# CGvalidator — CLAUDE.md

## Purpose
GUI tool for spot-checking NASA granule collections. Samples N granules from a collection via the CMR API, runs automated metadata-only checks, and presents a PASS/WARN/FAIL report. All validation is against UMM-G JSON returned by the CMR search API — no files are downloaded.

## Run
```bash
source .venv/bin/activate
python main.py
```

## Auth
Credentials in `.env` (never commit):
```
EARTHDATA_USERNAME=your_username
EARTHDATA_PASSWORD=your_password
```
Login uses `earthaccess.login(strategy="environment")`. Manual entry in the GUI temporarily injects env vars and restores them after login.

## Architecture

```
main.py                  — entry point; loads .env, suppresses FutureWarnings, launches GUI
gui/
  app.py                 — ValidatorApp (CTk/Tk root); shared state (auth, selected_collection,
                           last_validation_run); drives screen transitions via show_*() methods
  login_screen.py        — auth screen; background thread for earthaccess.login()
  search_screen.py       — collection search; populates ttk.Treeview; DAAC filter searches
                           both on-prem and cloud providers to avoid missing cloud collections
  config_screen.py       — sample size slider (1–50), date range, check toggles (one per check_id)
  results_screen.py      — runs ValidationRunner in background; 100ms polling loop; split-pane
                           detail view with collapsible lists; browse image thumbnail; CSV export
validator/
  checks.py              — 9 check functions + helpers; each returns CheckResult(status, message, details)
  runner.py              — ValidationRunner (background thread + queue.Queue); GranuleReport;
                           ValidationRun; CHECKS registry; ALL_CHECK_IDS order list
  report.py              — export_csv(), default_report_path()
```

## Threading Rule
**Never touch a Tkinter/CTk widget from a non-main thread.**
Worker threads put `("progress"|"done"|"error"|"cancelled", payload)` tuples into `runner.result_queue`. The results screen polls every 100ms via `self.after(100, self._poll)`.

## CTk / Tk Compatibility
All screens support both `customtkinter` (preferred) and plain `tkinter` via `_HAS_CTK` guards. Widget state calls that produce identical results in both libraries are written once without branching.

## Validation Checks (`validator/checks.py`)

| check_id   | What it verifies |
|------------|-----------------|
| `schema`     | Required UMM-G fields present (GranuleUR, TemporalExtent, DataGranule, RelatedUrls) |
| `temporal`   | BeginningDateTime ≤ EndingDateTime; neither is a pipeline epoch/placeholder; neither is in the future |
| `spatial`    | Coordinates in valid ranges; polygon closure; W < E (WARN on antimeridian crossing) |
| `daynight`   | DayNightFlag matches computed sun position via astral |
| `url_health` | GET DATA URL present; no http:// URLs; descriptions present; first URL responds HTTP 2xx |
| `file_size`  | No zero-byte or suspiciously tiny (<1 KB) files in ArchiveAndDistributionInformation |
| `prod_date`  | ProductionDateTime present, not an epoch/placeholder, after BeginningDateTime, not future |
| `collection` | CollectionReference.ShortName matches the selected collection |
| `duplicates` | No repeated concept-ids across the sample |

### Epoch/Placeholder Detection
`_is_epoch_placeholder(dt_str)` catches `1970-01-01*` and `0001-01-01*` sentinel strings. Shared by `check_temporal_validity` and `check_production_date_sanity`.

### URL Health Quality Issues
`check_url_health` collects static quality issues (no GET DATA URL, http:// URLs, missing descriptions) before the live HTTP probe. Issues are surfaced in `details["quality_issues"]` on all return paths. A clean probe that has quality issues returns WARN, not PASS.

### Known Limitations
- **Polar day/night**: `astral` raises at extreme latitudes → day/night check returns WARN
- **Missing SpatialExtent**: Legitimately absent on some collections → spatial/daynight return WARN
- **FutureWarnings**: `DataGranule.size()` / `.data_links()` emit FutureWarnings in earthaccess 0.18.x — suppressed globally at startup
- **CMR rate limiting**: ~10 req/s; tool fetches `page_size=1` with random `page_num` offsets to spread sampling across full collection history (max depth 1,000,000)
- **No file download**: All checks are metadata-only against UMM-G JSON

## Runner Sampling Strategy (`validator/runner.py`)
One CMR hit-count query, then one `page_size=1` request per granule at a random `page_num` in `[1, min(total_count, 1_000_000)]`. Spreads samples across the full collection rather than clustering on the most recent page.

## Adding a New Check
1. Add `check_my_thing(granule) -> CheckResult` in `validator/checks.py`
2. Add `"my_thing": ("My Thing Label", check_my_thing)` to `CHECKS` in `validator/runner.py`
3. Add `"my_thing"` to `ALL_CHECK_IDS` in `validator/runner.py`
4. Add a label string to `check_labels` dict in `gui/config_screen.py`

## Future Work
- **Platform/Instrument collection cross-check**: compare granule `Platforms`/`Instruments` against parent collection UMM-C. Deferred until a download-capable validator version exists — UMM-G search responses often omit `Platforms`, making the check low-signal without a sidecar.

## Dependencies
Key packages (`requirements.txt`):
- `earthaccess` — NASA CMR search and authenticated sessions
- `customtkinter` — modern Tk widgets
- `astral` — sun position for day/night check
- `python-dotenv` — loads `.env` credentials
- `Pillow` — browse image thumbnails in detail pane
