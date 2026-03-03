#!/usr/bin/env python3
"""
Smart export of photos organized by year/month, person, album, or location.
Uses AppleScript to trigger actual exports from Photos.app.
"""

import argparse
import sys
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

from _common import (
    PhotosDB, coredata_to_datetime, format_size
)


def generate_export_plan(
    db_path: Optional[str] = None,
    organize_by: str = 'year_month',
    favorites_only: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    person_name: Optional[str] = None,
    album_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate an export plan showing what will be exported.
    
    Args:
        db_path: Path to database
        organize_by: How to organize ('year_month', 'person', 'album', 'location')
        favorites_only: Only export favorites
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)
        person_name: Export only photos with this person
        album_name: Export only from this album
        
    Returns:
        Export plan dictionary
    """
    with PhotosDB(db_path) as conn:
        cursor = conn.cursor()
        
        # Build WHERE clauses
        where_clauses = ['a.ZTRASHEDSTATE != 1']
        
        if favorites_only:
            where_clauses.append('a.ZFAVORITE = 1')
        
        if start_date:
            # Convert to Core Data timestamp
            from datetime import datetime
            from _common import datetime_to_coredata
            dt = datetime.fromisoformat(start_date)
            timestamp = datetime_to_coredata(dt)
            where_clauses.append(f'a.ZDATECREATED >= {timestamp}')
        
        if end_date:
            from datetime import datetime
            from _common import datetime_to_coredata
            dt = datetime.fromisoformat(end_date)
            timestamp = datetime_to_coredata(dt)
            where_clauses.append(f'a.ZDATECREATED <= {timestamp}')
        
        # Base query
        query = f"""
            SELECT 
                a.Z_PK,
                a.ZFILENAME,
                a.ZDATECREATED,
                a.ZLATITUDE,
                a.ZLONGITUDE,
                aa.ZORIGINALFILESIZE
            FROM ZASSET a
            LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON a.Z_PK = aa.ZASSET
        """
        
        # Add person filter if specified
        if person_name:
            query += """
                JOIN ZDETECTEDFACE df ON a.Z_PK = df.ZASSET
                JOIN ZPERSON p ON df.ZPERSON = p.Z_PK
            """
            where_clauses.append(f"p.ZFULLNAME = '{person_name}'")
        
        # Add album filter if specified
        if album_name:
            query += """
                JOIN Z_27ASSETS ga ON a.Z_PK = ga.Z_3ASSETS
                JOIN ZGENERICALBUM album ON ga.Z_27ALBUMS = album.Z_PK
            """
            where_clauses.append(f"album.ZTITLE = '{album_name}'")
        
        query += " WHERE " + " AND ".join(where_clauses)
        query += " ORDER BY a.ZDATECREATED"
        
        cursor.execute(query)
        
        # Organize results
        organized = defaultdict(list)
        total_size = 0
        total_count = 0
        
        for row in cursor.fetchall():
            asset_id = row['Z_PK']
            filename = row['ZFILENAME']
            created = coredata_to_datetime(row['ZDATECREATED'])
            size = row['ZORIGINALFILESIZE'] or 0
            
            total_size += size
            total_count += 1
            
            # Determine organization key
            if organize_by == 'year_month':
                if created:
                    key = f"{created.year}/{created.strftime('%m-%B')}"
                else:
                    key = "Unknown"
            
            elif organize_by == 'person' and person_name:
                key = person_name
            
            elif organize_by == 'album' and album_name:
                key = album_name
            
            elif organize_by == 'location':
                if row['ZLATITUDE'] and row['ZLONGITUDE']:
                    # Round to 2 decimal places for grouping
                    lat = round(row['ZLATITUDE'], 2)
                    lon = round(row['ZLONGITUDE'], 2)
                    key = f"loc_{lat}_{lon}"
                else:
                    key = "no_location"
            
            else:
                key = "all"
            
            organized[key].append({
                'id': asset_id,
                'filename': filename,
                'created': created.isoformat() if created else None,
                'size': size,
            })
        
        # Convert to serializable format
        plan = {
            'organize_by': organize_by,
            'filters': {
                'favorites_only': favorites_only,
                'start_date': start_date,
                'end_date': end_date,
                'person_name': person_name,
                'album_name': album_name,
            },
            'folders': {},
            'summary': {
                'total_photos': total_count,
                'total_size': total_size,
                'total_size_formatted': format_size(total_size),
                'folder_count': len(organized),
            }
        }
        
        for folder_name, items in organized.items():
            folder_size = sum(item['size'] for item in items)
            plan['folders'][folder_name] = {
                'count': len(items),
                'size': folder_size,
                'size_formatted': format_size(folder_size),
                'items': items,
            }
        
        return plan


def export_with_applescript(
    asset_ids: List[int],
    output_dir: str,
    folder_name: str = ""
) -> bool:
    """
    Use AppleScript to export photos from Photos.app.
    
    Args:
        asset_ids: List of asset IDs to export
        output_dir: Base output directory
        folder_name: Subfolder name (if organizing)
        
    Returns:
        True if successful
    """
    # Create output directory
    if folder_name:
        export_path = os.path.join(output_dir, folder_name)
    else:
        export_path = output_dir
    
    Path(export_path).mkdir(parents=True, exist_ok=True)
    
    # Convert asset IDs to string list
    id_list = ", ".join(str(id) for id in asset_ids)
    
    # AppleScript to export photos
    # Note: This is a simplified version. Real implementation would need
    # to map Z_PK to Photos.app media items, which is complex.
    applescript = f'''
    tell application "Photos"
        -- Note: This is a placeholder. Actual implementation requires
        -- mapping database Z_PK to Photos.app media items.
        -- This would typically involve:
        -- 1. Getting all media items
        -- 2. Matching by filename/date
        -- 3. Exporting matched items
        
        display dialog "Export not yet implemented. This would export to: {export_path}"
    end tell
    '''
    
    try:
        result = subprocess.run(
            ['osascript', '-e', applescript],
            capture_output=True,
            text=True,
            timeout=300
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Error running AppleScript: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Smart export of Apple Photos',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show export plan for all photos by year/month
  %(prog)s --output-dir ~/Pictures/Export --plan-only
  
  # Export favorites from 2025 organized by month
  %(prog)s --output-dir ~/Pictures/Export --favorites --start-date 2025-01-01
  
  # Export photos with a specific person
  %(prog)s --output-dir ~/Pictures/Export --person "Jonah" --organize-by person
  
  # Export specific album
  %(prog)s --output-dir ~/Pictures/Export --album "Vacation 2025" --organize-by album

Note: Actual export requires Photos.app and proper permissions.
        """
    )
    parser.add_argument('--db-path', help='Path to Photos.sqlite database')
    parser.add_argument('--library', help='Path to Photos library')
    parser.add_argument('--output-dir', required=True, help='Output directory for exports')
    parser.add_argument('--organize-by', choices=['year_month', 'person', 'album', 'location'],
                        default='year_month', help='How to organize exports')
    parser.add_argument('--favorites', action='store_true', help='Export only favorites')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--person', help='Export only photos with this person')
    parser.add_argument('--album', help='Export only from this album')
    parser.add_argument('--plan-only', action='store_true',
                        help='Show export plan without actually exporting')
    
    args = parser.parse_args()
    
    try:
        db_path = args.db_path or args.library
        
        plan = generate_export_plan(
            db_path=db_path,
            organize_by=args.organize_by,
            favorites_only=args.favorites,
            start_date=args.start_date,
            end_date=args.end_date,
            person_name=args.person,
            album_name=args.album,
        )
        
        # Show plan
        print("📤 EXPORT PLAN")
        print("=" * 50)
        print(f"Organization: {plan['organize_by']}")
        print(f"Total photos: {plan['summary']['total_photos']:,}")
        print(f"Total size: {plan['summary']['total_size_formatted']}")
        print(f"Folders: {plan['summary']['folder_count']}")
        print()
        
        print("Folders:")
        for folder_name, folder_info in sorted(plan['folders'].items()):
            print(f"  {folder_name}/")
            print(f"    {folder_info['count']:,} items, {folder_info['size_formatted']}")
        print()
        
        if args.plan_only:
            print("(Plan only - no actual export performed)")
            return 0
        
        # Perform export
        print(f"Exporting to: {args.output_dir}")
        print()
        
        for folder_name, folder_info in plan['folders'].items():
            print(f"Exporting {folder_name}... ", end='', flush=True)
            asset_ids = [item['id'] for item in folder_info['items']]
            
            success = export_with_applescript(asset_ids, args.output_dir, folder_name)
            
            if success:
                print("✓")
            else:
                print("✗ (failed)")
        
        print()
        print("Note: AppleScript export is not fully implemented.")
        print("This is a placeholder that shows the structure.")
        
        return 0
    
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error generating export plan: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
