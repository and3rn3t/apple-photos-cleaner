# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/): a new JSON field is a minor release,
a removed or renamed one is a major. See [RELEASING.md](RELEASING.md) for how a
release is cut.

## [Unreleased]

### Added

- `docs/threat-model.md`, linked from SECURITY.md (T0.9). It lists trust boundaries, what we
  protect, and the mitigation and test behind each one.
- A deprecation policy in CONTRIBUTING.md (T0.16). Flags and JSON fields get one minor release
  of warnings before removal. Safety fixes are the only exception.

## [1.0.3] - 2026-10-13

Hygiene patch: roadmap items T0.1–T0.6, T0.8, T0.12 and T0.13.

### Changed

- **Python 3.10 is now the minimum** (T0.12). 3.9 is end-of-life. Stock macOS
  `/usr/bin/python3` (Command Line Tools) is 3.9 and no longer works; install a
  current Python with `brew install python`. CI tests 3.10, 3.14 and 3.15.
- `--year`, `--start-date` and `--end-date` are interpreted as local capture dates.

### Fixed

- **Dates use local capture time, not UTC** (T0.1). Peak hour, On This Day,
  streaks, seasons, timelines, export folders and every per-year/month/day
  bucket were shifted for anyone outside UTC. A photo taken at 23:30 on Dec 31
  in Chicago used to be counted as Jan 1. Each asset's recorded time zone
  offset is used, falling back to the Mac's current zone.
- `smart_export --end-date` now includes the end date. It stopped at midnight,
  which dropped that whole day.
- `smart_export` output-folder containment check: a symlinked subfolder
  pointing at a sibling directory sharing the same prefix (`/out-evil` next to
  `/out`) passed as "inside" the output directory (T0.8).
- `--year` rejected malformed input, except a year followed by a trailing
  newline (T0.8).

### Security

- Every GitHub Action and reusable workflow is pinned by commit SHA (Renovate, #2); a test keeps it that way (T0.6).
- Security regression suite for AppleScript escaping (including a round-trip
  through real `osascript`), path traversal, and SQL injection (T0.8).

### Removed

- Personal names and machine references in examples and fixtures (T0.2).
- The no-op Lighthouse workflow; this is a CLI with no website to audit (T0.3).
- The stale "Future Enhancements" list in SKILL.md, which now links to
  [ROADMAP.md](ROADMAP.md) (T0.4).

### Added

- Test that every flag documented in SKILL.md/README exists on its script (T0.5).
- `CHANGELOG.md`, `RELEASING.md` and a Python version policy in CONTRIBUTING.md (T0.13).

## [1.0.2] - 2026-10-12

### Fixed

- `cleanup_executor` and `smart_export` target assets by Photos UUID instead of
  filename. Filenames aren't unique, so a filename match could delete or
  export a photo the filters had excluded.

### Changed

- Full-library scans stream rows instead of loading everything with `fetchall()`.
- Dependency ranges have upper bounds.
- SKILL.md documents export safety accurately and adds a data-sensitivity section.

### Added

- ClawHub manifest fields in SKILL.md (`version`, OS restriction), a test that
  keeps them in step with `pyproject.toml`, and a publish-on-merge workflow.
- CI gates: mypy, 80% coverage floor, ruff formatting, Python 3.14.
- Repository baseline: security policy, pre-commit hooks, consistency guard,
  gitleaks, actionlint, stale, labeler and release-drafter workflows.

## [1.0.1]

Published to ClawHub without a matching version bump or tag in this
repository, so its exact contents aren't recorded. It sits between 1.0.0 and
1.0.2; everything that changed in that window is listed under 1.0.2.

## [1.0.0] - 2026-03-03

### Added

- First release as a Claude/OpenClaw skill: 20 stdlib-only scripts that read
  the Photos SQLite database read-only. They cover library analysis, storage,
  junk and duplicate detection, timeline recaps, people, places, scenes, photo
  habits, On This Day, album audit, Live Photos, iCloud status, Shared Library,
  similarity, seasonal highlights and face quality.
- Opt-in mutating commands: `cleanup_executor` (moves items to Recently Deleted
  via Photos.app) and `smart_export` (exports copies via AppleScript), both
  preview-first.
- Schema detection for the old and new (`ZPERSONFORFACE`/`ZASSETFORFACE`) face tables.

[Unreleased]: https://github.com/and3rn3t/apple-photos-cleaner/compare/v1.0.3...HEAD
<!-- No tags existed before 1.0.3; versions are anchored on commits. -->
[1.0.3]: https://github.com/and3rn3t/apple-photos-cleaner/compare/05552f3...v1.0.3
[1.0.2]: https://github.com/and3rn3t/apple-photos-cleaner/compare/cf2f97e...05552f3
[1.0.0]: https://github.com/and3rn3t/apple-photos-cleaner/tree/cf2f97e
