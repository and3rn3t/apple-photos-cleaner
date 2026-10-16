#!/usr/bin/env python3
"""Markdown and CSV output for every command (ROADMAP T2.23)."""

import csv
import io
import json
from typing import ClassVar

import pytest
from test_degradation import SCRIPTS, db_without, run

from _common import render_csv, render_markdown


def tables(value, path=""):
    """Every list of objects in a JSON result, with its dotted path (what CSV should contain)."""
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from tables(item, f"{path}.{key}" if path else key)


class TestRenderers:
    DATA: ClassVar[dict] = {
        "summary": {"count": 2, "size": "1 KB"},
        "items": [{"name": "a|b", "tags": ["x", "y"]}, {"name": "c\nd", "extra": None}],
        "nested": {"deeper": {"rows": [{"k": 1}]}},
        "empty": [],
        "words": ["one", "two"],
        "flag": True,
    }

    def test_markdown(self):
        md = render_markdown(self.DATA, "demo")
        assert md.startswith("# demo\n")
        assert "- **flag**: True" in md
        assert "## summary" in md and "- **count**: 2" in md
        assert "| name | tags | extra |" in md
        assert "| a\\|b |" in md  # pipes escaped
        assert "| c d |" in md  # newlines can't break a table row
        assert '["x","y"]' in md  # nested values as compact JSON
        assert "#### rows" in md  # heading depth follows nesting
        assert "- **empty**: (none)" in md
        assert "- **words**: one, two" in md

    def test_csv(self):
        rows = list(csv.DictReader(io.StringIO(render_csv(self.DATA))))
        assert [r["section"] for r in rows] == ["items", "items", "nested.deeper.rows"]
        assert rows[0]["name"] == "a|b" and json.loads(rows[0]["tags"]) == ["x", "y"]
        assert rows[1]["extra"] == ""
        assert rows[2]["k"] == "1"

    def test_csv_with_no_rows_still_has_a_header(self):
        assert render_csv({"summary": {"count": 0}}) == "section\n"


@pytest.mark.parametrize("script", SCRIPTS)
def test_every_command_supports_md_and_csv(script, tmp_path):
    db = db_without(tmp_path, None, None)
    code, out = run(script, db, tmp_path)  # JSON (doctor / smart_export pass --format json in the sweep)
    assert code == 0
    result = json.loads(out)

    code, md = run(script, db, tmp_path, extra=["--format", "md"])
    assert code == 0
    assert md.startswith("# ")

    code, text = run(script, db, tmp_path, extra=["--format", "csv"])
    assert code == 0
    rows = list(csv.DictReader(io.StringIO(text)))
    expected = sum(len(table) for _, table in tables(result))
    assert len(rows) == expected, f"{script}: {len(rows)} CSV rows for {expected} result rows"
    assert {r["section"] for r in rows} == {path for path, _ in tables(result)}


def test_output_file(tmp_path):
    db = db_without(tmp_path, None, None)
    out = tmp_path / "report.md"
    code, stdout = run("library_analysis", db, tmp_path, extra=["--format", "md", "-o", str(out)])
    assert code == 0
    assert stdout == ""
    assert out.read_text().startswith("# ")
