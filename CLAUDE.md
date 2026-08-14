# CGvalidator — CLAUDE.md

## Purpose
GUI tool for spot-checking NASA granule collections. Samples N granules from a collection via the CMR API, runs automated metadata-only checks, and presents a PASS/WARN/FAIL report. All validation is against UMM-G JSON returned by the CMR search API — no files are downloaded.

## Run
```bash
source .venv/bin/activate
.venv/bin/python main.py
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
main.py                  — entry point; loads .env, suppresses FutureWarnings from earthaccess, launches GUI
gui/
  assets/                — static assets; currently contains login_screen_right_pane.webp (right-panel
                           background image loaded by login_screen.py via PIL)
  theme.py               — centralised palette: ACCENT (#00b4d8 cyan-steel), ACCENT_HOVER, SURFACE_0/1/2,
                           BORDER_SUBTLE/STRONG, TEXT_PRIMARY/MUTED/DISABLED/STATUS, STATUS_PASS/PASS_HVR/
                           WARN/FAIL/FAIL_HVR, LINK/LINK_HOVER, THUMB_MISSING, SCROLLBAR_BTN/HVR; FONT_*
                           tuples: TITLE/H1/H2/H3/H4/SUBHEAD/BODY/BODY_BOLD/SMALL/TINY/CAPTION/MONO/
                           MONO_SMALL; setup_ttk_style() applies dark Treeview + Vertical.TScrollbar styles;
                           all screens import from here — no inline hex strings anywhere else
  theme.json             — CTk custom color theme; accent #00b4d8 replaces CTk default blue; loaded by
                           absolute path via os.path.join(__file__, "theme.json") in app.py
  app.py                 — ValidatorApp (CTk/Tk root); title "GraVal"; 1600x900 window, minsize 800x560;
                           loads theme.json by path supporting both normal execution
                           (os.path.join(__file__, "theme.json")) and PyInstaller frozen builds
                           (sys._MEIPASS + "gui/theme.json"); dark mode; shared state (auth,
                           selected_collection, last_validation_run); drives screen transitions via
                           show_login/show_home/show_search/show_config/show_results()
  login_screen.py        — split-pane auth screen: left panel = form ("Sign in" heading, "use your
                           Earthdata login" subtitle, Username entry, Password entry, status label,
                           progress bar, primary "Login" button (uses entered credentials), secondary
                           "Sign in with .env" button, footer with "GraVal" branding and privacy note);
                           right panel = CTkLabel (CTk) or tk.Canvas (plain Tk) displaying a
                           cover-cropped version of gui/assets/login_screen_right_pane.webp, resized on
                           <Configure> via PIL ImageOps.fit with 80ms debounce; background thread for
                           earthaccess.login(); on success → app.show_home(); env vars injected/restored
                           when manual credentials are used
  home_screen.py         — card-based dashboard (tool bag); shown after login, before search; header bar
                           with "GraVal" title + "Sign Out" button; 3-column CTkScrollableFrame grid of
                           tool cards; currently one card: "Granule Validator" → app.show_search(); Sign
                           Out clears auth/selected_collection/last_validation_run → show_login()
  search_screen.py       — collection search; calls theme.setup_ttk_style(); populates ttk.Treeview
                           (short_name, version, concept_id, provider); DAAC filter (NSIDC, GHRCDAAC,
                           PODAAC, ASF, ORNLDAAC, LPDAAC, GES_DISC, OBDAAC, SEDAC, LAADS, ASDC)
                           searches both on-prem and cloud providers to avoid missing cloud collections
                           (e.g. EMIT via LPCLOUD); Back button → app.show_home()
  config_screen.py       — sample size slider (1–50), optional date range (YYYY-MM-DD), check toggles
                           (one per check_id from ALL_CHECK_IDS); Back button → app.show_search();
                           passes config dict to show_results()
  results_screen.py      — runs ValidationRunner in background; progress bar with Cancel button (→
                           show_config()); 100ms polling loop via self.after(100, self._poll); calls
                           theme.setup_ttk_style(); split-pane detail view with collapsible lists;
                           clickable "View in Earthdata Search" link; browse image thumbnail with per-URL
                           cache and SSL fallback; CSV export; unwraps raw CMR JSON error bodies in
                           _on_error(); "← New Validation" button → show_config()
validator/
  checks.py              — 9 check functions + helpers (_get_centroid, _is_epoch_placeholder,
                           _human_size, _EPOCH_PLACEHOLDERS frozenset); each returns
                           CheckResult(check_name, status, message, details)
  runner.py              — ValidationRunner (background thread + queue.Queue); GranuleReport;
                           ValidationRun; CHECKS registry; ALL_CHECK_IDS order list; duplicates check
                           is whole-sample (handled outside the per-granule loop)
  report.py              — export_csv(), default_report_path() — filename encodes granule count and
                           pass/warn/fail summary, defaults to ~/Desktop/
```

## Threading Rule
**Never touch a Tkinter/CTk widget from a non-main thread.**
Worker threads put `("progress"|"done"|"error"|"cancelled", payload)` tuples into `runner.result_queue`. The results screen polls every 100ms via `self.after(100, self._poll)`.

## CTk / Tk Compatibility
All screens support both `customtkinter` (preferred) and plain `tkinter` via `_HAS_CTK` guards. Widget state calls that produce identical results in both libraries are written once without branching. All colour values come from `gui/theme.py` — never use inline hex strings.

## Navigation Flow
```
LoginScreen → HomeScreen → SearchScreen → ConfigScreen → ResultsScreen
                  ↑              ↑ (Back)       ↑ (Back)
              (Sign Out)     HomeScreen      SearchScreen
```
- Login success → `show_home()`
- HomeScreen Sign Out → clears `auth`/`selected_collection`/`last_validation_run` → `show_login()`
- SearchScreen Back → `show_home()` (not `show_login()`)
- ConfigScreen Back → `show_search()`
- ResultsScreen Cancel or "← New Validation" → `show_config()`

## Validation Checks (`validator/checks.py`)

| check_id   | What it verifies |
|------------|-----------------|
| `schema`     | Required UMM-G fields present (GranuleUR, TemporalExtent, DataGranule, RelatedUrls); WARN if SpatialExtent absent |
| `temporal`   | BeginningDateTime ≤ EndingDateTime; neither is a pipeline epoch/placeholder; neither is in the future |
| `spatial`    | Coordinates in valid ranges; polygon closure; W < E (WARN on antimeridian crossing) |
| `daynight`   | DayNightFlag matches computed sun position via astral |
| `url_health` | GET DATA URL present; no http:// URLs; descriptions present; first URL responds HTTP 2xx; S3 URLs accepted on presence alone |
| `file_size`  | No zero-byte or suspiciously tiny (<1 KB) files in ArchiveAndDistributionInformation |
| `prod_date`  | ProductionDateTime present, not an epoch/placeholder, after BeginningDateTime, not future |
| `collection` | CollectionReference.ShortName matches selected collection; falls back to EntryTitle comparison when ShortName absent |
| `duplicates` | No repeated concept-ids across the sample (whole-sample check, not per-granule) |

### Epoch/Placeholder Detection
`_is_epoch_placeholder(dt_str)` calls `.strip().lower()` on the input and matches against `_EPOCH_PLACEHOLDERS` — a frozenset of 5 lowercase sentinel strings: `1970-01-01t00:00:00z`, `1970-01-01t00:00:00`, `1970-01-01`, `0001-01-01t00:00:00z`, `0001-01-01`. Shared by `check_temporal_validity` and `check_production_date_sanity`.

### URL Health Quality Issues
`check_url_health` collects static quality issues (no GET DATA URL, http:// URLs, missing descriptions) before the live HTTP probe. Issues are surfaced in `details["quality_issues"]` on all return paths. A clean probe that has quality issues returns WARN, not PASS. S3 (`s3://`) URLs skip the HTTP probe — presence alone is sufficient; quality issues still produce WARN. On SSLError, the probe retries without SSL verification to distinguish a reachable file from a real cert failure; a successful retry adds `ssl_note` to details but still returns PASS (NASA CDN self-signed cert quirk). HTTP 401/403 → WARN (access restricted); HTTP 404 → FAIL; other unexpected codes → WARN.

### Known Limitations
- **Polar day/night**: `astral` raises at extreme latitudes → day/night check returns WARN
- **Missing SpatialExtent**: Legitimately absent on some collections → spatial/daynight return WARN
- **FutureWarnings**: `DataGranule(...)` and `granule.data_links()` emit FutureWarnings in earthaccess 0.18.x — suppressed globally at startup and locally inside `check_url_health`
- **CMR rate limiting**: ~10 req/s; tool fetches `page_size=1` with random `page_num` offsets to spread sampling across full collection history (max depth 1,000,000)
- **No file download**: All checks are metadata-only against UMM-G JSON

## Runner Sampling Strategy (`validator/runner.py`)
One CMR hit-count query (`query.hits()`), then one direct `GET /search/granules.umm_json` request per granule with `page_size=1` at a random `page_num` in `[1, min(total_count, 1_000_000)]`. Uses `earthaccess.get_requests_https_session()`. Spreads samples across the full collection rather than clustering on the most recent page. Wraps each raw CMR item as `DataGranule(item, cloud_hosted=<bool>)` with FutureWarnings suppressed.

## Adding a New Check
1. Add `check_my_thing(granule) -> CheckResult` in `validator/checks.py`
2. Add `"my_thing": ("My Thing Label", check_my_thing)` to `CHECKS` in `validator/runner.py`
3. Add `"my_thing"` to `ALL_CHECK_IDS` in `validator/runner.py` (order controls display in config screen)
4. Add a label string to `_CHECK_LABELS` dict in `gui/config_screen.py`

## Adding a New Home Screen Tool Card
1. Append `(title, description, "show_method_name")` to `_TOOLS` in `gui/home_screen.py`
2. Add the corresponding `show_method_name()` navigation method to `gui/app.py`
3. Create the new screen module under `gui/`

## Future Work
- **Platform/Instrument collection cross-check**: compare granule `Platforms`/`Instruments` against parent collection UMM-C. Deferred until a download-capable validator version exists — UMM-G search responses often omit `Platforms`, making the check low-signal without a sidecar.
- **Additional tool cards on HomeScreen**: `_TOOLS` list in `home_screen.py` is intentionally extensible (3-column grid); future tools (e.g. collection-level UMM-C linting, file download integrity checks) plug in by appending to that list and adding a navigation method to `app.py`.

## Dependencies
Key packages (`requirements.txt`):
- `earthaccess` — NASA CMR search and authenticated sessions
- `customtkinter` — modern Tk widgets
- `astral` — sun position for day/night check
- `python-dotenv` — loads `.env` credentials
- `Pillow` — browse image thumbnails in detail pane

# Project Rules & Style Guide

## Python Coding Standards
- **Imports**: All imports must reside at the absolute top of the file. Group logically: 1. Standard Library, 2. Third-Party Libraries, 3. Local Application Modules. Never write inline or mid-file imports.
- **Style Compliance**: Strictly adhere to PEP 8. Maintain 4-space indentation, wrap lines at 79 characters, and use 2 blank lines between top-level functions/classes.
- **Execution Guard**: Keep operational script logic inside the `if __name__ == "__main__":` block.

## Documentation & Comments
- **Timelessness**: Write comments as if a stranger is reading the code a year from now. Do not reference our conversation history, previous bugs, edits, or debugging context.
- **Docstrings**: Use clear, descriptive triple-quote `"""docstrings"""` for modules, classes, and public functions to explain purpose.
- **Inline Comments**: Keep inline comments brief and focused entirely on *why* complex code is written, not *what* basic code is doing.
