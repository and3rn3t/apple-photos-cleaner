#!/usr/bin/env python3
"""
Where scene labels ("Beach", "Dog") come from (issue #35).

Older libraries store a name and an asset key on every ZSCENECLASSIFICATION
row. macOS 26 doesn't: rows carry only a numeric ZSCENEIDENTIFIER, and the
human-readable labels live in Photos' search index, `database/search/psi.sqlite`:

- ``groups``: category 1500 holds Apple's scene vocabulary; category 1501 holds
  synonyms whose ``owning_groupid`` points at a 1500 label. Labels end in NUL.
- ``ga(groupid, assetid)`` links a label group to an indexed asset.
- ``assets(uuid_0, uuid_1)``: the asset's ZUUID as two little-endian signed
  64-bit halves.

The index has no per-photo confidence. It is optional: when neither source
exists, scene features report ``degraded`` instead of failing. Verified against
a real macOS 26.7.2 library (model 19607).
"""

import os
import sqlite3
import uuid
from collections import Counter
from collections.abc import Iterable

from _schema import SCENES, get_schema

LABEL_CATEGORY = 1500
SYNONYM_CATEGORY = 1501
DATABASE = "database"
SEARCH_INDEX = "search_index"
# SQLite's default limit on bound parameters is 999 in older builds.
_CHUNK = 900


def search_index_path(db_path: str) -> str:
    """psi.sqlite sits in the library's database/search/ folder, next to Photos.sqlite."""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "search", "psi.sqlite")


def search_index_available(db_path: str | None) -> bool:
    """Whether a readable search index with the expected tables exists next to *db_path*."""
    if not db_path or not os.path.isfile(search_index_path(db_path)):
        return False
    try:
        with SearchIndex(db_path) as index:
            return index.valid
    except (OSError, sqlite3.DatabaseError):
        return False


def uuid_to_halves(asset_uuid: str) -> tuple[int, int]:
    raw = uuid.UUID(asset_uuid).bytes
    return int.from_bytes(raw[:8], "little", signed=True), int.from_bytes(raw[8:], "little", signed=True)


def halves_to_uuid(uuid_0: int, uuid_1: int) -> str:
    raw = uuid_0.to_bytes(8, "little", signed=True) + uuid_1.to_bytes(8, "little", signed=True)
    return str(uuid.UUID(bytes=raw)).upper()


def clean_label(label: str | None) -> str:
    return (label or "").rstrip("\x00").strip()


def _chunks(items: list, size: int = _CHUNK) -> Iterable[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class SearchIndex:
    """Read-only access to psi.sqlite's scene labels, through the same guarded connection as Photos.sqlite."""

    def __init__(self, db_path: str):
        from _common import connect_db  # local: _common imports this module's siblings at import time

        self.conn = connect_db(search_index_path(db_path))
        self.conn.row_factory = None
        # The registry never connects to the index's FTS5 table (its tokenizer is Apple-private).
        schema = get_schema(self.conn)
        self.valid = all(schema.has_table(table) for table in ("groups", "ga", "assets"))

    def __enter__(self) -> "SearchIndex":
        return self

    def __exit__(self, *exc: object) -> None:
        self.conn.close()

    def _matching_labels(self, term: str) -> dict[int, str]:
        """Label groups (category 1500) whose label or one of whose synonyms contains *term*."""
        pattern = f"%{term.lower()}%"
        rows = self.conn.execute(
            """
            SELECT g.rowid, g.content_string FROM groups g
            WHERE g.category = ? AND lower(g.content_string) LIKE ?
            UNION
            SELECT owner.rowid, owner.content_string FROM groups s
            JOIN groups owner ON owner.rowid = s.owning_groupid AND owner.category = ?
            WHERE s.category = ? AND lower(s.content_string) LIKE ?
            """,
            (LABEL_CATEGORY, pattern, LABEL_CATEGORY, SYNONYM_CATEGORY, pattern),
        ).fetchall()
        return {rowid: clean_label(label) for rowid, label in rows}

    def _labels_with_uuids(self, group_ids: list[int] | None) -> dict[str, set[str]]:
        """label -> asset UUIDs, for the given label groups (or every label group)."""
        where = "g.category = ?"
        params: list = [LABEL_CATEGORY]
        if group_ids is not None:
            if not group_ids:
                return {}
            where += f" AND g.rowid IN ({','.join('?' * len(group_ids))})"
            params += group_ids
        labels: dict[str, set[str]] = {}
        for label, uuid_0, uuid_1 in self.conn.execute(
            f"""
            SELECT g.content_string, a.uuid_0, a.uuid_1
            FROM groups g JOIN ga ON ga.groupid = g.rowid JOIN assets a ON a.rowid = ga.assetid
            WHERE {where}
            """,
            params,
        ):
            labels.setdefault(clean_label(label), set()).add(halves_to_uuid(uuid_0, uuid_1))
        return labels

    def search(self, term: str) -> dict[str, set[str]]:
        """label -> asset UUIDs for every label matching *term* (synonyms included)."""
        return self._labels_with_uuids(list(self._matching_labels(term)))

    def inventory(self) -> dict[str, set[str]]:
        return self._labels_with_uuids(None)

    def labels_for(self, uuids: Iterable[str]) -> Counter[str]:
        """How many of *uuids* carry each label."""
        counts: Counter[str] = Counter()
        halves = [uuid_to_halves(u) for u in uuids]
        for chunk in _chunks(halves, _CHUNK // 2):
            clause = " OR ".join("(a.uuid_0 = ? AND a.uuid_1 = ?)" for _ in chunk)
            params = [part for pair in chunk for part in pair]
            for (label,) in self.conn.execute(
                f"""
                SELECT g.content_string FROM assets a
                JOIN ga ON ga.assetid = a.rowid JOIN groups g ON g.rowid = ga.groupid
                WHERE g.category = ? AND ({clause})
                """,
                [LABEL_CATEGORY, *params],
            ):
                counts[clean_label(label)] += 1
        return counts


def scene_source(conn: sqlite3.Connection) -> str | None:
    """DATABASE when ZSCENECLASSIFICATION names its scenes, SEARCH_INDEX when psi.sqlite can, else None."""
    if all(get_schema(conn).has(name) for name in SCENES):
        return DATABASE
    if search_index_available(getattr(conn, "db_file", None)):
        return SEARCH_INDEX
    return None


def uuids_for(conn: sqlite3.Connection, asset_ids: list[int]) -> dict[int, str]:
    """ZASSET.Z_PK -> ZUUID for *asset_ids*."""
    found: dict[int, str] = {}
    for chunk in _chunks(asset_ids):
        rows = conn.execute(
            f"SELECT Z_PK, ZUUID FROM ZASSET WHERE Z_PK IN ({','.join('?' * len(chunk))})", chunk
        ).fetchall()
        found.update({row[0]: row[1].upper() for row in rows if row[1]})
    return found


def top_labels_for_assets(conn: sqlite3.Connection, asset_ids: list[int], limit: int = 5) -> list[dict]:
    """[{scene, count}] for photos *asset_ids*, from the search index (macOS 26 path)."""
    if not asset_ids:
        return []
    with SearchIndex(conn.db_file) as index:  # type: ignore[attr-defined]
        counts = index.labels_for(uuids_for(conn, asset_ids).values())
    return [{"scene": label, "count": n} for label, n in counts.most_common(limit) if label]
