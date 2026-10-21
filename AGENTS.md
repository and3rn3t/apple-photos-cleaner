# Project Guidelines (AGENTS.md)

<!--
  Single source of truth for AI assistant instructions in this repo.
  CLAUDE.md is a thin pointer to this file — edit HERE.
-->

## Project Overview

**apple-photos-cleaner** analyzes, audits and cleans up an Apple Photos library by reading
its `Photos.sqlite` database directly. It is primarily a Claude/OpenClaw skill (`SKILL.md`),
published to ClawHub as `@and3rn3t/apple-photos-cleaner`, and also installs as a
`photos-cleaner` CLI via `pipx install .`. macOS only; Python 3.10+, **stdlib only** at runtime.

Agents depend on the CLI flags, JSON output shape and exit codes — treat them as a public API.

## Layout

```
SKILL.md                  # skill manifest + command table (frontmatter `version:` is the source of truth)
photos_cleaner.py         # dispatcher: `python3 photos_cleaner.py <command>` / `photos-cleaner <command>`
scripts/
  _bootstrap.py           # Python-version guard; import before any other project module (keep 3.9-parseable)
  _common.py              # shared DB access, arg parsing, output formats, ExitCode, SCHEMA_VERSION
  _schema.py              # schema registry: logical column names → physical Core Data columns
  _scenes.py              # scene-classification helpers
  schema-fingerprints.json
  <command>.py            # one file per command (library_analysis, junk_finder, cleanup_executor, …)
references/
  commands/<command>.md   # per-command flags, output and examples (SKILL.md links here)
  workflows.md, database-schema.md
tests/                    # pytest; conftest.py builds synthetic Photos databases, pins TZ to UTC
docs/threat-model.md
```

Installed, `scripts/` becomes the private package `photos_cleaner_commands` (see
`[tool.setuptools]` in `pyproject.toml`); the dispatcher puts it on `sys.path` itself.

## Build & Test

The Makefile runs everything inside `./.venv` (Homebrew/system Pythons are PEP 668
"externally managed"):

```bash
make install      # create .venv, pip install -e ".[dev]"
make test         # pytest tests/ -v
make coverage     # + coverage report (fail_under = 92 in pyproject.toml — a ratchet, raise it, never lower it)
make lint         # ruff check .
make format       # ruff format .
make typecheck    # mypy (files configured in pyproject.toml)
make check        # lint + format --check + tests
```

CI (`ci.yml`) runs: `ruff check .`, `pytest --cov=scripts`, `ruff format --check .`, `mypy`.
Equivalent one-liner inside an activated venv:

```bash
ruff check . && ruff format --check . && mypy && pytest --cov=scripts
```

Pre-commit: ruff check/format plus a conventional-commit `commit-msg` hook.

## Safety Model (do not weaken)

- Every analysis command is **read-only**: connections open `mode=ro` behind an SQLite
  authorizer that refuses writes. Never write to `Photos.sqlite`.
- Only two commands mutate, via Photos.app AppleScript: `cleanup_executor.py` (moves items
  to Recently Deleted) and `smart_export.py` (writes copies to a folder). Both preview first
  and only act when given the preview's confirmation token.
- No network access anywhere. Reports can contain names, faces, GPS and Shared Library
  contributors — never add telemetry or remote calls. See `docs/threat-model.md`.

## Conventions

- Build SQL through the schema registry (`schema.col("face.person_fk")` etc.), not hard-coded
  column names. When Apple renames a column, add the new name to the front of its candidate
  tuple in `LOGICAL_COLUMNS` in `scripts/_schema.py`.
- Every command shares the flags from `_common.py`: `--db-path`/`--library`,
  `--format json|human|md|csv`, `-o`, `-q`, `-v`, `--top`, `--limit`. JSON is the default.
- New command → `scripts/<name>.py` (the dispatcher discovers `scripts/[a-z]*.py`; add its
  one-line summary to `SUMMARIES` in `photos_cleaner.py`), add
  `references/commands/<name>.md`, add a row to the SKILL.md command table, add tests.
  `tests/test_docs_flags.py` checks documented flags match the real parsers.
- Deprecations: at least one minor release of warnings (entry in the result's `warnings`
  list) before removal in a major — except safety fixes, which may land immediately
  (see `CONTRIBUTING.md`).
- **No personal references** in tracked files: `tests/test_no_personal_refs.py` fails on a
  denylist of real names. Use neutral placeholders (Alex, Sam) in examples and fixtures,
  because ClawHub publishes the whole repository.
- Ruff: line length 120, target py310. Tests run in UTC (`pin_utc` fixture).
- Conventional commits; branches `type/short-description`.

## Releasing

Merging a version bump to `main` publishes to ClawHub (`clawhub-publish.yml`). Follow
`RELEASING.md`: bump `version:` in `SKILL.md` **and** `pyproject.toml` (enforced by
`tests/test_skill_manifest.py`), add a dated `CHANGELOG.md` section, update `ROADMAP.md`.
Breaking a flag or JSON field is a major bump plus `SCHEMA_VERSION` in `scripts/_common.py`.
Never bump versions, publish, commit or push unless explicitly asked.
