#!/usr/bin/env python3
"""
Security regression tests (ROADMAP T0.8).

What the skill treats as untrusted: filenames, person names and album titles
from the Photos database (anyone who AirDrops you a file picks its name), plus
every CLI argument an agent passes in. These tests pin down the three places
that input meets an interpreter: AppleScript, the filesystem, and SQL.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from _common import build_asset_query, build_identifier_lists, escape_applescript, sanitize_folder_name, validate_year

HOSTILE_STRINGS = [
    'plain "quoted" name',
    '" & (do shell script "touch /tmp/pwned") & "',
    "ends with backslash \\",
    'backslash before quote \\"',
    '\\\\" & "',
    "line\nbreak",
    "carriage\rreturn",
    'tab\tand "quote"',
    "unicode 📸 Ünïcødé ﬁle — “smart quotes”",
    "right-to-left \u202egnp.exe",
    "nul-adjacent \x01\x02",
    "",
    '"',
    "\\",
    "¬",  # AppleScript's line-continuation character
]


def parse_applescript_string(source: str) -> tuple[str, int]:
    """Parse one AppleScript string literal starting at source[0]; return (value, end index).

    Mirrors AppleScript's rules: backslash escapes the next character, an
    unescaped double quote closes the literal, and raw newlines are allowed.
    """
    assert source[0] == '"'
    escapes = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
    value, i = [], 1
    while i < len(source):
        ch = source[i]
        if ch == "\\":
            value.append(escapes.get(source[i + 1], source[i + 1]))
            i += 2
        elif ch == '"':
            return "".join(value), i + 1
        else:
            value.append(ch)
            i += 1
    raise AssertionError(f"unterminated literal: {source!r}")


class TestAppleScriptEscaping:
    @pytest.mark.parametrize("raw", HOSTILE_STRINGS)
    def test_literal_cannot_be_closed_early(self, raw):
        literal = f'"{escape_applescript(raw)}"'
        value, end = parse_applescript_string(literal)
        assert end == len(literal), "string literal closed before its end: injection possible"
        assert value == raw

    @pytest.mark.parametrize("raw", HOSTILE_STRINGS)
    def test_identifier_lists_keep_one_item_per_asset(self, raw):
        items = [{"uuid": "AAAA", "filename": raw}, {"uuid": raw or "B", "filename": "second.jpg"}]
        id_list, name_list = build_identifier_lists(items)
        for literal_list, expected in [
            (id_list, ["AAAA/L0/001", (raw or "B") + "/L0/001"]),
            (name_list, [raw, "second.jpg"]),
        ]:
            values, rest = [], literal_list
            while rest:
                value, end = parse_applescript_string(rest)
                values.append(value)
                rest = rest[end:].removeprefix(", ")
            assert values == expected

    @pytest.mark.skipif(
        sys.platform != "darwin" or shutil.which("osascript") is None, reason="needs the real AppleScript runtime"
    )
    def test_round_trip_through_osascript(self):
        """The real interpreter returns every hostile string unchanged."""
        for raw in HOSTILE_STRINGS:
            if "\x01" in raw or "\r" in raw:
                continue  # osascript normalizes control chars and CR on output; covered by the parser test
            result = subprocess.run(
                ["osascript", "-e", f'return "{escape_applescript(raw)}"'],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, (raw, result.stderr)
            assert result.stdout.removesuffix("\n") == raw


class TestPathSafety:
    @pytest.mark.parametrize(
        "name",
        ["../../etc", "..", ".", "/absolute/path", "C:\\Windows", "a/../../b", ".hidden", "...", "a\x00b", ""],
    )
    def test_sanitized_folder_stays_a_single_safe_component(self, name):
        safe = sanitize_folder_name(name)
        assert safe
        assert "/" not in safe and "\\" not in safe
        assert ".." not in safe and not safe.startswith(".")
        assert os.path.basename(safe) == safe

    def test_export_folder_traversal_stays_inside(self, tmp_path):
        from smart_export import export_with_applescript

        out = tmp_path / "out"
        out.mkdir()
        items = [{"uuid": "ABC", "filename": "x.jpg"}]
        with patch("smart_export.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "EXPORTED:1 SKIPPED:0"
            export_with_applescript(items, str(out), "../../escape")
        created = [p for p in tmp_path.rglob("*") if p.is_dir()]
        assert all(p == out or out in p.parents for p in created)

    def test_export_refuses_symlink_to_sibling_with_shared_prefix(self, tmp_path):
        """'/out-evil' starts with '/out' but is not inside it."""
        from smart_export import export_with_applescript

        out = tmp_path / "out"
        out.mkdir()
        sibling = tmp_path / "out-evil"
        sibling.mkdir()
        (out / "trip").symlink_to(sibling)

        with patch("smart_export.subprocess.run") as mock_run, pytest.raises(ValueError, match="Path traversal"):
            export_with_applescript([{"uuid": "ABC", "filename": "x.jpg"}], str(out), "trip")
        mock_run.assert_not_called()

    def test_export_refuses_symlink_outside(self, tmp_path):
        from smart_export import export_with_applescript

        out = tmp_path / "out"
        out.mkdir()
        (out / "trip").symlink_to(tmp_path)

        with patch("smart_export.subprocess.run") as mock_run, pytest.raises(ValueError, match="Path traversal"):
            export_with_applescript([{"uuid": "ABC", "filename": "x.jpg"}], str(out), "trip")
        mock_run.assert_not_called()


SQL_PAYLOADS = [
    "'; DROP TABLE ZASSET; --",
    '" OR 1=1 --',
    "%' OR '1'='1",
    "Robert'); DELETE FROM ZPERSON; --",
]


def run_with(module: str, conn: sqlite3.Connection, fn, **kwargs):
    with patch(f"{module}.PhotosDB") as mock_db:
        mock_db.return_value.__enter__ = MagicMock(return_value=conn)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        return fn(db_path="test", **kwargs)


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("ZASSET", "ZPERSON")}


class TestSqlInjection:
    @pytest.mark.parametrize("year", ["2025 OR 1=1", "2025'", "20251", "abcd", "", "2025\n"])
    def test_validate_year_rejects_non_years(self, year):
        with pytest.raises(ValueError):
            validate_year(year)

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_scene_search_term_is_bound(self, full_db, payload):
        from scene_search import search_scenes

        before = table_counts(full_db)
        result = run_with("scene_search", full_db, search_scenes, search_term=payload)
        assert result["results"] == []
        assert table_counts(full_db) == before

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_export_person_and_album_are_bound(self, full_db, payload):
        from smart_export import generate_export_plan

        before = table_counts(full_db)
        for kwargs in ({"person_name": payload}, {"album_name": payload}):
            plan = run_with("smart_export", full_db, generate_export_plan, **kwargs)
            assert plan["summary"]["total_photos"] == 0
        assert table_counts(full_db) == before

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_face_quality_person_is_bound(self, full_db, payload):
        from face_quality import analyze_face_quality

        before = table_counts(full_db)
        run_with("face_quality", full_db, analyze_face_quality, person_name=payload)
        assert table_counts(full_db) == before

    def test_on_this_day_rejects_malformed_date(self, full_db):
        from on_this_day import on_this_day

        with pytest.raises(ValueError):
            run_with("on_this_day", full_db, on_this_day, target_date="2025-01-01' OR 1=1 --")

    def test_query_builder_limit_must_be_integer(self):
        with pytest.raises(ValueError):
            build_asset_query(limit="1; DROP TABLE ZASSET")  # type: ignore[arg-type]
        assert build_asset_query(limit=5).endswith("LIMIT 5")
