#!/usr/bin/env python3
"""
Shared utilities for Apple Photos database operations.
All scripts use this module for consistent database access and data formatting.
"""

import sqlite3
import os
import sys
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from pathlib import Path

# Python version check
if sys.version_info < (3, 9):
    print("Error: Python 3.9 or higher is required", file=sys.stderr)
    sys.exit(1)


# Core Data reference date (January 1, 2001 00:00:00 UTC)
CORE_DATA_EPOCH = datetime(2001, 1, 1, 0, 0, 0)


def find_photos_db(custom_path: Optional[str] = None) -> str:
    """
    Find the Photos.sqlite database.
    
    Args:
        custom_path: Optional custom path to Photos library or database
        
    Returns:
        Path to Photos.sqlite
        
    Raises:
        FileNotFoundError: If database cannot be found
    """
    if custom_path:
        # Check if it's a direct path to the database
        if custom_path.endswith('.sqlite') and os.path.exists(custom_path):
            return custom_path
        # Check if it's a Photos library
        if custom_path.endswith('.photoslibrary'):
            db_path = os.path.join(custom_path, 'database', 'Photos.sqlite')
            if os.path.exists(db_path):
                return db_path
    
    # Default location
    default_library = os.path.expanduser('~/Pictures/Photos Library.photoslibrary')
    default_db = os.path.join(default_library, 'database', 'Photos.sqlite')
    
    if os.path.exists(default_db):
        return default_db
    
    raise FileNotFoundError(
        f"Photos database not found. Searched:\n"
        f"  - {default_db}\n"
        f"Please specify the path using --library or --db-path"
    )


def connect_db(db_path: str) -> sqlite3.Connection:
    """
    Connect to Photos database in read-only mode.
    
    Args:
        db_path: Path to Photos.sqlite
        
    Returns:
        SQLite connection
    """
    # Use read-only mode with URI
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def coredata_to_datetime(timestamp: Optional[float]) -> Optional[datetime]:
    """
    Convert Core Data timestamp to Python datetime.
    Core Data timestamps are seconds since 2001-01-01 00:00:00 UTC.
    
    Args:
        timestamp: Core Data timestamp (float)
        
    Returns:
        datetime object or None if timestamp is None
    """
    if timestamp is None:
        return None
    return CORE_DATA_EPOCH + timedelta(seconds=timestamp)


def datetime_to_coredata(dt: datetime) -> float:
    """
    Convert Python datetime to Core Data timestamp.
    
    Args:
        dt: datetime object
        
    Returns:
        Core Data timestamp (seconds since 2001-01-01)
    """
    delta = dt - CORE_DATA_EPOCH
    return delta.total_seconds()


def format_size(bytes_size: Optional[int]) -> str:
    """
    Format byte size to human-readable string.
    
    Args:
        bytes_size: Size in bytes
        
    Returns:
        Human-readable size string (e.g., "1.5 GB")
    """
    if bytes_size is None or bytes_size == 0:
        return "0 B"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    size = float(bytes_size)
    unit_index = 0
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"


def output_json(data: Any, output_file: Optional[str] = None, pretty: bool = True) -> None:
    """
    Output data as JSON to file or stdout.
    
    Args:
        data: Data to serialize
        output_file: Optional output file path
        pretty: Whether to pretty-print JSON
    """
    json_str = json.dumps(data, indent=2 if pretty else None)
    
    if output_file:
        with open(output_file, 'w') as f:
            f.write(json_str)
        print(f"Output written to: {output_file}", file=sys.stderr)
    else:
        print(json_str)


def get_asset_kind_name(kind: int) -> str:
    """
    Convert ZKIND value to human-readable name.
    
    Args:
        kind: ZKIND value from ZASSET table
        
    Returns:
        Human-readable asset type name
    """
    kinds = {
        0: 'photo',
        1: 'video',
    }
    return kinds.get(kind, f'unknown_{kind}')


def is_screenshot(row: sqlite3.Row) -> bool:
    """Check if an asset is a screenshot."""
    return bool(row['ZISDETECTEDSCREENSHOT'])


def is_burst(row: sqlite3.Row) -> bool:
    """Check if an asset is part of a burst sequence."""
    avalanche_kind = row.get('ZAVALANCHEKIND')
    return avalanche_kind is not None and avalanche_kind > 0


def is_favorite(row: sqlite3.Row) -> bool:
    """Check if an asset is marked as favorite."""
    return bool(row.get('ZFAVORITE', 0))


def is_hidden(row: sqlite3.Row) -> bool:
    """Check if an asset is hidden."""
    return bool(row.get('ZHIDDEN', 0))


def is_trashed(row: sqlite3.Row) -> bool:
    """Check if an asset is in the trash."""
    trashed_state = row.get('ZTRASHEDSTATE', 0)
    return trashed_state == 1


def get_quality_score(row: sqlite3.Row) -> Optional[float]:
    """
    Calculate a simple quality score from multiple quality attributes.
    Higher is better. Returns None if no quality data available.
    
    Uses:
    - ZPLEASANTCOMPOSITIONSCORE (higher is better)
    - ZPLEASANTLIGHTINGSCORE (higher is better)
    - ZFAILURESCORE (lower is better, so we invert)
    - ZNOISESCORE (lower is better, so we invert)
    
    All scores are typically in range [0, 1].
    """
    scores = []
    
    # Positive scores (higher is better)
    if row.get('ZPLEASANTCOMPOSITIONSCORE') is not None:
        scores.append(row['ZPLEASANTCOMPOSITIONSCORE'])
    if row.get('ZPLEASANTLIGHTINGSCORE') is not None:
        scores.append(row['ZPLEASANTLIGHTINGSCORE'])
    
    # Negative scores (lower is better, so invert)
    if row.get('ZFAILURESCORE') is not None:
        scores.append(1.0 - row['ZFAILURESCORE'])
    if row.get('ZNOISESCORE') is not None:
        scores.append(1.0 - row['ZNOISESCORE'])
    
    if not scores:
        return None
    
    return sum(scores) / len(scores)


def format_date_range(start: Optional[datetime], end: Optional[datetime]) -> str:
    """Format a date range as a human-readable string."""
    if start is None and end is None:
        return "Unknown"
    if start is None:
        return f"Until {end.strftime('%Y-%m-%d')}"
    if end is None:
        return f"From {start.strftime('%Y-%m-%d')}"
    if start.date() == end.date():
        return start.strftime('%Y-%m-%d')
    return f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"


class PhotosDB:
    """Context manager for Photos database connection."""
    
    def __init__(self, db_path: Optional[str] = None, library_path: Optional[str] = None):
        """
        Initialize database connection.
        
        Args:
            db_path: Direct path to Photos.sqlite
            library_path: Path to Photos library (will append /database/Photos.sqlite)
        """
        if db_path:
            self.db_path = db_path
        elif library_path:
            self.db_path = os.path.join(library_path, 'database', 'Photos.sqlite')
        else:
            self.db_path = find_photos_db()
        
        self.conn: Optional[sqlite3.Connection] = None
    
    def __enter__(self) -> sqlite3.Connection:
        """Open connection."""
        self.conn = connect_db(self.db_path)
        return self.conn
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close connection."""
        if self.conn:
            self.conn.close()


# Query builders
def build_asset_query(
    where_clauses: Optional[List[str]] = None,
    join_additional: bool = False,
    join_computed: bool = False,
    order_by: Optional[str] = None,
    limit: Optional[int] = None
) -> str:
    """
    Build a query for ZASSET table with optional joins and filters.
    
    Args:
        where_clauses: List of WHERE conditions
        join_additional: Join ZADDITIONALASSETATTRIBUTES
        join_computed: Join ZCOMPUTEDASSETATTRIBUTES
        order_by: ORDER BY clause
        limit: LIMIT value
        
    Returns:
        SQL query string
    """
    # Base select
    query = "SELECT a.*"
    
    if join_additional:
        query += """,
            aa.ZORIGINALFILESIZE,
            aa.ZORIGINALHEIGHT,
            aa.ZORIGINALWIDTH"""
    
    if join_computed:
        query += """,
            ca.ZFAILURESCORE,
            ca.ZNOISESCORE,
            ca.ZPLEASANTCOMPOSITIONSCORE,
            ca.ZPLEASANTLIGHTINGSCORE,
            ca.ZPLEASANTPATTERNSCORE,
            ca.ZPLEASANTPERSPECTIVESCORE,
            ca.ZPLEASANTPOSTPROCESSINGSCORE,
            ca.ZPLEASANTREFLECTIONSSCORE,
            ca.ZPLEASANTSYMMETRYSCORE"""
    
    query += "\nFROM ZASSET a"
    
    if join_additional:
        query += "\nLEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON a.Z_PK = aa.ZASSET"
    
    if join_computed:
        query += "\nLEFT JOIN ZCOMPUTEDASSETATTRIBUTES ca ON a.Z_PK = ca.ZASSET"
    
    if where_clauses:
        query += "\nWHERE " + " AND ".join(where_clauses)
    
    if order_by:
        query += f"\nORDER BY {order_by}"
    
    if limit:
        query += f"\nLIMIT {limit}"
    
    return query
