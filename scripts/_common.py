#!/usr/bin/env python3
"""
Shared utilities for Apple Photos database operations.
All scripts use this module for consistent database access and data formatting.
"""

import argparse
import contextlib
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import IntEnum
from pathlib import Path
from typing import Any

from _schema import PhotosConnection, SchemaUnsupportedError, get_schema

logger = logging.getLogger("apple_photos_cleaner")


class ExitCode(IntEnum):
    """Process exit codes. Agents branch on these, so they are part of the CLI contract."""

    OK = 0
    ERROR = 1  # unexpected failure
    USAGE = 2  # bad arguments (argparse also exits 2)
    DB_NOT_FOUND = 3
    PERMISSION_DENIED = 4  # usually missing Full Disk Access
    SCHEMA_UNSUPPORTED = 5
    USER_ABORTED = 10
    CONFIRMATION_REQUIRED = 11


class DatabaseNotFoundError(FileNotFoundError):
    """No Photos.sqlite at the given or default location."""


# Core Data reference date (January 1, 2001 00:00:00 UTC)
CORE_DATA_EPOCH = datetime(2001, 1, 1, 0, 0, 0)
# Seconds between the Unix epoch and the Core Data epoch
CORE_DATA_UNIX_OFFSET = 978307200


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application.

    Args:
        verbose: If True, set DEBUG level; otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def find_photos_db(custom_path: str | None = None) -> str:
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
        if custom_path.endswith(".sqlite") and os.path.exists(custom_path):
            return custom_path
        # Check if it's a Photos library
        if custom_path.endswith(".photoslibrary"):
            db_path = os.path.join(custom_path, "database", "Photos.sqlite")
            if os.path.exists(db_path):
                return db_path

    # Default location
    default_library = os.path.expanduser("~/Pictures/Photos Library.photoslibrary")
    default_db = os.path.join(default_library, "database", "Photos.sqlite")

    if os.path.exists(default_db):
        return default_db

    raise DatabaseNotFoundError(
        f"Photos database not found. Searched:\n  - {default_db}\nPlease specify the path using --library or --db-path"
    )


def connect_db(db_path: str) -> sqlite3.Connection:
    """
    Connect to Photos database in read-only mode.

    Args:
        db_path: Path to Photos.sqlite

    Returns:
        SQLite connection

    Raises:
        FileNotFoundError: If database file doesn't exist
        PermissionError: If database file can't be read
        sqlite3.OperationalError: If connection fails
    """
    if not os.path.exists(db_path):
        raise DatabaseNotFoundError(f"Database not found: {db_path}")
    # os.access() doesn't see macOS privacy (TCC) denials; actually opening the file does.
    try:
        open(db_path, "rb").close()
    except PermissionError as e:
        raise PermissionError(
            f"Cannot read database (permission denied): {db_path}\n"
            "Hint: grant Full Disk Access to your terminal or agent app in "
            "System Settings > Privacy & Security > Full Disk Access."
        ) from e

    # Use read-only mode with URI; busy_timeout retries if Photos.app holds a lock
    # as_uri() percent-encodes the path, so a "?" or "#" in a library name stays part of it.
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5, factory=PhotosConnection)
    except sqlite3.OperationalError as e:
        raise sqlite3.OperationalError(
            f"Failed to open database: {db_path} — {e}\n"
            "Hint: Close Photos.app or check if the file is a valid SQLite database."
        ) from e
    # Second line of defence behind mode=ro: refuse anything but reads at prepare time.
    conn.set_authorizer(_deny_writes)
    conn.row_factory = sqlite3.Row
    return conn


_READ_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_FUNCTION,
        getattr(sqlite3, "SQLITE_RECURSIVE", 33),  # module constant added in Python 3.11
    }
)
# Use these as PRAGMA statements (see _schema). The table-valued pragma form trips
# the guard on older SQLite, which authorizes internal sqlite_master UPDATEs for it.
_READ_ONLY_PRAGMAS = frozenset({"table_info", "table_xinfo"})


def _deny_writes(action: int, arg1: str | None, arg2: str | None, db_name: str | None, trigger: str | None) -> int:
    """SQLite authorizer allowing only reads; every other statement fails to prepare."""
    if action in _READ_ACTIONS:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg1 in _READ_ONLY_PRAGMAS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def coredata_to_datetime(timestamp: float | None) -> datetime | None:
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


def coredata_to_local(timestamp: float | None, tz_offset: int | None) -> datetime | None:
    """
    Convert a Core Data timestamp to the naive local wall-clock time it was taken at.

    Photos records each asset's UTC offset at capture time
    (ZADDITIONALASSETATTRIBUTES.ZTIMEZONEOFFSET, in seconds). When it is known it wins,
    so a photo taken at 23:30 in Chicago stays 23:30 even when analyzed in Tokyo.
    When it is missing, fall back to the system time zone.

    Use this for anything bucketed by hour, day, month or year. coredata_to_datetime()
    stays UTC.
    """
    if timestamp is None:
        return None
    if tz_offset is not None:
        return CORE_DATA_EPOCH + timedelta(seconds=timestamp + tz_offset)
    return datetime.fromtimestamp(timestamp + CORE_DATA_UNIX_OFFSET)


def has_timezone_offset(cursor: sqlite3.Cursor) -> bool:
    """Whether this library's schema records a per-asset capture time zone offset."""
    return get_schema(cursor).has("asset_attrs.tz_offset")


def tz_offset_sql(tz_offset_available: bool, attrs: str = "aa") -> str:
    """SELECT expression for the capture offset; NULL when the schema lacks the column."""
    return f"{attrs}.ZTIMEZONEOFFSET" if tz_offset_available else "NULL"


def local_datetime_sql(tz_offset_available: bool, asset: str = "a", attrs: str = "aa") -> str:
    """
    SQL expression for an asset's local capture time, the SQL twin of coredata_to_local().

    Requires `LEFT JOIN ZADDITIONALASSETATTRIBUTES {attrs}` in the query when the
    offset is available. Wrap it in strftime() to bucket by year, month, day or hour.
    """
    unix = f"{asset}.ZDATECREATED + {CORE_DATA_UNIX_OFFSET}"
    if not tz_offset_available:
        return f"datetime({unix}, 'unixepoch', 'localtime')"
    return (
        f"(CASE WHEN {attrs}.ZTIMEZONEOFFSET IS NOT NULL "
        f"THEN datetime({unix} + {attrs}.ZTIMEZONEOFFSET, 'unixepoch') "
        f"ELSE datetime({unix}, 'unixepoch', 'localtime') END)"
    )


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


def format_size(bytes_size: int | None) -> str:
    """
    Format byte size to human-readable string.

    Args:
        bytes_size: Size in bytes

    Returns:
        Human-readable size string (e.g., "1.5 GB")
    """
    if bytes_size is None or bytes_size == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(bytes_size)
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"


def output_json(data: Any, output_file: str | None = None, pretty: bool = True) -> None:
    """
    Output data as JSON to file or stdout.

    Args:
        data: Data to serialize
        output_file: Optional output file path
        pretty: Whether to pretty-print JSON

    Raises:
        OSError: If output file cannot be written
    """
    json_str = json.dumps(data, indent=2 if pretty else None)

    if output_file:
        try:
            with open(output_file, "w") as f:
                f.write(json_str)
        except OSError as e:
            logger.error("Cannot write to %s: %s", output_file, e)
            raise
        logger.info("Output written to: %s", output_file)
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
        0: "photo",
        1: "video",
    }
    return kinds.get(kind, f"unknown_{kind}")


def is_screenshot(row: sqlite3.Row) -> bool:
    """Check if an asset is a screenshot."""
    return bool(row["ZISDETECTEDSCREENSHOT"])


def is_burst(row) -> bool:
    """Check if an asset is part of a burst sequence."""
    d = dict(row) if not isinstance(row, dict) else row
    avalanche_kind = d.get("ZAVALANCHEKIND")
    return avalanche_kind is not None and avalanche_kind > 0


def is_favorite(row) -> bool:
    """Check if an asset is marked as favorite."""
    d = dict(row) if not isinstance(row, dict) else row
    return bool(d.get("ZFAVORITE", 0))


def is_hidden(row) -> bool:
    """Check if an asset is hidden."""
    d = dict(row) if not isinstance(row, dict) else row
    return bool(d.get("ZHIDDEN", 0))


def is_trashed(row) -> bool:
    """Check if an asset is in the trash."""
    d = dict(row) if not isinstance(row, dict) else row
    return bool(d.get("ZTRASHEDSTATE", 0) == 1)


def get_quality_score(row) -> float | None:
    """
    Calculate a simple quality score from multiple quality attributes.
    Higher is better. Returns None if no quality data available.

    Uses:
    - ZPLEASANTCOMPOSITIONSCORE (higher is better)
    - ZPLEASANTLIGHTINGSCORE (higher is better)
    - ZFAILURESCORE (lower is better, so we invert)
    - ZNOISESCORE (lower is better, so we invert)

    All scores are typically in range [0, 1].

    Accepts both dict and sqlite3.Row objects.
    """
    # sqlite3.Row supports keys() but not .get(); normalize to dict
    if not isinstance(row, dict):
        row = dict(row)

    scores: list[float] = []

    # Positive scores (higher is better)
    if row.get("ZPLEASANTCOMPOSITIONSCORE") is not None:
        scores.append(row["ZPLEASANTCOMPOSITIONSCORE"])
    if row.get("ZPLEASANTLIGHTINGSCORE") is not None:
        scores.append(row["ZPLEASANTLIGHTINGSCORE"])

    # Negative scores (lower is better, so invert)
    if row.get("ZFAILURESCORE") is not None:
        scores.append(1.0 - row["ZFAILURESCORE"])
    if row.get("ZNOISESCORE") is not None:
        scores.append(1.0 - row["ZNOISESCORE"])

    if not scores:
        return None

    return sum(scores) / len(scores)


def format_date_range(start: datetime | None, end: datetime | None) -> str:
    """Format a date range as a human-readable string."""
    if start is not None and end is not None:
        if start.date() == end.date():
            return start.strftime("%Y-%m-%d")
        return f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"
    if start is not None:
        return f"From {start.strftime('%Y-%m-%d')}"
    if end is not None:
        return f"Until {end.strftime('%Y-%m-%d')}"
    return "Unknown"


def detect_face_schema(cursor: sqlite3.Cursor) -> dict[str, str]:
    """
    Detect which schema version Photos is using for ZDETECTEDFACE table.

    Returns dict with 'person_fk' and 'asset_fk' keys pointing to correct column names.

    Older macOS: ZPERSON, ZASSET
    Newer macOS (Sequoia+): ZPERSONFORFACE, ZASSETFORFACE
    """
    schema = get_schema(cursor)
    # Fall back to the pre-Sequoia names when the table is missing, so queries fail loudly
    # on the absent table rather than on a None column.
    return {
        "person_fk": schema.col("face.person_fk") or "ZPERSON",
        "asset_fk": schema.col("face.asset_fk") or "ZASSET",
    }


class PhotosDB:
    """Context manager for Photos database connection."""

    def __init__(self, db_path: str | None = None, library_path: str | None = None):
        """
        Initialize database connection.

        Args:
            db_path: Direct path to Photos.sqlite
            library_path: Path to Photos library (will append /database/Photos.sqlite)
        """
        # Scripts pass `args.db_path or args.library`, so a library bundle can arrive as db_path.
        if db_path and os.path.isdir(db_path):
            self.db_path = os.path.join(db_path, "database", "Photos.sqlite")
        elif db_path:
            self.db_path = db_path
        elif library_path:
            self.db_path = os.path.join(library_path, "database", "Photos.sqlite")
        else:
            self.db_path = find_photos_db()

        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        """Open connection."""
        self.conn = connect_db(self.db_path)
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close connection."""
        if self.conn:
            with contextlib.suppress(sqlite3.ProgrammingError):
                self.conn.close()


# Query builders
def build_asset_query(
    where_clauses: list[str] | None = None,
    join_additional: bool = False,
    join_computed: bool = False,
    order_by: str | None = None,
    limit: int | None = None,
    tz_offset_available: bool = False,
) -> str:
    """
    Build a query for ZASSET table with optional joins and filters.

    Args:
        where_clauses: List of WHERE conditions
        join_additional: Join ZADDITIONALASSETATTRIBUTES
        join_computed: Join ZCOMPUTEDASSETATTRIBUTES
        order_by: ORDER BY clause
        limit: LIMIT value
        tz_offset_available: Schema has ZTIMEZONEOFFSET (see has_timezone_offset);
            with join_additional, selects it as `tz_offset` for coredata_to_local()

    Returns:
        SQL query string
    """
    # Base select
    query = "SELECT a.*"

    if join_additional:
        query += (
            """,
            aa.ZORIGINALFILESIZE,
            aa.ZORIGINALHEIGHT,
            aa.ZORIGINALWIDTH,
            """
            + tz_offset_sql(tz_offset_available)
            + " AS tz_offset"
        )

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
        query += f"\nLIMIT {int(limit)}"

    return query


# ── Security helpers ─────────────────────────────────────────────────────────


def positive_int(value: str) -> int:
    """argparse type for counts and limits. SQLite reads a negative LIMIT as "no limit"."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def validate_year(year: str | None) -> str | None:
    """Validate that a year string is a 4-digit number.

    Args:
        year: Year string from CLI argument

    Returns:
        The validated year string, or None if input was None

    Raises:
        ValueError: If year is not a 4-digit number
    """
    if year is None:
        return None
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError(f"Year must be a 4-digit number, got: {year!r}")
    return year


def escape_applescript(s: str) -> str:
    """Escape a string for use inside AppleScript double-quotes.

    Handles backslashes first, then double-quotes, to avoid
    double-escaping.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')


# Photos exposes an asset's AppleScript `id` as "<UUID>/L0/001" for library assets.
LOCAL_IDENTIFIER_SUFFIX = "/L0/001"


def require_uuid_support(cursor: sqlite3.Cursor, operation: str) -> None:
    """Verify the ZASSET table exposes ZUUID.

    Targeting assets by UUID is what keeps AppleScript operations bounded to the
    assets the user actually reviewed. Filenames are not unique — the same
    IMG_0042.HEIC can appear many times across devices and re-imports — so a
    filename match can hit assets outside the previewed set. If the column is
    missing we refuse to proceed rather than silently falling back.

    Args:
        cursor: Open cursor on the Photos database.
        operation: Human-readable name of the caller, used in the error message.

    Raises:
        SchemaUnsupportedError: If ZASSET has no ZUUID column.
    """
    get_schema(cursor).require("asset.uuid", operation=f"{operation} (which targets assets by UUID)")


def build_identifier_lists(items: list[dict]) -> tuple[str, str]:
    """Build the AppleScript `id` and filename list literals for *items*.

    Both lists are positional: index *i* of the id list and index *i* of the
    name list describe the same asset, which lets the generated script confirm
    that a resolved item is the one the database pointed at.

    Args:
        items: Dicts carrying a "uuid" and a "filename".

    Returns:
        A ``(id_list, name_list)`` pair of comma-separated AppleScript literals.

    Raises:
        ValueError: If any item is missing a UUID.
    """
    missing = [item.get("filename", "<unknown>") for item in items if not item.get("uuid")]
    if missing:
        raise ValueError(
            f"Refusing to build an AppleScript: {len(missing)} item(s) have no UUID "
            f"(e.g. {missing[0]!r}). Matching by filename alone is unsafe."
        )

    id_list = ", ".join(f'"{escape_applescript(item["uuid"] + LOCAL_IDENTIFIER_SUFFIX)}"' for item in items)
    name_list = ", ".join(f'"{escape_applescript(item["filename"] or "")}"' for item in items)
    return id_list, name_list


def plan_token(command: str, params: dict[str, Any], uuids: list[str | None]) -> str:
    """Fingerprint exactly what a mutating command is about to do.

    The preview prints this token and execution requires it back via
    ``--confirm``. Approval therefore covers one specific set of assets, and an
    agent cannot approve a set it never showed the user. Any change to the
    candidates or to the parameters that selected them produces a new token.

    Args:
        command: Script name, so tokens are never valid across commands.
        params: Every argument that influences what gets selected or written.
        uuids: Asset UUIDs in the plan; order does not matter.

    Returns:
        16 hex characters (64 bits of SHA-256).
    """
    payload = json.dumps(
        {"command": command, "params": params, "uuids": sorted(u or "" for u in uuids)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def sanitize_folder_name(name: str) -> str:
    """Sanitize a string for safe use as a folder/file name.

    Strips path separators, dotfile prefixes, and other unsafe characters
    to prevent path-traversal attacks.
    """
    # Replace path separators and other unsafe chars with underscore
    safe = re.sub(r'[/\\:"<>|?*]', "_", name)
    # Remove dots (prevent hidden dirs and .. traversal)
    safe = re.sub(r"\.+", "_", safe)
    # Collapse runs of underscores and strip leading/trailing underscores
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe or "unnamed"


# ── Safe column / value helpers ──────────────────────────────────────────────


def _safe_col(row: dict, name: str, default=None):
    """Return column value if it exists, else *default*."""
    return row.get(name, default)


def _safe_float(val, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ── Shared CLI boilerplate ───────────────────────────────────────────────────


def run_script(
    description: str,
    analyze_fn: Callable,
    format_fn: Callable[[dict], str],
    extra_args_fn: Callable[[argparse.ArgumentParser], None] | None = None,
    epilog: str | None = None,
) -> int:
    """
    Shared CLI entry-point used by every analysis script.

    Handles argparse setup (--db-path, --library, -o, --human),
    invokes *analyze_fn*, and routes output through *format_fn* /
    ``output_json``.

    Args:
        description: One-line argparse description.
        analyze_fn:  ``fn(db_path, args) -> dict`` — the script's core work.
        format_fn:   ``fn(result) -> str`` — human-readable formatter.
        extra_args_fn: Optional callback to add script-specific argparse args.
        epilog:      Optional argparse epilog text (examples, etc.).

    Returns:
        An ExitCode.
    """
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    parser.add_argument("--db-path", help="Path to Photos.sqlite database")
    parser.add_argument("--library", help="Path to Photos library")
    parser.add_argument("-o", "--output", help="Output JSON file")
    parser.add_argument("--human", action="store_true", help="Output human-readable summary instead of JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose/debug logging")

    if extra_args_fn:
        extra_args_fn(parser)

    args = parser.parse_args()
    setup_logging(verbose=getattr(args, "verbose", False))
    db_path = args.db_path or args.library

    try:
        result = analyze_fn(db_path, args)

        if args.human:
            print(format_fn(result))
        else:
            output_json(result, args.output)
            if not args.output:
                print("\n" + format_fn(result), file=sys.stderr)

        return ExitCode.OK

    except KeyboardInterrupt:
        logger.error("Cancelled.")
        return ExitCode.USER_ABORTED
    except Exception as e:
        return handle_cli_error(e)


def exit_code_for(error: BaseException) -> ExitCode:
    """Map an exception to the documented exit code (see ExitCode)."""
    if isinstance(error, DatabaseNotFoundError):
        return ExitCode.DB_NOT_FOUND
    if isinstance(error, PermissionError):
        return ExitCode.PERMISSION_DENIED
    if isinstance(error, SchemaUnsupportedError):
        return ExitCode.SCHEMA_UNSUPPORTED
    if isinstance(error, KeyboardInterrupt):
        return ExitCode.USER_ABORTED
    if isinstance(error, ValueError):
        return ExitCode.USAGE
    return ExitCode.ERROR


def handle_cli_error(error: Exception) -> ExitCode:
    """Log *error* for a CLI user and return its exit code."""
    code = exit_code_for(error)
    if isinstance(error, sqlite3.DatabaseError):
        logger.error("Database error: %s", error)
    elif code == ExitCode.ERROR:
        logger.error("Unexpected error: %s", error)
    else:
        logger.error("%s", error)
    if code == ExitCode.ERROR and logger.isEnabledFor(logging.DEBUG):
        traceback.print_exc()
    return code
