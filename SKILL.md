---
name: apple-photos-cleaner
description: Analyze, clean up, and organize Apple Photos libraries. Find and report junk photos (screenshots, low-quality, burst leftovers, duplicates), analyze storage usage, generate photo timeline recaps, and plan smart exports. All operations are READ-ONLY on the database (safe). Trigger on: Photos cleanup, photo storage, duplicate photos, junk photos, screenshot cleanup, Photos analysis, photo timeline, photo export, Photos library stats, burst cleanup, storage hogs, photo organization.
---

# Apple Photos Cleaner

Comprehensive toolkit for analyzing and cleaning up Apple Photos libraries. Goes beyond what Photos.app offers: intelligent junk detection, detailed storage analysis, duplicate finding with quality scoring, timeline recaps for storytelling, and smart export planning.

## Overview

Apple Photos is great at organizing and syncing photos, but it's not so great at cleanup. This skill fills that gap:

- **Library Analysis** — Get the big picture: counts, storage, date ranges, people, quality distribution
- **Junk Finder** — Identify screenshots, low-quality photos, burst leftovers, old screenshots
- **Duplicate Finder** — Find duplicates using Apple's detection + timestamp/dimension matching
- **Storage Analyzer** — Detailed breakdown by year, type, file format, growth trends, storage hogs
- **Timeline Recap** — Generate narrative summaries of photo activity for any date range
- **Smart Export** — Plan organized exports by year/month, person, album, or location

**Safety:** All operations are READ-ONLY database queries. No photos are modified or deleted without explicit user action.

## When to Use This Skill

Use when users mention:
- Cleaning up Photos / freeing up photo storage
- Finding duplicate photos
- Removing old screenshots
- Analyzing Photos library storage
- Finding junk or low-quality photos
- Organizing photo exports
- Getting photo timeline summaries ("what did I do last week?")
- Burst photo cleanup
- Finding storage hogs in Photos

## Quick Start

All scripts work standalone. The Photos database is automatically located at:
`~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite`

**Basic workflow:**
1. Run `library_analysis.py` to get overview
2. Run `junk_finder.py` to identify cleanup candidates
3. Run `duplicate_finder.py` to find duplicates
4. Use results to guide manual cleanup in Photos.app

## Commands

### 1. Library Analysis

Get comprehensive library statistics: counts, storage, date ranges, people, quality scores.

```bash
python3 scripts/library_analysis.py [--human] [--output FILE]
```

**Options:**
- `--human` — Human-readable summary instead of JSON
- `--output FILE` — Write JSON to file
- `--db-path PATH` — Custom database path
- `--library PATH` — Custom Photos library path

**Example Output:**
```
📊 APPLE PHOTOS LIBRARY ANALYSIS
==================================================

Total Assets: 12,453
Total Storage: 48.3 GB
Average Size: 4.1 MB
Date Range: 2020-01-15 to 2025-03-03

By Type:
  Photo: 11,234
  Video: 891
  Screenshots: 328
  Favorites: 456
  Bursts: 1,234

By Year:
  2025: 1,203 items, 5.2 GB
  2024: 3,456 items, 15.1 GB
  2023: 2,987 items, 12.4 GB
  ...

Top People:
  Jonah: 3,456 photos
  Silas: 3,234 photos
  ...
```

**Usage in Conversation:**

**User:** "How many photos do I have?"  
**AI:** *Runs library_analysis.py with --human flag, reports summary*

**User:** "Show me my Photos storage breakdown"  
**AI:** *Runs library_analysis.py, highlights key stats*

---

### 2. Junk Finder

Identify cleanup candidates: screenshots, low-quality photos, burst leftovers, duplicates.

```bash
python3 scripts/junk_finder.py [--screenshot-age DAYS] [--quality-threshold N] [--human]
```

**Options:**
- `--screenshot-age DAYS` — Consider screenshots older than N days as junk (default: 30)
- `--quality-threshold N` — Quality score threshold for low-quality (default: 0.3, range: 0.0-1.0)
- `--no-duplicates` — Skip duplicate detection
- `--human` — Human-readable summary
- `--output FILE` — Write JSON to file

**Example Output:**
```
🗑️  JUNK FINDER RESULTS
==================================================

Found:
  📸 Screenshots: 328
     └─ Old (>30 days): 287
  📉 Low Quality: 156
  📸 Burst Leftovers: 1,089
  👥 Possible Duplicates: 45

Estimated Savings:
  Conservative: 2.3 GB
    (Old screenshots + burst leftovers)
  Aggressive: 5.7 GB
    (All screenshots + low quality + bursts + ~50% of duplicates)
```

**What It Finds:**
- **Screenshots** — Detected via `ZISDETECTEDSCREENSHOT` flag
- **Old screenshots** — Screenshots older than specified age (safe to delete)
- **Low quality** — Photos with low quality scores (high failure/noise, low composition/lighting)
- **Burst leftovers** — Unpicked photos from burst sequences
- **Possible duplicates** — Using Apple's built-in detection

**Usage in Conversation:**

**User:** "Find junk in my Photos"  
**AI:** *Runs junk_finder.py, reports totals and estimated savings*

**User:** "How many old screenshots do I have?"  
**AI:** *Runs junk_finder.py, focuses on screenshot stats*

**User:** "What can I delete to free up 5GB?"  
**AI:** *Runs junk_finder.py, shows conservative/aggressive estimates, suggests next steps*

---

### 3. Duplicate Finder

Find duplicate photos and recommend which to keep based on quality, favorite status, and file size.

```bash
python3 scripts/duplicate_finder.py [--human] [--output FILE]
```

**Detection Methods:**
1. **Apple's built-in** — Uses `ZDUPLICATEASSETVISIBILITYSTATE`
2. **Timestamp + dimensions** — Photos taken at same second with same dimensions

**Recommendation Logic:**
- Favorites get priority
- Screenshots get penalty
- Highest quality score preferred
- Largest file size as tiebreaker

**Example Output:**
```
👥 DUPLICATE FINDER RESULTS
==================================================

Found 12 duplicate groups
Total duplicates: 27
Can safely delete: 15
Total size: 156 MB
Potential savings: 89 MB

Sample groups (showing first 5):

Group 1 (apple_builtin):
  ✓ KEEP ★ IMG_1234.jpg (4.2 MB, Q:0.823)
    DELETE   IMG_1234-2.jpg (4.1 MB, Q:0.801)

Group 2 (timestamp_dimensions):
  ✓ KEEP   IMG_5678.heic (2.8 MB, Q:0.756)
    DELETE   IMG_5678-edited.jpg (3.1 MB, Q:0.654)
```

**Usage in Conversation:**

**User:** "Do I have duplicate photos?"  
**AI:** *Runs duplicate_finder.py, reports findings*

**User:** "Find duplicates and tell me which to delete"  
**AI:** *Runs duplicate_finder.py, explains recommendations*

---

### 4. Storage Analyzer

Detailed storage breakdown: by year, type, source, growth trends, file types, storage hogs.

```bash
python3 scripts/storage_analyzer.py [--human] [--output FILE]
```

**Analyzes:**
- Total storage and breakdown by photo/video
- Storage by year and month
- Screenshots vs regular photos
- File types (JPEG, HEIC, MOV, etc.)
- Growth trends over time
- Top 20 largest files

**Example Output:**
```
💾 STORAGE ANALYSIS
==================================================

Total Storage: 48.3 GB

By Type:
  Photo: 32.1 GB (66.5%)
    11,234 items, avg 2.9 MB
  Video: 16.2 GB (33.5%)
    891 items, avg 18.7 MB

By Source:
  Photos & Videos: 46.1 GB (95.4%)
  Screenshots: 2.2 GB (4.6%)

By Year:
  2025: 5.2 GB (1,203 items)
  2024: 15.1 GB (3,456 items)
  2023: 12.4 GB (2,987 items)
  ...

Top 10 Largest Files:
  1. 📹 287 MB - VID_2024_vacation.mov
  2. 📹 245 MB - VID_2024_swim_meet.mov
  3. 📹 198 MB - VID_2023_birthday.mov
  ...

Recent Growth (last 12 months):
  Total added: 18.7 GB
  Average per month: 1.6 GB
```

**Usage in Conversation:**

**User:** "What's taking up space in my Photos?"  
**AI:** *Runs storage_analyzer.py, highlights biggest categories*

**User:** "Show me my largest videos"  
**AI:** *Runs storage_analyzer.py, focuses on storage_hogs section filtered by videos*

**User:** "How much storage am I adding per month?"  
**AI:** *Runs storage_analyzer.py, reports recent growth stats*

---

### 5. Timeline Recap

Generate narrative summaries of photo activity for any date range. Groups photos into events and includes context: people, locations, scenes.

```bash
python3 scripts/timeline_recap.py --start-date YYYY-MM-DD [--end-date YYYY-MM-DD] [--narrative]
```

**Options:**
- `--start-date` — Start date (required)
- `--end-date` — End date (optional, defaults to today)
- `--cluster-hours N` — Hours between photos to consider separate events (default: 4)
- `--narrative` — Output narrative text instead of JSON
- `--output FILE` — Write to file

**What It Generates:**
- Day-by-day photo activity
- Event clustering (groups photos taken close together)
- People detected in each event
- Scene classifications (beach, sunset, dog, etc.)
- Location data (if available)
- Favorites count

**Example Output:**
```
📅 PHOTO TIMELINE RECAP
==================================================

Period: 2025-03-01 to 2025-03-07
Total: 156 photos across 5 days
Events: 12

📆 2025-03-01 (Saturday) - 45 photos

  🕐 09:15 (2h 15m)
     32 photos, 2 videos ⭐ 5 favorites
     👥 Jonah, Silas
     🏷️  swimming, pool, sports
     📍 41.5369, -90.5776

  🕐 18:30 (45m)
     13 photos
     👥 Jonah, Silas
     🏷️  dinner, food, family
```

**Usage in Conversation:**

**User:** "What did I do last week?"  
**AI:** *Runs timeline_recap.py with last week's dates, narrates the timeline in story form*

**User:** "Show me my photo activity for February"  
**AI:** *Runs timeline_recap.py with Feb 1 - Feb 28, summarizes highlights*

**User:** "Tell me about our vacation photos from August"  
**AI:** *Runs timeline_recap.py with August dates, creates a narrative story*

**AI Tip:** When presenting timeline results, narrate them like a story! Don't just dump the JSON. Example:

> "You had a busy Saturday on March 1st! In the morning around 9:15, you spent about 2 hours at the pool — 32 photos with Jonah and Silas, mostly swimming and sports shots. You marked 5 as favorites. Then in the evening around 6:30, you captured a family dinner with 13 photos. Looks like a great day!"

---

### 6. Smart Export

Plan organized exports by year/month, person, album, or location. Shows what will be exported without actually doing it (unless confirmed).

```bash
python3 scripts/smart_export.py --output-dir PATH [--organize-by MODE] [--plan-only]
```

**Options:**
- `--output-dir PATH` — Where to export (required)
- `--organize-by MODE` — How to organize: `year_month`, `person`, `album`, `location` (default: year_month)
- `--favorites` — Export only favorites
- `--start-date YYYY-MM-DD` — Filter by start date
- `--end-date YYYY-MM-DD` — Filter by end date
- `--person NAME` — Export only photos with this person
- `--album NAME` — Export only from this album
- `--plan-only` — Show plan without exporting (recommended first step)

**Example Output:**
```
📤 EXPORT PLAN
==================================================
Organization: year_month
Total photos: 3,456
Total size: 15.2 GB
Folders: 36

Folders:
  2025/01-January/
    123 items, 542 MB
  2025/02-February/
    156 items, 687 MB
  2025/03-March/
    89 items, 398 MB
  ...
```

**Note:** Actual export via AppleScript is not fully implemented. This command generates the export plan and folder structure. For now, use this to identify what to export, then do it manually in Photos.app.

**Usage in Conversation:**

**User:** "I want to export all my 2024 photos organized by month"  
**AI:** *Runs smart_export.py with year filter and --plan-only, shows the plan*

**User:** "Export all photos with Jonah"  
**AI:** *Runs smart_export.py with --person "Jonah" and --plan-only, shows what would be exported*

---

## Database Schema Reference

Detailed schema documentation is in `references/database-schema.md`. Key tables:

- **ZASSET** — Main photos/videos table
- **ZADDITIONALASSETATTRIBUTES** — File sizes, dimensions
- **ZCOMPUTEDASSETATTRIBUTES** — Apple's quality scores
- **ZPERSON** — Detected people
- **ZDETECTEDFACE** — Face detections
- **ZGENERICALBUM** — Albums
- **ZSCENECLASSIFICATION** — ML scene labels

**Important:** Core Data timestamps are seconds since 2001-01-01, not Unix epoch.

## Common Workflows

### Workflow 1: Quick Cleanup Assessment

```bash
# Get overview
python3 scripts/library_analysis.py --human

# Find junk
python3 scripts/junk_finder.py --human

# Review and manually clean up in Photos.app
```

### Workflow 2: Free Up Storage

```bash
# Analyze storage
python3 scripts/storage_analyzer.py --human

# Find duplicates
python3 scripts/duplicate_finder.py --human

# Find junk with aggressive settings
python3 scripts/junk_finder.py --screenshot-age 14 --quality-threshold 0.4 --human

# Use findings to guide cleanup
```

### Workflow 3: Year-End Photo Recap

```bash
# Generate timeline for the year
python3 scripts/timeline_recap.py --start-date 2024-01-01 --end-date 2024-12-31 --narrative

# Get storage stats by year
python3 scripts/storage_analyzer.py | jq '.by_year'

# Get top people for the year
python3 scripts/library_analysis.py | jq '.top_people'
```

### Workflow 4: Export Organized Archive

```bash
# Plan export
python3 scripts/smart_export.py --output-dir ~/Desktop/Photos-Export --favorites --start-date 2024-01-01 --plan-only

# Review plan, then execute (manual for now)
```

## Tips for AI Assistants

### When User Asks About Photos Cleanup

1. **Start with analysis** — Run `library_analysis.py` to understand the library
2. **Find junk** — Run `junk_finder.py` to quantify cleanup opportunities
3. **Be specific** — Don't just say "you have junk photos," say "you have 287 screenshots older than 30 days (2.1 GB) that could be deleted"
4. **Explain savings** — Always mention estimated storage savings
5. **Guide to Photos.app** — Scripts identify candidates, but user must delete via Photos.app

### When User Asks "What Did I Do?"

1. **Use timeline_recap** — Perfect for narrative summaries
2. **Narrate, don't dump** — Turn JSON into a story
3. **Highlight favorites** — Mention standout moments
4. **Use emojis** — Makes it more engaging

### When User Asks About Storage

1. **Run storage_analyzer** — Most comprehensive view
2. **Identify hogs** — Call out the biggest files/categories
3. **Show trends** — "You're adding about 1.5 GB per month"
4. **Suggest actions** — "Deleting old screenshots could free up 2 GB"

### Output Format Guidance

**JSON output:** Default for programmatic use, includes full details

**Human output:** Use `--human` flag for readable summaries

**In conversation:** Synthesize the data into natural language, don't just read the output

## Requirements

- **Python:** 3.9+ (tested with 3.13)
- **Platform:** macOS only (Apple Photos database)
- **Dependencies:** None (uses only Python stdlib)
- **Database:** Read-only access to `~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite`

## Safety & Permissions

- ✅ **All operations are READ-ONLY** — No photos are modified or deleted
- ✅ **No external dependencies** — Pure Python stdlib
- ✅ **No Photos.app API** — Direct SQLite reads (safe)
- ⚠️ **Smart export uses AppleScript** — Would require Photos.app permissions (not implemented yet)

## Limitations

- **Read-only** — Scripts identify candidates, but cleanup must be done manually in Photos.app
- **No actual deletion** — Scripts don't delete anything, they just report
- **Export is placeholder** — AppleScript export logic not fully implemented
- **Empty library support** — Scripts work on any library, but Matt's Mac mini library is empty (synced elsewhere)
- **Schema changes** — Apple may change database schema in future macOS versions

## Troubleshooting

**"Database not found"**  
→ Specify path with `--library ~/Path/To/Photos Library.photoslibrary`

**"Permission denied"**  
→ Close Photos.app first, or run script while Photos.app is open (read-only is safe)

**"No quality scores"**  
→ Not all photos have computed quality attributes; scripts handle NULLs gracefully

**"Results don't match Photos.app counts"**  
→ Scripts exclude trashed items; Photos.app may show different views

## Future Enhancements

Ideas for future expansion:
- Actual AppleScript export implementation
- Batch delete via AppleScript (with confirmation)
- Photo face recognition quality analysis
- Live Photo vs still comparison
- Shared library analysis
- iCloud sync status integration

---

**Bottom line:** This skill gives you X-ray vision into your Photos library. Use it to understand what you have, find what you don't need, and make cleanup decisions with confidence.
