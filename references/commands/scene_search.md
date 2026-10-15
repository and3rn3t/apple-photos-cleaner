# Scene / Content Search — `scene_search.py`

Search photos by ML-detected scene classifications (beach, sunset, dog, food, etc.) or generate a complete content inventory.

> **Not available on macOS 26 (Tahoe).** Its Photos database keys scenes by numeric
> `ZSCENEIDENTIFIER` and has no `ZSCENENAME` or `ZSCENECLASSIFICATION.ZASSET`, so this command
> exits 5 and the scene sections of `on_this_day` and `timeline_recap` are `degraded`. Run
> `doctor.py` to see what your library supports.

```bash
python3 scripts/scene_search.py [--search TERM] [--min-confidence N] [--human]
```

**Options:**
- `--search TERM` — Scene name to search for (omit for content inventory)
- `--min-confidence N` — Minimum confidence score (default: 0.0)
- `--top N` — Number of search results (default: 50)
- `--year YYYY` — Filter to specific year
- `--human` — Human-readable summary
- `--output FILE` — Write JSON to file

**Modes:**
1. **Search mode** (`--search beach`) — Find all photos matching a scene label
2. **Inventory mode** (no --search) — Show all scene labels with counts, grouped by category

**Example Output (inventory):**
```
🏷️  SCENE / CONTENT SEARCH
==================================================

Unique scene labels: 234
Scene-tagged entries: 45,678
Library total: 12,453

By Category:
  📂 Nature Outdoor (5,678 photos)
    beach: 234
    sunset: 189
    mountain: 156
  📂 Animals (2,345 photos)
    dog: 1,234
    cat: 567
  📂 Food Drink (1,890 photos)
    food: 890
    coffee: 234
```

**Usage in Conversation:**

**User:** "How many beach photos do I have?"  
**AI:** *Runs scene_search.py --search beach, reports count and related scenes*

**User:** "What kinds of photos do I take?"  
**AI:** *Runs scene_search.py (inventory mode), summarizes categories*

---

[← All commands](../../SKILL.md#commands)
