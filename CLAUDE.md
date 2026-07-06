# CGvalidator — CLAUDE.md

## Project Purpose
Automate the manual process of validating NASA granule collections. Data scientists currently hand-pick 3–5 granules and manually skim their metadata. This tool samples N granules, runs automated checks, and presents a pass/warn/fail report in a lightweight GUI.

## How to Run
```bash
source .venv/bin/activate
python main.py
```

## Authentication
Credentials live in `.env` (never commit this file):
```
EARTHDATA_USERNAME=your_username
EARTHDATA_PASSWORD=your_password
```
Login is handled by `earthaccess.login(strategy="environment")` in `gui/login_screen.py`.

## Architecture

```
main.py              — entry point; loads .env, suppresses FutureWarnings, launches GUI
gui/
  app.py             — ValidatorApp (CTk/Tk root); holds shared state (auth, selected_collection,
                       last_validation_run); drives screen navigation via show_*() methods
  login_screen.py    — auth screen; background thread for earthaccess.login()
  search_screen.py   — collection search; populates ttk.Treeview with results
  config_screen.py   — sample size slider, date range, check toggles
  results_screen.py  — runs ValidationRunner in background; polling loop; detail pane; CSV export
validator/
  checks.py          — 9 modular check functions returning CheckResult(check_name, status, message, details)
  runner.py          — ValidationRunner (background thread + queue.Queue); GranuleReport; ValidationRun
  report.py          — export_csv(), export_summary_text(), default_report_path()
```

## Threading Rule
**Never touch a Tkinter/CTk widget from a non-main thread.**
All earthaccess calls run in daemon background threads. The `results_screen.py` polls `runner.result_queue` every 100 ms via `self.after(100, self._poll)`. Worker threads put `("progress"|"done"|"error"|"cancelled", payload)` tuples into the queue — they never call widget methods directly.

## Validation Checks
The 9 checks live in `validator/checks.py`. Each returns a `CheckResult(status=Status.PASS|WARN|FAIL, ...)`.

| ID           | What it verifies |
|--------------|------------------|
| `schema`     | Required UMM-G fields are present |
| `temporal`   | BeginningDateTime ≤ EndingDateTime, not in future |
| `spatial`    | Coordinates in valid ranges; polygon closure |
| `daynight`   | DayNightFlag matches computed sun position (astral) |
| `url_health` | Download URLs exist and the first one responds with HTTP 2xx (live HEAD/GET probe via authenticated session) |
| `file_size`  | No zero-byte or suspiciously tiny files |
| `prod_date`  | ProductionDateTime is present, after BeginningDateTime, not in the future, and not the Unix epoch sentinel |
| `collection` | CollectionReference.ShortName matches selected collection |
| `duplicates` | No repeated concept-ids in the sample |

## Adding a New Check
1. Add a function `check_my_thing(granule) -> CheckResult` in `validator/checks.py`.
2. Register it in `CHECKS` dict in `validator/runner.py`: `"my_thing": ("My Thing Label", check_my_thing)`.
3. Add a toggle label in the `check_labels` dict inside `gui/config_screen.py`.
4. Add `"my_thing"` to `ALL_CHECK_IDS` in `validator/runner.py` (keeps order consistent).

## Known Limitations
- **Polar day/night**: `astral` raises for locations at extreme latitudes during midnight-sun or polar-night. The day/night check returns WARN (not FAIL) in these cases.
- **Missing SpatialExtent**: Some collections legitimately omit `SpatialExtent`. Spatial and day/night checks return WARN, not FAIL.
- **FutureWarnings**: `DataGranule.size()` / `.data_links()` emit FutureWarnings in earthaccess 0.18.x — suppressed globally at startup.
- **CMR rate limiting**: ~10 requests/second. The tool fetches a single page (count=50) and samples from it; unlikely to hit limits in normal use.
- **No file download**: All checks are metadata-only. File content is not read.

## Dependencies
Key packages (full list in `requirements.txt`):
- `earthaccess` — NASA CMR search and file access
- `customtkinter` — modern Tk widgets
- `astral` — sun position calculation for day/night consistency check
- `python-dotenv` — loads `.env` credentials
