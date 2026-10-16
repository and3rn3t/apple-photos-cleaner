#!/usr/bin/env python3
"""Every command shares the same core flags, with the same meaning (ROADMAP T1.8)."""

import argparse
import importlib
import json
import sqlite3
import subprocess
import sys
from functools import cache
from pathlib import Path
from unittest.mock import patch

import pytest
from test_new_scripts import create_full_test_db

ROOT = Path(__file__).resolve().parent.parent
COMMANDS = sorted(p.stem for p in (ROOT / "scripts").glob("[a-z]*.py"))
# Commands whose primary audience is a person at a terminal default to human output.
HUMAN_BY_DEFAULT = {"doctor", "smart_export"}


class _ParserCapturedError(Exception):
    def __init__(self, parser: argparse.ArgumentParser):
        self.parser = parser


@cache
def parser_for(command: str) -> argparse.ArgumentParser:
    def capture(parser, *args, **kwargs):
        raise _ParserCapturedError(parser)

    with patch.object(argparse.ArgumentParser, "parse_args", capture), pytest.raises(_ParserCapturedError) as caught:
        importlib.import_module(command).main()
    return caught.value.parser


def action(parser: argparse.ArgumentParser, option: str) -> argparse.Action:
    return next(a for a in parser._actions if option in a.option_strings)


@pytest.mark.parametrize("command", COMMANDS)
def test_shared_flags(command):
    parser = parser_for(command)
    options = {o for a in parser._actions for o in a.option_strings}
    expected = {"--db-path", "--library", "-o", "--output", "--format", "--human", "-q", "--quiet", "-v", "--verbose"}
    assert expected <= options, f"{command} lacks {sorted(expected - options)}"

    fmt = action(parser, "--format")
    assert list(fmt.choices) == ["json", "human"]
    assert fmt.default == ("human" if command in HUMAN_BY_DEFAULT else "json")
    # --human is shorthand for --format human, stored in the same place
    human = action(parser, "--human")
    assert (human.dest, human.const) == ("format", "human")


def cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=ROOT, timeout=60)


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("lib") / "Photos.sqlite"
    target = sqlite3.connect(path)
    create_full_test_db().backup(target)
    target.close()
    return str(path)


@pytest.mark.parametrize(
    ("script", "alias"),
    [("library_analysis", "--human"), ("cleanup_executor", "--human"), ("timeline_recap", "--narrative")],
)
def test_format_human_equals_its_alias(db, script, alias):
    extra = ["--category", "all_screenshots"] if script == "cleanup_executor" else []
    run = [str(ROOT / "scripts" / f"{script}.py"), "--db-path", db, *extra]
    via_format = cli(*run, "--format", "human")
    via_alias = cli(*run, alias)
    assert via_format.returncode == via_alias.returncode == 0
    assert via_format.stdout == via_alias.stdout
    with pytest.raises(json.JSONDecodeError):
        json.loads(via_format.stdout)  # human text, not JSON


@pytest.mark.parametrize("script", ["library_analysis", "cleanup_executor", "timeline_recap"])
def test_quiet_leaves_only_the_result(db, script):
    extra = ["--category", "all_screenshots"] if script == "cleanup_executor" else []
    run = [str(ROOT / "scripts" / f"{script}.py"), "--db-path", db, *extra]
    loud, quiet = cli(*run), cli(*run, "--quiet")
    assert loud.stderr.strip(), "without --quiet a human summary goes to stderr"
    assert quiet.stderr == ""
    assert json.loads(quiet.stdout) == json.loads(loud.stdout)


def test_quiet_still_reports_errors(tmp_path):
    result = cli(str(ROOT / "scripts" / "library_analysis.py"), "--db-path", str(tmp_path / "missing.sqlite"), "-q")
    assert result.returncode == 3
    assert "not found" in result.stderr


def test_smart_export_output_file(db, tmp_path):
    out = tmp_path / "plan.json"
    result = cli(
        str(ROOT / "scripts" / "smart_export.py"),
        "--db-path", db, "--output-dir", str(tmp_path / "export"),
        "--plan-only", "--format", "json", "-o", str(out),
    )  # fmt: skip
    assert result.returncode == 0
    assert result.stdout == ""
    assert "confirm_token" in json.loads(out.read_text())
