#!/usr/bin/env python3
"""
Docs-vs-CLI audit (ROADMAP T0.5).

Agents learn the CLI from SKILL.md, so a documented flag that a script doesn't
accept is a guaranteed failed command. Each script's real flags come from its
own `--help` (which exits before touching any database), so this needs no
refactoring of the scripts and stays true to what users actually run.
"""

import re
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
DOCS = ["SKILL.md", "README.md"]

SCRIPT_NAMES = sorted(p.stem for p in SCRIPTS_DIR.glob("[a-z]*.py"))
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
SCRIPT_REF = re.compile(r"\b(" + "|".join(SCRIPT_NAMES) + r")\.py\b")


@cache
def cli_flags(script: str) -> frozenset[str]:
    """Long options from the script's --help, excluding its examples epilog."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / f"{script}.py"), "--help"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    options = re.split(r"\n(?:examples|Examples):", result.stdout)[0]
    return frozenset(FLAG.findall(options))


def logical_lines(text: str):
    """Yield (line_number, line), joining shell `\\` continuations."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        start, line = i + 1, lines[i]
        while line.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            line = line.rstrip()[:-1] + " " + lines[i]
        yield start, line
        i += 1


def documented_script_flags(doc: str) -> list[tuple[int, str, str]]:
    """(line, script, flag) for each flag that follows a `<script>.py` mention on the same line."""
    found = []
    for lineno, line in logical_lines((REPO_ROOT / doc).read_text(encoding="utf-8")):
        refs = list(SCRIPT_REF.finditer(line))
        for k, ref in enumerate(refs):
            segment_end = refs[k + 1].start() if k + 1 < len(refs) else len(line)
            found.extend((lineno, ref[1], flag) for flag in FLAG.findall(line[ref.end() : segment_end]))
    return found


def test_every_script_has_help():
    assert SCRIPT_NAMES, "no scripts found"
    for script in SCRIPT_NAMES:
        assert "--help" in cli_flags(script), script


@pytest.mark.parametrize("doc", DOCS)
def test_documented_flags_exist_on_their_script(doc):
    missing = [
        f"{doc}:{lineno}: {script}.py {flag}"
        for lineno, script, flag in documented_script_flags(doc)
        if flag not in cli_flags(script)
    ]
    assert not missing, "Documented flags the script doesn't accept:\n" + "\n".join(missing)


@pytest.mark.parametrize("doc", DOCS)
def test_every_mentioned_flag_exists_somewhere(doc):
    """Catches flags in prose and tables that don't name a script on the same line."""
    known = frozenset().union(*(cli_flags(s) for s in SCRIPT_NAMES))
    unknown = [
        f"{doc}:{lineno}: {flag}"
        for lineno, line in logical_lines((REPO_ROOT / doc).read_text(encoding="utf-8"))
        for flag in FLAG.findall(line)
        if flag not in known
    ]
    assert not unknown, "Flags no script defines:\n" + "\n".join(unknown)


def test_extractor_finds_documented_usage():
    """Guard the guard: if parsing silently finds nothing, the tests above pass vacuously."""
    flags = documented_script_flags("SKILL.md")
    assert len(flags) > 40
    assert ("cleanup_executor", "--execute") in {(s, f) for _, s, f in flags}
