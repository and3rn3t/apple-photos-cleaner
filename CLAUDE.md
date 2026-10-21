# CLAUDE.md — apple-photos-cleaner

**Read `AGENTS.md` first** — it holds the layout, commands, safety model and conventions.
This file only adds Claude-specific notes.

Read-only Apple Photos analysis skill (stdlib Python 3.10+, macOS), published to ClawHub.

## Claude-specific notes

- Done gate: `make check && make typecheck` (runs in `./.venv`; `make install` first).
- When *using* the skill rather than developing it, follow `SKILL.md`; run
  `python3 scripts/doctor.py --format json` after any nonzero exit before retrying.
- Never run `cleanup_executor.py` or `smart_export.py` against a real library without the
  user's explicit go-ahead on the previewed plan.
- Don't write real names into any tracked file (`tests/test_no_personal_refs.py` will fail).
- Don't bump versions, commit, push or publish unless asked — a version bump merged to
  `main` publishes to ClawHub.
