#!/usr/bin/env python3
"""
Location / Travel Mapper: analyze where your photos were taken.
Cluster GPS coordinates into locations, identify trips, find most-photographed places.
"""

import argparse
import math
import sys
from collections import defaultdict
from typing import Any, Optional

from _common import PhotosDB, coredata_to_datetime, format_size, output_json


# Haversine distance in km
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two GPS coordinates in kilometers."""
    r = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def cluster_locations(
    photos: list[dict[str, Any]],
    radius_km: float = 1.0,
) -> list[dict[str, Any]]:
    """
    Cluster photos by GPS proximity using simple greedy clustering.

    Args:
        photos: List of photo dicts with latitude/longitude
        radius_km: Cluster radius in km

    Returns:
        List of location clusters
    """
    unassigned = list(range(len(photos)))
    clusters = []

    while unassigned:
        # Pick the first unassigned photo as seed
        seed_idx = unassigned[0]
        seed = photos[seed_idx]
        cluster_indices = [seed_idx]
        remaining = []

        for idx in unassigned[1:]:
            p = photos[idx]
            dist = haversine_km(seed["latitude"], seed["longitude"], p["latitude"], p["longitude"])
            if dist <= radius_km:
                cluster_indices.append(idx)
            else:
                remaining.append(idx)

        # Compute cluster centroid
        cluster_photos = [photos[i] for i in cluster_indices]
        avg_lat = sum(p["latitude"] for p in cluster_photos) / len(cluster_photos)
        avg_lon = sum(p["longitude"] for p in cluster_photos) / len(cluster_photos)

        clusters.append(
            {
                "centroid_lat": round(avg_lat, 4),
                "centroid_lon": round(avg_lon, 4),
                "photo_count": len(cluster_photos),
                "photos": cluster_photos,
            }
        )

        unassigned = remaining

    return clusters


def analyze_locations(
    db_path: Optional[str] = None,
    cluster_radius_km: float = 1.0,
    year: Optional[str] = None,
    min_photos: int = 3,
) -> dict[str, Any]:
    """
    Analyze photo locations and identify trips/places.

    Args:
        db_path: Path to database
        cluster_radius_km: Radius in km for clustering nearby photos
        year: Filter to specific year
        min_photos: Minimum photos to include a location cluster

    Returns:
        Location analysis dictionary
    """
    with PhotosDB(db_path) as conn:
        cursor = conn.cursor()

        where_clauses = [
            "a.ZTRASHEDSTATE != 1",
            "a.ZLATITUDE IS NOT NULL",
            "a.ZLONGITUDE IS NOT NULL",
            "a.ZLATITUDE != 0",
            "a.ZLONGITUDE != 0",
        ]

        if year:
            where_clauses.append(f"strftime('%Y', datetime(a.ZDATECREATED + 978307200, 'unixepoch')) = '{year}'")

        query = f"""
            SELECT
                a.Z_PK,
                a.ZFILENAME,
                a.ZDATECREATED,
                a.ZKIND,
                a.ZLATITUDE,
                a.ZLONGITUDE,
                a.ZFAVORITE,
                aa.ZORIGINALFILESIZE
            FROM ZASSET a
            LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON a.Z_PK = aa.ZASSET
            WHERE {" AND ".join(where_clauses)}
            ORDER BY a.ZDATECREATED
        """

        cursor.execute(query)

        photos_with_location = []
        total_assets = 0

        for row in cursor.fetchall():
            created = coredata_to_datetime(row["ZDATECREATED"])
            photos_with_location.append(
                {
                    "id": row["Z_PK"],
                    "filename": row["ZFILENAME"],
                    "created": created.isoformat() if created else None,
                    "created_dt": created,
                    "latitude": row["ZLATITUDE"],
                    "longitude": row["ZLONGITUDE"],
                    "kind": "photo" if row["ZKIND"] == 0 else "video",
                    "is_favorite": bool(row["ZFAVORITE"]),
                    "size": row["ZORIGINALFILESIZE"] or 0,
                }
            )
            total_assets += 1

        # Count total assets (with and without location)
        cursor.execute("""
            SELECT COUNT(*) as total FROM ZASSET WHERE ZTRASHEDSTATE != 1
        """)
        total_all = cursor.fetchone()["total"]
        without_location = total_all - total_assets

        # Cluster locations
        clusters = cluster_locations(photos_with_location, cluster_radius_km)

        # Filter to significant clusters and enrich
        locations = []
        for cluster in clusters:
            if cluster["photo_count"] < min_photos:
                continue

            cluster_photos = cluster["photos"]

            # Date range
            dates = [p["created_dt"] for p in cluster_photos if p["created_dt"]]
            first = min(dates) if dates else None
            last = max(dates) if dates else None

            # Count by year-month
            by_month = defaultdict(int)
            for p in cluster_photos:
                if p["created_dt"]:
                    key = p["created_dt"].strftime("%Y-%m")
                    by_month[key] += 1

            # Identify potential trips (>= 5 photos, spanning multiple hours)
            is_trip = False
            if first and last and len(cluster_photos) >= 5:
                duration_hours = (last - first).total_seconds() / 3600
                is_trip = duration_hours >= 4

            favorites = sum(1 for p in cluster_photos if p["is_favorite"])
            total_size = sum(p["size"] for p in cluster_photos)

            # Get people at this location
            photo_ids = [p["id"] for p in cluster_photos]
            people_at_location = []
            if photo_ids:
                placeholders = ",".join("?" * len(photo_ids))
                cursor.execute(
                    f"""
                    SELECT DISTINCT p.ZFULLNAME, COUNT(df.ZASSET) as count
                    FROM ZPERSON p
                    JOIN ZDETECTEDFACE df ON p.Z_PK = df.ZPERSON
                    WHERE df.ZASSET IN ({placeholders})
                    AND p.ZFULLNAME IS NOT NULL AND p.ZFULLNAME != ''
                    GROUP BY p.Z_PK
                    ORDER BY count DESC
                    LIMIT 5
                """,
                    photo_ids,
                )
                people_at_location = [{"name": row["ZFULLNAME"], "count": row["count"]} for row in cursor.fetchall()]

            locations.append(
                {
                    "centroid_lat": cluster["centroid_lat"],
                    "centroid_lon": cluster["centroid_lon"],
                    "photo_count": cluster["photo_count"],
                    "favorites": favorites,
                    "total_size": total_size,
                    "total_size_formatted": format_size(total_size),
                    "first_photo": first.isoformat() if first else None,
                    "last_photo": last.isoformat() if last else None,
                    "is_trip": is_trip,
                    "by_month": dict(sorted(by_month.items())),
                    "people": people_at_location,
                }
            )

        # Sort by photo count
        locations.sort(key=lambda x: x["photo_count"], reverse=True)

        # Travel timeline: identify distinct trips (clusters of photos far from "home")
        trips = [loc for loc in locations if loc["is_trip"]]

        return {
            "locations": locations,
            "trips": trips,
            "summary": {
                "total_with_location": total_assets,
                "total_without_location": without_location,
                "location_coverage": round(total_assets / total_all * 100, 1) if total_all else 0,
                "unique_locations": len(locations),
                "identified_trips": len(trips),
                "cluster_radius_km": cluster_radius_km,
            },
        }


def format_summary(data: dict[str, Any]) -> str:
    """Format location analysis as human-readable summary."""
    lines = []
    lines.append("📍 LOCATION / TRAVEL MAPPER")
    lines.append("=" * 50)
    lines.append("")

    summary = data["summary"]
    lines.append(f"Photos with GPS: {summary['total_with_location']:,} ({summary['location_coverage']}%)")
    lines.append(f"Without GPS: {summary['total_without_location']:,}")
    lines.append(f"Unique locations: {summary['unique_locations']:,}")
    lines.append(f"Possible trips: {summary['identified_trips']:,}")
    lines.append("")

    lines.append("Top Locations:")
    for i, loc in enumerate(data["locations"][:15], 1):
        trip_flag = " 🧳" if loc["is_trip"] else ""
        fav_str = f" ⭐{loc['favorites']}" if loc["favorites"] else ""
        lines.append(f"  {i:>3}. ({loc['centroid_lat']}, {loc['centroid_lon']})")
        lines.append(f"       {loc['photo_count']:,} photos{fav_str}{trip_flag} | {loc['total_size_formatted']}")

        if loc["first_photo"] and loc["last_photo"]:
            lines.append(f"       📅 {loc['first_photo'][:10]} → {loc['last_photo'][:10]}")

        if loc["people"]:
            names = ", ".join(p["name"] for p in loc["people"][:3])
            lines.append(f"       👥 {names}")

    lines.append("")

    if data["trips"]:
        lines.append("Identified Trips:")
        for trip in data["trips"][:10]:
            lines.append(f"  🧳 ({trip['centroid_lat']}, {trip['centroid_lon']})")
            lines.append(f"     {trip['photo_count']} photos, {trip['first_photo'][:10]} → {trip['last_photo'][:10]}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze photo locations and identify trips",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --human
  %(prog)s --radius 2.0 --year 2025
  %(prog)s --min-photos 10 --output locations.json
        """,
    )
    parser.add_argument("--db-path", help="Path to Photos.sqlite database")
    parser.add_argument("--library", help="Path to Photos library")
    parser.add_argument("--radius", type=float, default=1.0, help="Cluster radius in km (default: 1.0)")
    parser.add_argument("--year", help="Filter to specific year (YYYY)")
    parser.add_argument("--min-photos", type=int, default=3, help="Minimum photos per location cluster (default: 3)")
    parser.add_argument("-o", "--output", help="Output JSON file")
    parser.add_argument("--human", action="store_true", help="Output human-readable summary")

    args = parser.parse_args()

    try:
        db_path = args.db_path or args.library
        result = analyze_locations(
            db_path=db_path,
            cluster_radius_km=args.radius,
            year=args.year,
            min_photos=args.min_photos,
        )

        if args.human:
            print(format_summary(result))
        else:
            output_json(result, args.output)
            if not args.output:
                print("\n" + format_summary(result), file=sys.stderr)

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error analyzing locations: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
