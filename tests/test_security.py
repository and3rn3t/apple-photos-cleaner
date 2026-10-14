#!/usr/bin/env python3
"""
Security regression tests (ROADMAP T0.8).

What the skill treats as untrusted: filenames, person names and album titles
from the Photos database (anyone who AirDrops you a file picks its name), plus
every CLI argument an agent passes in. These tests pin down the three places
that input meets an interpreter: AppleScript, the filesystem, and SQL.
"""

import io
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from _common import (
    DatabaseNotFoundError,
    ExitCode,
    SchemaUnsupportedError,
    _deny_writes,
    build_asset_query,
    build_identifier_lists,
    connect_db,
    escape_applescript,
    exit_code_for,
    plan_token,
    sanitize_folder_name,
    validate_year,
)

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


# ── Read-only guard (T1.20) and exit codes (T1.9) ────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAMES = sorted(p.stem for p in (REPO_ROOT / "scripts").glob("[a-z]*.py"))
# Arguments that keep each script on its read-only path.
SCRIPT_ARGS = {
    "cleanup_executor": ["--category", "all_screenshots"],
    "smart_export": ["--output-dir", "{tmp}", "--plan-only"],
}
# Scripts that still crash when an optional column is absent. T1.4 empties this.
NOT_YET_DEGRADING = {"seasonal_highlights": "hardcodes optional ZCOMPUTEDASSETATTRIBUTES scores"}


def run_cli(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / f"{script}.py"), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )


@pytest.fixture
def db_file(full_db, tmp_path) -> Path:
    """full_db written to disk, so scripts open it through connect_db."""
    path = tmp_path / "Photos.sqlite"
    target = sqlite3.connect(path)
    full_db.backup(target)
    target.close()
    return path


class TestReadOnlyGuard:
    WRITES = (
        "INSERT INTO ZASSET (Z_PK) VALUES (999)",
        "UPDATE ZASSET SET ZFAVORITE = 1",
        "DELETE FROM ZASSET",
        "CREATE TABLE evil (x)",
        "CREATE TEMP TABLE evil (x)",
        "DROP TABLE ZASSET",
        "ALTER TABLE ZASSET ADD COLUMN evil",
        "ATTACH DATABASE ':memory:' AS evil",
        "PRAGMA journal_mode = DELETE",
        "PRAGMA writable_schema = ON",
        "BEGIN IMMEDIATE",
    )

    @pytest.mark.parametrize("sql", WRITES)
    def test_writes_are_denied(self, db_file, sql):
        conn = connect_db(str(db_file))
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            conn.execute(sql)
        conn.close()

    @pytest.mark.parametrize("sql", WRITES[:4])
    def test_authorizer_denies_even_without_read_only_mode(self, db_file, sql):
        """The guard must hold on its own if a future change drops mode=ro."""
        conn = sqlite3.connect(db_file)
        conn.set_authorizer(_deny_writes)
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            conn.execute(sql)
        conn.close()

    def test_reads_are_allowed(self, db_file):
        # Use PRAGMA table_info(...), never the pragma_table_info() table-valued
        # function: SQLite < ~3.45 (e.g. 3.40 in python.org's 3.10) authorizes
        # internal sqlite_master UPDATEs when building that virtual table, which
        # the guard rightly denies.
        conn = connect_db(str(db_file))
        assert conn.execute("SELECT count(*) FROM ZASSET").fetchone()[0] > 0
        assert conn.execute("PRAGMA table_info(ZASSET)").fetchall()
        assert conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        recursive = "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r WHERE x < 3) SELECT max(x) FROM r"
        assert conn.execute(recursive).fetchone()[0] == 3
        conn.close()

    @pytest.mark.parametrize(
        "script",
        [
            pytest.param(name, marks=pytest.mark.xfail(strict=True, reason=f"T1.4: {NOT_YET_DEGRADING[name]}"))
            if name in NOT_YET_DEGRADING
            else name
            for name in SCRIPT_NAMES
        ],
    )
    def test_every_script_runs_under_the_guard(self, script, db_file, tmp_path):
        """Unit tests stub PhotosDB; this drives each real CLI through connect_db."""
        args = [a.replace("{tmp}", str(tmp_path / "export")) for a in SCRIPT_ARGS.get(script, [])]
        result = run_cli(script, "--db-path", str(db_file), *args)
        assert "not authorized" not in result.stderr
        assert result.returncode == ExitCode.OK, result.stderr


class TestExitCodes:
    @pytest.mark.parametrize("script", SCRIPT_NAMES)
    def test_missing_database(self, script, tmp_path):
        args = [a.replace("{tmp}", str(tmp_path)) for a in SCRIPT_ARGS.get(script, [])]
        result = run_cli(script, "--db-path", str(tmp_path / "missing.sqlite"), *args)
        assert result.returncode == ExitCode.DB_NOT_FOUND, result.stderr

    @pytest.mark.parametrize("script", ["library_analysis", "cleanup_executor", "timeline_recap"])
    def test_unknown_flag_is_usage_error(self, script):
        assert run_cli(script, "--no-such-flag").returncode == ExitCode.USAGE

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
    def test_unreadable_database(self, db_file):
        db_file.chmod(0)
        try:
            result = run_cli("library_analysis", "--db-path", str(db_file))
        finally:
            db_file.chmod(0o600)
        assert result.returncode == ExitCode.PERMISSION_DENIED
        assert "Full Disk Access" in result.stderr

    def test_invalid_argument_value_is_usage_error(self, db_file):
        result = run_cli("on_this_day", "--db-path", str(db_file), "--date", "not-a-date")
        assert result.returncode == ExitCode.USAGE, result.stderr

    @pytest.mark.parametrize(
        ("error", "code"),
        [
            (DatabaseNotFoundError("x"), ExitCode.DB_NOT_FOUND),
            (FileNotFoundError("output dir"), ExitCode.ERROR),
            (PermissionError("x"), ExitCode.PERMISSION_DENIED),
            (SchemaUnsupportedError("x"), ExitCode.SCHEMA_UNSUPPORTED),
            (KeyboardInterrupt(), ExitCode.USER_ABORTED),
            (ValueError("x"), ExitCode.USAGE),
            (sqlite3.OperationalError("locked"), ExitCode.ERROR),
            (RuntimeError("x"), ExitCode.ERROR),
        ],
    )
    def test_exception_mapping(self, error, code):
        assert exit_code_for(error) == code


# ── Confirmation tokens for mutations (T1.19) ────────────────────────────────


class TestPlanToken:
    def test_order_of_uuids_does_not_matter(self):
        assert plan_token("c", {"a": 1}, ["u1", "u2"]) == plan_token("c", {"a": 1}, ["u2", "u1"])

    @pytest.mark.parametrize(
        "changed",
        [
            ("c", {"a": 1}, ["u1", "u2", "u3"]),  # one more asset
            ("c", {"a": 1}, ["u1"]),  # one fewer asset
            ("c", {"a": 2}, ["u1", "u2"]),  # different parameters
            ("other", {"a": 1}, ["u1", "u2"]),  # different command
        ],
    )
    def test_any_change_produces_a_new_token(self, changed):
        assert plan_token(*changed) != plan_token("c", {"a": 1}, ["u1", "u2"])


def run_main(module, argv: list[str], capsys) -> tuple[int, str]:
    with patch.object(sys, "argv", [module.__name__, *argv]):
        code = module.main()
    return code, capsys.readouterr().out


class TestCleanupConfirmation:
    @pytest.fixture
    def cli(self, db_file):
        import cleanup_executor

        return cleanup_executor, ["--db-path", str(db_file), "--category", "all_screenshots"]

    def preview_token(self, cli, capsys) -> str:
        module, argv = cli
        code, out = run_main(module, argv, capsys)
        assert code == ExitCode.OK
        return json.loads(out)["confirm_token"]

    @pytest.mark.parametrize("confirm", [None, "0000000000000000"])
    def test_execute_without_matching_token_does_nothing(self, cli, capsys, confirm):
        module, argv = cli
        extra = ["--execute"] + (["--confirm", confirm] if confirm else [])
        with patch("cleanup_executor.subprocess.run") as osascript:
            code, out = run_main(module, argv + extra, capsys)
        assert code == ExitCode.CONFIRMATION_REQUIRED
        osascript.assert_not_called()
        assert json.loads(out)["confirm_token"], "the refusal must re-show the preview and its token"

    def test_execute_with_preview_token_runs(self, cli, capsys):
        module, argv = cli
        token = self.preview_token(cli, capsys)
        with patch("cleanup_executor.subprocess.run") as osascript:
            osascript.return_value = MagicMock(returncode=0, stdout="DELETED:1 SKIPPED:0", stderr="")
            code, out = run_main(module, [*argv, "--execute", "--confirm", token], capsys)
        assert code == ExitCode.OK
        osascript.assert_called_once()
        assert json.loads(out)["success_count"] == 1

    def test_token_is_stale_once_parameters_change(self, cli, capsys):
        module, argv = cli
        token = self.preview_token(cli, capsys)
        with patch("cleanup_executor.subprocess.run") as osascript:
            code, _ = run_main(module, [*argv, "--limit", "1", "--execute", "--confirm", token], capsys)
        assert code == ExitCode.CONFIRMATION_REQUIRED
        osascript.assert_not_called()

    def test_piped_yes_is_not_a_confirmation(self, cli, capsys, monkeypatch):
        module, argv = cli
        monkeypatch.setattr("sys.stdin", io.StringIO("yes\n"))
        with patch("cleanup_executor.subprocess.run") as osascript:
            code, _ = run_main(module, [*argv, "--execute"], capsys)
        assert code == ExitCode.CONFIRMATION_REQUIRED
        osascript.assert_not_called()

    def test_next_command_round_trips(self, cli, capsys):
        module, argv = cli
        code, out = run_main(module, argv, capsys)
        next_argv = shlex.split(json.loads(out)["next_command"])[1:]
        with patch("cleanup_executor.subprocess.run") as osascript:
            osascript.return_value = MagicMock(returncode=0, stdout="DELETED:1 SKIPPED:0", stderr="")
            code, _ = run_main(module, next_argv, capsys)
        assert code == ExitCode.OK
        osascript.assert_called_once()


class TestExportConfirmation:
    @pytest.fixture
    def cli(self, db_file, tmp_path):
        import smart_export

        argv = ["--db-path", str(db_file), "--output-dir", str(tmp_path / "out"), "--favorites", "--format", "json"]
        return smart_export, argv

    def test_export_without_token_writes_nothing(self, cli, capsys, tmp_path):
        module, argv = cli
        with patch("smart_export.subprocess.run") as osascript:
            code, out = run_main(module, argv, capsys)
        assert code == ExitCode.CONFIRMATION_REQUIRED
        osascript.assert_not_called()
        assert not (tmp_path / "out").exists()
        assert json.loads(out)["confirm_token"]

    def test_export_with_plan_token_runs(self, cli, capsys):
        module, argv = cli
        _, out = run_main(module, [*argv, "--plan-only"], capsys)
        token = json.loads(out)["confirm_token"]
        with patch("smart_export.subprocess.run") as osascript:
            osascript.return_value = MagicMock(returncode=0, stdout="EXPORTED:1 SKIPPED:0", stderr="")
            code, out = run_main(module, [*argv, "--confirm", token], capsys)
        assert code == ExitCode.OK
        osascript.assert_called_once()
        assert json.loads(out)["exported"] == 1

    def test_token_is_bound_to_output_dir(self, cli, capsys, tmp_path):
        module, argv = cli
        _, out = run_main(module, [*argv, "--plan-only"], capsys)
        token = json.loads(out)["confirm_token"]
        elsewhere = [*argv[:3], str(tmp_path / "elsewhere"), *argv[4:]]
        with patch("smart_export.subprocess.run") as osascript:
            code, _ = run_main(module, [*elsewhere, "--confirm", token], capsys)
        assert code == ExitCode.CONFIRMATION_REQUIRED
        osascript.assert_not_called()

    def test_removed_yes_flag_is_rejected(self, cli, capsys):
        module, argv = cli
        with pytest.raises(SystemExit) as exc:
            run_main(module, [*argv, "--yes"], capsys)
        assert exc.value.code == ExitCode.USAGE
