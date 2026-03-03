# Error Handling & Logging Audit Report

**Codebase**: apple-photos-cleaner
**Date**: 2025
**Scope**: All files in `scripts/` and `tests/`

---

## Executive Summary

The codebase is generally well-structured with consistent patterns (shared `run_script()` boilerplate, `PhotosDB` context manager, `_safe_float()`/`_safe_col()` helpers). However, there are **SQL injection vulnerabilities** in 5 scripts, **zero use of Python's logging module**, **missing input validation** in several scripts, and **no error handling around critical I/O operations**. The most severe issues involve unparameterized SQL and the potential for destructive operations (cleanup_executor, smart_export) to fail silently.

**Finding counts by severity:**

- **HIGH**: 5 findings
- **MEDIUM**: 8 findings
- **LOW**: 6 findings

---

## HIGH Severity

### H1. SQL Injection via Unvalidated `year` Parameter (5 scripts)

**Scripts affected:**

- [best_photos.py](scripts/best_photos.py#L46) — `year` interpolated directly
- [photo_habits.py](scripts/photo_habits.py#L35) — `year` interpolated directly
- [seasonal_highlights.py](scripts/seasonal_highlights.py#L78) — `year` interpolated directly
- [live_photo_analyzer.py](scripts/live_photo_analyzer.py#L99) — `year` interpolated directly
- [on_this_day.py](scripts/on_this_day.py#L53-L55) — `current_year` interpolated directly

**Problem**: These scripts interpolate a `year` parameter directly into SQL via f-strings without calling `validate_year()`. While this is a read-only database, malformed input could cause SQL errors or unexpected query behavior. Three other scripts (`similarity_finder.py`, `scene_search.py`, `location_mapper.py`) correctly use `validate_year()` already.

**Example** ([best_photos.py](scripts/best_photos.py#L46)):

```python
# CURRENT — vulnerable
if year:
    where_clauses.append(f"strftime('%Y', datetime(a.ZDATECREATED + 978307200, 'unixepoch')) = '{year}'")
```

**Fix**:

```python
from _common import validate_year

# In function body:
if year:
    year = validate_year(year)
    where_clauses.append(f"strftime('%Y', datetime(a.ZDATECREATED + 978307200, 'unixepoch')) = '{year}'")
```

Apply the same pattern to all 5 scripts. `validate_year()` already exists in `_common.py` and rejects anything that is not exactly 4 digits.

---

### H2. Unvalidated Timestamps Interpolated into SQL (timeline_recap.py)

**File**: [timeline_recap.py](scripts/timeline_recap.py#L42-L47)

**Problem**: `start_date` and `end_date` are parsed via `datetime.fromisoformat()` then converted to a float via `datetime_to_coredata()`, which is then interpolated directly into the SQL query string. While `fromisoformat()` constrains the initial input, the resulting float is still embedded without parameterization.

```python
# CURRENT
timestamp = datetime_to_coredata(dt)
where_clauses.append(f"a.ZDATECREATED >= {timestamp}")
```

**Fix**: Use parameterized queries:

```python
timestamp = datetime_to_coredata(dt)
where_clauses.append("a.ZDATECREATED >= ?")
params.append(timestamp)
# ... later:
cursor.execute(query, params)
```

---

### H3. `connect_db()` Has No Error Handling

**File**: [_common.py](scripts/_common.py#L56-L71)

**Problem**: `connect_db()` calls `sqlite3.connect()` with no try/except. If the database is locked, the file doesn't exist at the URI level, or the file is corrupted, the raw `sqlite3` exception propagates with an unhelpful message. This is the single point of entry for all 17 scripts.

```python
# CURRENT
def connect_db(db_path: str) -> sqlite3.Connection:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn
```

**Fix**:

```python
def connect_db(db_path: str) -> sqlite3.Connection:
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.OperationalError as e:
        if "unable to open" in str(e).lower():
            raise FileNotFoundError(
                f"Cannot open database: {db_path}\n"
                "Ensure Photos.app is not performing a migration."
            ) from e
        if "locked" in str(e).lower():
            raise RuntimeError(
                f"Database is locked: {db_path}\n"
                "Close Photos.app or wait and retry."
            ) from e
        raise
    conn.row_factory = sqlite3.Row
    return conn
```

---

### H4. `output_json()` Has No Error Handling for File Write

**File**: [_common.py](scripts/_common.py#L129-L144)

**Problem**: `output_json()` opens and writes a file with no error handling. A full disk, permission error, or invalid path silently crashes.

```python
# CURRENT
if output_file:
    with open(output_file, "w") as f:
        f.write(json_str)
```

**Fix**:

```python
if output_file:
    try:
        with open(output_file, "w") as f:
            f.write(json_str)
    except OSError as e:
        print(f"Error writing output to {output_file}: {e}", file=sys.stderr)
        # Fall back to stdout so data isn't lost
        print(json_str)
        return
```

---

### H5. AppleScript Errors Can Silently Skip Files (cleanup_executor.py)

**File**: [cleanup_executor.py](scripts/cleanup_executor.py) — the generated AppleScript uses `try/end try` blocks

**Problem**: The generated AppleScript wraps each file search in `try`/`end try`. If a file isn't found or can't be deleted, it silently skips it. The Python code only checks `returncode` of the overall `osascript` process. If 5 of 10 files silently fail inside AppleScript, the success count still reports all 10 as deleted.

**Fix**: Have the AppleScript accumulate failure filenames and return them in stdout, then parse and report:

```applescript
set failedFiles to {}
repeat with fname in fileList
    try
        -- delete logic
    on error errMsg
        set end of failedFiles to (fname as text) & ": " & errMsg
    end try
end repeat
return (count of failedFiles) & " failures: " & (failedFiles as text)
```

Then in Python, parse stdout to extract actual success/failure counts.

---

## MEDIUM Severity

### M1. No Python `logging` Module Used Anywhere

**Finding**: Zero occurrences of `import logging` across the entire codebase. All diagnostic output uses `print(..., file=sys.stderr)`.

**Impact**: No log levels, no log rotation, no structured logging, no way to filter verbosity. Users can't distinguish warnings from info from debug output.

**Files affected**: All 17 scripts and `_common.py`

**Fix**: Introduce logging in `_common.py` and use it everywhere:

```python
# In _common.py
import logging

def setup_logging(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    return logging.getLogger("photos-cleaner")

logger = setup_logging()
```

Then replace `print(f"Error: ...", file=sys.stderr)` with `logger.error(...)`, etc.

---

### M2. `PhotosDB.__exit__` Doesn't Propagate Exception Info

**File**: [_common.py](scripts/_common.py#L276-L280)

**Problem**: The `__exit__` method closes the connection but always returns `None` (falsy), which is correct—it doesn't suppress exceptions. However, if `conn.close()` itself raises (e.g., during a corrupted WAL cleanup), that exception replaces the original.

```python
def __exit__(self, exc_type, exc_val, exc_tb):
    if self.conn:
        self.conn.close()
```

**Fix**:

```python
def __exit__(self, exc_type, exc_val, exc_tb):
    if self.conn:
        try:
            self.conn.close()
        except sqlite3.Error:
            if exc_type is None:
                raise  # Only raise if no existing exception
```

---

### M3. No Progress Indication for O(n²) Operations

**Files affected**:

- [similarity_finder.py](scripts/similarity_finder.py) — compares every photo pair (lines ~105-130)
- [album_auditor.py](scripts/album_auditor.py) — album overlap comparison (lines ~160-195)

**Problem**: These scripts perform $O(n^2)$ comparisons with no progress output. For a library with 50,000 photos, similarity checking involves ~1.25 billion comparisons and could appear hung.

**Fix**: Add periodic stderr progress updates:

```python
total_pairs = len(photos) * (len(photos) - 1) // 2
for idx, (i, j) in enumerate(combinations(range(len(photos)), 2)):
    if idx % 100000 == 0:
        print(f"\r  Comparing: {idx:,}/{total_pairs:,} pairs...",
              end="", file=sys.stderr)
```

---

### M4. `format_size()` Doesn't Handle Negative Sizes

**File**: [_common.py](scripts/_common.py#L108-L126)

**Problem**: `format_size()` handles `None` and `0` but not negative values. A corrupted `ZORIGINALFILESIZE` value of `-1` would produce "-1 B" strings that propagate to output.

**Fix**:

```python
def format_size(size_bytes: Optional[int]) -> str:
    if size_bytes is None or size_bytes <= 0:
        return "0 B"
```

---

### M5. `run_script()` Catches Generic `Exception` but Doesn't Distinguish Types

**File**: [_common.py](scripts/_common.py#L459-L466)

**Problem**: The catch-all `except Exception` in `run_script()` prints a traceback for every error type. For `sqlite3.OperationalError` (database locked), `PermissionError`, or `KeyboardInterrupt` (not caught—but `SystemExit` would bypass it), the user gets a generic traceback dump rather than an actionable message.

```python
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    traceback.print_exc()
    return 1
```

**Fix**: Add targeted catches before the generic one:

```python
except KeyboardInterrupt:
    print("\nCancelled.", file=sys.stderr)
    return 130
except sqlite3.OperationalError as e:
    print(f"Database error: {e}", file=sys.stderr)
    if "locked" in str(e).lower():
        print("Try closing Photos.app and retrying.", file=sys.stderr)
    return 1
except FileNotFoundError as e:
    print(f"Error: {e}", file=sys.stderr)
    return 1
except Exception as e:
    print(f"Unexpected error: {e}", file=sys.stderr)
    traceback.print_exc()
    return 1
```

---

### M6. `timeline_recap.py` and `cleanup_executor.py` Have Custom `main()` Without `run_script()`

**Files**:

- [timeline_recap.py](scripts/timeline_recap.py#L325-L369) — custom main()
- [cleanup_executor.py](scripts/cleanup_executor.py#L390-L480) — custom main()
- [smart_export.py](scripts/smart_export.py#L262-L366) — custom main()

**Problem**: These three scripts implement their own argument parsing and error handling instead of using `run_script()`. This means they miss any future improvements to the shared error handling (like the suggestion in M5). Currently their error handling is adequate but inconsistent with the other 14 scripts.

**Recommendation**: Document clearly which scripts use custom `main()` and why. Refactor if possible to share at least the error handling layer.

---

### M7. `on_this_day.py` — `date(2000, month, day)` Can Raise ValueError

**File**: [on_this_day.py](scripts/on_this_day.py#L48)

**Problem**: `date(2000, month, day)` is used as a "base date" for offset calculations. While 2000 *is* a leap year (so Feb 29 works), if `target_date` is somehow invalid before reaching this line, the code would fail. More importantly, the `try`/`except ValueError` on line 50 only wraps the timedelta addition, not the initial `date(2000, month, day)`.

**Current code handles this acceptably** for valid ISO dates (since `date.fromisoformat()` already validates), but it's fragile if the API is called programmatically with raw month/day values.

---

### M8. Missing Test Coverage for Error Paths

**Tests audited**: All 4 test files + conftest.py.

**Gaps identified**:

- No tests for `connect_db()` failure modes (locked DB, missing file)
- No tests for `output_json()` write failures
- No tests for `format_size()` with negative values
- No tests for scripts receiving invalid `year` values (only `validate_year()` itself is tested in test_common.py)
- No tests for `PhotosDB.__exit__` when `conn.close()` raises
- No integration tests for AppleScript failure scenarios in cleanup_executor's generated scripts

---

## LOW Severity

### L1. `live_photo_analyzer.py` — `year` Parameter Not Validated

**File**: [live_photo_analyzer.py](scripts/live_photo_analyzer.py#L99)

**Problem**: Uses f-string SQL interpolation with `year` without calling `validate_year()`. Same class of issue as H1 but in a read-only, non-destructive context.

**Fix**: Import and call `validate_year(year)` before use.

---

### L2. Division-by-Zero Guards Are Inconsistent

**Files with proper guards** (using `if scores`, `max(1, total)`, etc.):

- `face_quality.py`, `icloud_status.py`, `shared_library.py`, `scene_search.py`, `storage_analyzer.py`, `seasonal_highlights.py`

**Files where guards could be tighter**:

- [album_auditor.py](scripts/album_auditor.py) — `overlap_pct` calculation: `shared / len(a1_photos) * 100`. If `a1_photos` is an empty set after filtering, this divides by zero. The current code guards with `if a1["photo_ids"]` but the `photo_ids` set could theoretically be empty.

**Recommendation**: Standardize on the `max(1, denominator)` pattern project-wide.

---

### L3. `junk_finder.py` — Potential `None` Comparison

**File**: [junk_finder.py](scripts/junk_finder.py)

**Problem**: Accesses `row["ZDATECREATED"]` and compares it without an explicit None check. If `ZDATECREATED` is NULL in the database, comparison with a numeric threshold raises `TypeError`.

**Fix**:

```python
if row["ZDATECREATED"] is not None and row["ZDATECREATED"] < screenshot_threshold:
```

---

### L4. `similarity_finder.py` — No Limit on Number of Photos Compared

**File**: [similarity_finder.py](scripts/similarity_finder.py)

**Problem**: Loads ALL photos with feature vectors into memory and does $O(n^2)$ comparisons. For a 100K photo library this is ~5 billion comparisons and will likely exhaust memory/time.

**Fix**: Add a `--limit` CLI argument with a sensible default (e.g., 5000), or implement approximate nearest-neighbor techniques.

---

### L5. Inconsistent Error Exit Codes

**Problem**: Scripts using `run_script()` return 0 or 1. `cleanup_executor.py`'s custom `main()` uses `sys.exit(0)` and `sys.exit(1)`. `timeline_recap.py` and `smart_export.py` use the same pattern. None use specific exit codes (e.g., 2 for usage error, 130 for interrupt).

**Recommendation**: Standardize exit codes:

- 0 = success
- 1 = runtime error
- 2 = usage/argument error
- 130 = keyboard interrupt

---

### L6. `smart_export.py` — Path Traversal Check But No Symlink Check

**File**: [smart_export.py](scripts/smart_export.py)

**Problem**: `sanitize_folder_name()` strips `../` but doesn't resolve symlinks. A symlink in the output directory could redirect exports outside the intended path.

**Fix**: Add `os.path.realpath()` resolution after constructing the full export path, then verify it still starts with the intended output directory.

---

## Summary Table

| ID  | Severity | Category               | File(s)                              | Status     |
|-----|----------|------------------------|--------------------------------------|------------|
| H1  | HIGH     | SQL Injection          | best_photos, photo_habits, seasonal_highlights, live_photo_analyzer, on_this_day | Open |
| H2  | HIGH     | SQL Injection          | timeline_recap                       | Open       |
| H3  | HIGH     | Database Error Handling| _common.py `connect_db()`            | Open       |
| H4  | HIGH     | File I/O Error         | _common.py `output_json()`           | Open       |
| H5  | HIGH     | Silent Failures        | cleanup_executor AppleScript         | Open       |
| M1  | MEDIUM   | Logging                | All scripts                          | Open       |
| M2  | MEDIUM   | Resource Management    | _common.py `PhotosDB.__exit__`       | Open       |
| M3  | MEDIUM   | Progress Indicators    | similarity_finder, album_auditor     | Open       |
| M4  | MEDIUM   | Input Validation       | _common.py `format_size()`           | Open       |
| M5  | MEDIUM   | Error Handling         | _common.py `run_script()`            | Open       |
| M6  | MEDIUM   | Consistency            | timeline_recap, cleanup_executor, smart_export | Open |
| M7  | MEDIUM   | Edge Case              | on_this_day                          | Open       |
| M8  | MEDIUM   | Test Coverage          | tests/                               | Open       |
| L1  | LOW      | SQL Injection          | live_photo_analyzer                  | Open       |
| L2  | LOW      | Division by Zero       | album_auditor                        | Open       |
| L3  | LOW      | Null Handling          | junk_finder                          | Open       |
| L4  | LOW      | Resource Limits        | similarity_finder                    | Open       |
| L5  | LOW      | Exit Codes             | All scripts                          | Open       |
| L6  | LOW      | Path Security          | smart_export                         | Open       |

---

## Positive Patterns (Already Done Well)

1. **`PhotosDB` context manager** — clean resource management for DB connections across all scripts
2. **`_safe_float()` and `_safe_col()`** — robust handling of nullable database columns
3. **`validate_year()` exists** — just needs wider adoption
4. **`escape_applescript()` and `sanitize_folder_name()`** — proper input sanitization for AppleScript/filesystem
5. **Read-only database mode** — `?mode=ro` in URI prevents accidental writes
6. **`build_asset_query()`** — centralized query builder reduces SQL duplication
7. **`run_script()` boilerplate** — 14 of 17 scripts share argument parsing and error handling
8. **Subprocess timeout** — both `cleanup_executor.py` (120s) and `smart_export.py` (600s) use `timeout=` on subprocess calls
9. **Interactive confirmation** — `cleanup_executor.py` requires typing "yes" before destructive operations
10. **Tests cover happy paths well** — comprehensive test suites for all scripts with mock DB fixtures
