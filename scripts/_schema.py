#!/usr/bin/env python3
"""
Schema registry for the Photos database (ROADMAP T1.1).

Apple renames and adds Core Data columns between macOS releases. This module is
the only place that inspects the schema: it reads the table list once, reads a
table's columns the first time something asks, and maps *logical* names such as
``face.person_fk`` to whichever physical column this library actually has.

When Apple renames a column, add the new name to the front of its candidate
tuple in LOGICAL_COLUMNS. Code that builds SQL with ``schema.col(...)`` follows
automatically.

Use ``PRAGMA table_info(...)`` here, never the ``pragma_table_info()``
table-valued function: older SQLite trips the read-only authorizer on it.
"""

import sqlite3


class SchemaUnsupportedError(RuntimeError):
    """The Photos database lacks something this command cannot run without."""


# logical name -> (table, physical column candidates in preference order)
LOGICAL_COLUMNS: dict[str, tuple[str, tuple[str, ...]]] = {
    # ZASSET
    "asset.uuid": ("ZASSET", ("ZUUID",)),
    "asset.kind_subtype": ("ZASSET", ("ZKINDSUBTYPE",)),
    "asset.playback_style": ("ZASSET", ("ZPLAYBACKSTYLE",)),
    "asset.library_scope": ("ZASSET", ("ZLIBRARYSCOPE",)),
    "asset.shared_library_scope_id": ("ZASSET", ("ZSHAREDLIBRARYSCOPEIDENTIFIER",)),
    "asset.library_scope_participation": ("ZASSET", ("ZACTIVELIBRARYSCOPEPARTICIPATIONSTATE",)),
    "asset.cloud_local_state": ("ZASSET", ("ZCLOUDLOCALSTATE",)),
    "asset.cloud_is_my_asset": ("ZASSET", ("ZCLOUDISMYASSET",)),
    "asset.cloud_batch_publish_date": ("ZASSET", ("ZCLOUDBATCHPUBLISHDATE",)),
    "asset.cloud_is_downloadable": ("ZASSET", ("ZCLOUDISDOWNLOADABLE",)),
    "asset.visibility_state": ("ZASSET", ("ZVISIBILITYSTATE",)),
    # ZADDITIONALASSETATTRIBUTES
    "asset_attrs.tz_offset": ("ZADDITIONALASSETATTRIBUTES", ("ZTIMEZONEOFFSET",)),
    # ZCOMPUTEDASSETATTRIBUTES
    "computed.composition": ("ZCOMPUTEDASSETATTRIBUTES", ("ZPLEASANTCOMPOSITIONSCORE",)),
    # ZDETECTEDFACE (macOS 15 Sequoia renamed the foreign keys)
    "face.person_fk": ("ZDETECTEDFACE", ("ZPERSONFORFACE", "ZPERSON")),
    "face.asset_fk": ("ZDETECTEDFACE", ("ZASSETFORFACE", "ZASSET")),
    "face.quality": ("ZDETECTEDFACE", ("ZQUALITYMEASURE",)),
    "face.blur": ("ZDETECTEDFACE", ("ZBLURSCORE",)),
    "face.smile": ("ZDETECTEDFACE", ("ZSMILESCORE",)),
}


class SchemaRegistry:
    """What this Photos database contains, introspected once per connection."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
        self._tables: tuple[str, ...] = tuple(row[0] for row in rows)
        self._columns: dict[str, frozenset[str]] = {}

    def tables(self) -> tuple[str, ...]:
        """All table names, sorted."""
        return self._tables

    def has_table(self, table: str) -> bool:
        return table in self._tables

    def columns(self, table: str) -> frozenset[str]:
        """Column names of *table*; empty if the table doesn't exist."""
        if table not in self._columns:
            if not self.has_table(table):
                return frozenset()
            quoted = '"' + table.replace('"', '""') + '"'
            rows = self._conn.execute(f"PRAGMA table_info({quoted})").fetchall()
            self._columns[table] = frozenset(row[1] for row in rows)
        return self._columns[table]

    def has_column(self, table: str, column: str) -> bool:
        return column in self.columns(table)

    def col(self, logical: str) -> str | None:
        """The physical column for a logical name, or None if this library has none of its candidates."""
        table, candidates = LOGICAL_COLUMNS[logical]
        present = self.columns(table)
        return next((name for name in candidates if name in present), None)

    def has(self, logical: str) -> bool:
        return self.col(logical) is not None

    def require(self, *logical: str, operation: str) -> None:
        """Raise SchemaUnsupportedError naming every missing logical column."""
        missing = [name for name in logical if not self.has(name)]
        if missing:
            physical = ", ".join(f"{LOGICAL_COLUMNS[name][0]}.{'/'.join(LOGICAL_COLUMNS[name][1])}" for name in missing)
            raise SchemaUnsupportedError(
                f"{physical} not found in this Photos database. {operation} cannot run without it. "
                "Please open an issue with your macOS version."
            )


class PhotosConnection(sqlite3.Connection):
    """Connection that caches its SchemaRegistry (plain connections can't hold attributes or weakrefs)."""

    schema_registry: SchemaRegistry | None = None


def get_schema(conn_or_cursor: sqlite3.Connection | sqlite3.Cursor) -> SchemaRegistry:
    """The SchemaRegistry for a connection (or a cursor's connection), cached when possible."""
    conn = conn_or_cursor.connection if isinstance(conn_or_cursor, sqlite3.Cursor) else conn_or_cursor
    if not isinstance(conn, PhotosConnection):
        return SchemaRegistry(conn)
    if conn.schema_registry is None:
        conn.schema_registry = SchemaRegistry(conn)
    return conn.schema_registry
