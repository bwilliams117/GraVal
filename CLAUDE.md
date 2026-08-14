# CGvalidator — CLAUDE.md

## Purpose
GUI tool with two instruments: **Granule Validator** spots-checks NASA granule collections by sampling N granules via the CMR API, running automated metadata-only checks, and presenting a PASS/WARN/FAIL report (UMM-G JSON only — no downloads). **Granule Inspector** is a pre-ingest, file-level validator for LP DAAC curators: downloads science files and inspects internal structure (HDF5, COG, HDF4, NetCDF) in addition to full UMM metadata checks.

## Run
```bash
source .venv/bin/activate
.venv/bin/python main.py
```

## Auth
Credentials are entered directly in the GUI login form. There is no `.env` file or environment-variable injection.
- **OPS**: Username/password submitted to `earthaccess.login(strategy="interactive")`; result stored in `app.auth`, `app.uat_token=None`.
- **UAT**: Username/password submitted via Basic auth to `uat.urs.earthdata.nasa.gov/api/users/tokens` (reuse existing token) or POST `/api/users/token` (create new). earthaccess is not used for UAT sessions; `app.uat_token` holds the Bearer string and `app.auth=None`.

## Architecture

```
main.py                       — entry point; suppresses FutureWarnings from earthaccess,
                                 launches GUI
gui/
  assets/                     — static assets; currently contains login_screen_right_pane.webp
                                 (right-panel background image loaded by login_screen.py via PIL)
  theme.py                    — centralised palette: ACCENT (#78D68B green), ACCENT_HOVER (#5fc476),
                                 SURFACE_0 (#121212)/1 (#1c1c1c)/2 (#272727), BORDER_SUBTLE/STRONG,
                                 TEXT_PRIMARY/MUTED/DISABLED/STATUS, STATUS_PASS (#78D68B)/PASS_HVR/
                                 WARN (#f59e0b)/FAIL (#ef4444)/FAIL_HVR, LINK (#78D68B)/LINK_HOVER,
                                 THUMB_MISSING, SCROLLBAR_BTN/HVR; FONT_* tuples: TITLE/H1/H2/H3/H4/
                                 SUBHEAD/BODY/BODY_BOLD/SMALL/TINY/CAPTION/MONO/MONO_SMALL;
                                 setup_ttk_style() applies dark Treeview + Vertical.TScrollbar styles;
                                 place_env_badge(screen, env) places a floating pill badge (UAT=amber,
                                 OPS=green) top-right of any screen; all screens import from here —
                                 no inline hex strings anywhere else
  theme.json                  — CTk custom color theme; accent #78D68B (green) replaces CTk default
                                 blue; loaded by absolute path in app.py
  app.py                      — ValidatorApp (CTk/Tk root); title "GraVal"; 1600x900, minsize 800x560;
                                 loads theme.json supporting both normal execution and PyInstaller
                                 frozen builds (sys._MEIPASS); dark mode; shared state: auth
                                 (earthaccess auth object for OPS, None for UAT), uat_token (Bearer
                                 token string for UAT, None for OPS), env ("UAT" or "OPS"),
                                 selected_collection, last_validation_run, _inspector_entry (bool —
                                 True when SearchScreen was entered from the Inspector flow);
                                 _replace_screen() destroys the current screen, packs the new one,
                                 and calls theme.place_env_badge (skipped for login); navigation
                                 methods: show_login / show_home / show_search / show_config /
                                 show_results(config) / show_inspector_search /
                                 show_inspector_config / show_inspector_results(check_config)
  login_screen.py             — split-pane auth screen; left panel: "Sign in" heading, "use your
                                 Earthdata login" subtitle, UAT/OPS CTkSegmentedButton toggle
                                 (UAT=amber, OPS=green), Username entry, Password entry, status
                                 label, progress bar, "Login" button, footer with "GraVal" branding
                                 and privacy note; right panel: cover-cropped
                                 login_screen_right_pane.webp resized on <Configure> via PIL
                                 ImageOps.fit with 80ms debounce; background thread for auth;
                                 UAT path: Basic-auth to uat.urs.earthdata.nasa.gov → retrieves/
                                 creates Bearer token → app.uat_token, app.env="UAT", app.auth=None;
                                 OPS path: earthaccess.login(strategy="interactive") with entered
                                 credentials → app.auth, app.env="OPS", app.uat_token=None;
                                 on success → app.show_home()
  home_screen.py              — card-based dashboard shown after login; header "GraVal" + "Select a
                                 tool to get started"; 3-column CTkScrollableFrame grid; two tool
                                 cards: "Granule Validator" → app.show_search(), "Granule Inspector"
                                 → app.show_inspector_search(); footer "Sign Out" clears auth /
                                 uat_token / selected_collection / last_validation_run, resets
                                 env="UAT" and _inspector_entry=False → show_login()
  search_screen.py            — collection search; shared by both Granule Validator and Granule
                                 Inspector flows; calls theme.setup_ttk_style(); populates
                                 ttk.Treeview (short_name, version, concept_id, provider); DAAC
                                 filter list: NSIDC, GHRCDAAC, PODAAC, ASF, ORNLDAAC, LPDAAC,
                                 GES_DISC, OBDAAC, SEDAC, LAADS, ASDC; OPS: _search_ops() via
                                 earthaccess, searches both on-prem and cloud providers per DAAC to
                                 avoid missing cloud collections (e.g. EMIT via LPCLOUD); UAT:
                                 _search_uat() via direct requests to
                                 cmr.uat.earthdata.nasa.gov/search/collections.umm_json with Bearer
                                 token; _UAT_DAAC_PROVIDERS dict maps DAAC labels to UAT provider
                                 ID lists; on select: if _inspector_entry → clears flag →
                                 show_inspector_config(), else → show_config(); Back → show_home()
  config_screen.py            — sample size slider (1–50), optional date range (YYYY-MM-DD), check
                                 toggles (one per check_id from ALL_CHECK_IDS); bottom bar:
                                 "← Back to Search" → show_search(), "Home" → show_home(),
                                 "Run Validation" → show_results(); config dict passed to
                                 show_results() contains: sample_size, temporal, enabled_checks,
                                 env, uat_token, concept_id
  inspector_config_screen.py  — InspectorConfigScreen; FILE FORMAT selector (AUTO/HDF5/COG/HDF4/
                                 NetCDF); GRANULES slider (1–3 files to download and inspect);
                                 two-column CHECKS grid — left "UMM Metadata" group (schema,
                                 temporal, spatial, daynight, url_health, prod_date, collection,
                                 duplicates), right "File-Level" group: hdf5_sm (requires h5py),
                                 cog_compliance (rasterio; sub-option allow_nan_nodata for
                                 ECOSTRESS), hdf4_core (pyhdf), netcdf_struct (netCDF4), file_size,
                                 prod_readiness (UAT sessions only — scans for UAT endpoint strings
                                 that must be absent in OPS), coll_xref (platforms/instruments/
                                 format cross-check); unavailable checks shown greyed with install
                                 hint; DOWNLOAD LOCATION section shows read-only path
                                 ~/Documents/GraVal/downloads/{env}/{short_name}_v{version}/
                                 {concept_id}; bottom bar: "← Back to Search" →
                                 show_inspector_search(), "Home" → show_home(), "Run Inspection"
                                 → show_inspector_results(check_config)
  results_screen.py           — runs ValidationRunner in background; progress bar with Cancel →
                                 show_config(); 100ms polling loop via self.after(100, self._poll);
                                 calls theme.setup_ttk_style() and theme.place_env_badge() after
                                 done; split-pane: left Treeview (status symbol / granule_ur /
                                 pass-count), right vertical paned (browse thumbnail top, detail
                                 text bottom); collapsible list items in detail pane (▶/▼ toggle);
                                 clickable "View in Earthdata Search" link; per-URL thumbnail cache
                                 + SSL fallback; CSV export; unwraps raw CMR JSON error bodies in
                                 _on_error(); "← New Validation" → show_config()
  inspector_results_screen.py — InspectorResultsScreen; uses DeepValidationRunner from
                                 validator/deep_runner.py; per-granule download + inspect progress
                                 with state dots (waiting/starting/downloading/inspecting/done/
                                 failed); split-pane report view after completion; "Open Folder"
                                 button reveals the download directory (macOS/Windows/Linux); CSV
                                 export; "← New Inspection" → show_inspector_config()
validator/
  checks.py                   — 9 check functions + helpers (_get_beginning_datetime_str,
                                 _get_centroid, _is_epoch_placeholder, _human_size,
                                 _EPOCH_PLACEHOLDERS frozenset); each returns
                                 CheckResult(check_name, status, message, details)
  runner.py                   — ValidationRunner (background thread + queue.Queue); GranuleReport;
                                 ValidationRun; CHECKS registry; ALL_CHECK_IDS = list(CHECKS.keys());
                                 _CMR_HOST dict {"OPS": "cmr.earthdata.nasa.gov",
                                 "UAT": "cmr.uat.earthdata.nasa.gov"}; run_async() accepts env,
                                 uat_token, concept_id; UAT uses plain requests.Session + Bearer
                                 Authorization header; OPS uses earthaccess.get_requests_https_session();
                                 CMR search pinned to collection_concept_id when concept_id provided;
                                 duplicates check is whole-sample (outside the per-granule loop)
  deep_checks.py              — file-level check functions for the Granule Inspector: HDF5 standard
                                 metadata, COG compliance (tile/overview/CRS/NoData), HDF4 core
                                 metadata, NetCDF structure, file size accuracy, PROD readiness
                                 (UAT endpoint string scan), collection cross-check
                                 (platforms/instruments/format)
  deep_runner.py              — DeepValidationRunner (background thread + queue.Queue);
                                 DeepValidationRun; downloads granule science files then runs
                                 metadata checks (via validator/checks.py) + file-level checks
                                 (via validator/deep_checks.py)
  report.py                   — export_csv(), default_report_path() — filename encodes granule count
                                 and pass/warn/fail summary, defaults to ~/Desktop/
```

## Threading Rule
**Never touch a Tkinter/CTk widget from a non-main thread.**
Worker threads put `("progress"|"done"|"error"|"cancelled", payload)` tuples into `runner.result_queue`. The results screen polls every 100ms via `self.after(100, self._poll)`.

## CTk / Tk Compatibility
All screens support both `customtkinter` (preferred) and plain `tkinter` via `_HAS_CTK` guards. Widget state calls that produce identical results in both libraries are written once without branching. All colour values come from `gui/theme.py` — never use inline hex strings.

## Navigation Flow
```
LoginScreen → HomeScreen ─────────────────────────────────────────────────────┐
                  ↑              ↓ show_search()           ↓ show_inspector_search()
              (Sign Out)    SearchScreen ────────────── SearchScreen
                                 ↓ (select, !inspector)      ↓ (select, inspector)
                            ConfigScreen              InspectorConfigScreen
                                 ↓ (Run Validation)          ↓ (Run Inspection)
                            ResultsScreen             InspectorResultsScreen
```
- Login success → `show_home()`
- HomeScreen Sign Out → clears auth/uat_token/selected_collection/last_validation_run, resets env="UAT", _inspector_entry=False → `show_login()`
- SearchScreen Back → `show_home()` (not `show_login()`)
- ConfigScreen "← Back to Search" → `show_search()`;  "Home" → `show_home()`
- ResultsScreen Cancel → `show_config()`;  "← New Validation" → `show_config()`
- InspectorConfigScreen "← Back to Search" → `show_inspector_search()`;  "Home" → `show_home()`
- InspectorResultsScreen "← New Inspection" → `show_inspector_config()`

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
`check_url_health` collects static quality issues (no GET DATA URL, http:// URLs, missing descriptions) before the live HTTP probe. Issues are surfaced in `details["quality_issues"]` on all return paths. A clean probe that has quality issues returns WARN, not PASS. S3 (`s3://`) URLs skip the HTTP probe — presence alone is sufficient; quality issues still produce WARN. On SSLError, the probe retries without SSL verification to distinguish a reachable file from a real cert failure; a successful retry adds `ssl_note` to details but still returns PASS (NASA CDN self-signed cert quirk). HTTP 401/403 → WARN (access restricted); HTTP 404 → FAIL; other unexpected codes → WARN. In UAT sessions where earthaccess auth is unavailable, falls back to a plain `requests.Session` — protected URLs will return 401/403, which is handled gracefully.

### Known Limitations
- **Polar day/night**: `astral` raises at extreme latitudes → day/night check returns WARN
- **Missing SpatialExtent**: Legitimately absent on some collections → spatial/daynight return WARN
- **FutureWarnings**: `DataGranule(...)` and `granule.data_links()` emit FutureWarnings in earthaccess 0.18.x — suppressed globally at startup and locally inside `check_url_health`
- **CMR rate limiting**: ~10 req/s; tool fetches `page_size=1` with random `page_num` offsets to spread sampling across full collection history (max depth 1,000,000)
- **No file download**: All Granule Validator checks are metadata-only against UMM-G JSON

## Runner Sampling Strategy (`validator/runner.py`)
One CMR hit-count query (HEAD request, reads `CMR-Hits` header), then one direct `GET /search/granules.umm_json` request per granule with `page_size=1` at a random `page_num` in `[1, min(total_count, 1_000_000)]`. Spreads samples across the full collection rather than clustering on the most recent page. When `concept_id` is provided, queries are pinned via `collection_concept_id` parameter — the only reliable way to stay within the selected collection across OPS and UAT. UAT env uses a plain `requests.Session` with a Bearer Authorization header; OPS uses `earthaccess.get_requests_https_session()`. Wraps each raw CMR item as `DataGranule(item, cloud_hosted=<bool>)` with FutureWarnings suppressed.

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
- **Platform/Instrument collection cross-check in Granule Validator**: The `coll_xref` check (platforms/instruments/format) is implemented in the Granule Inspector (`validator/deep_checks.py`). It has NOT been added to `validator/checks.py` or `validator/runner.py` for the metadata-only Granule Validator — UMM-G search responses often omit `Platforms`, making the check low-signal without downloading the file.
- **Additional tool cards on HomeScreen**: `_TOOLS` list in `home_screen.py` is extensible (3-column grid); Granule Validator and Granule Inspector are currently wired up; future tools (e.g. collection-level UMM-C linting) plug in by appending to that list and adding a navigation method to `app.py`.

## Dependencies
Key packages (`requirements.txt`):
- `earthaccess` — NASA CMR search and authenticated sessions
- `customtkinter` — modern Tk widgets
- `astral` — sun position for day/night check
- `Pillow` — browse image thumbnails in detail pane
- `requests` — direct CMR HTTP calls (UAT env) and URL health probes
- `h5py` — HDF5 file inspection (Inspector; optional)
- `rasterio` — COG compliance checks (Inspector; optional)
- `netCDF4` — NetCDF structure checks (Inspector; optional)
- `pyhdf` — HDF4 core metadata checks (Inspector; optional)
- `numpy`, `xarray`, `dask` — scientific data handling for file-level checks
- `cartopy`, `matplotlib` — geospatial rendering (Inspector)

# Project Rules & Style Guide

## Python Coding Standards
- **Imports**: All imports must reside at the absolute top of the file. Group logically: 1. Standard Library, 2. Third-Party Libraries, 3. Local Application Modules. Never write inline or mid-file imports.
- **Style Compliance**: Strictly adhere to PEP 8. Maintain 4-space indentation, wrap lines at 79 characters, and use 2 blank lines between top-level functions/classes.
- **Execution Guard**: Keep operational script logic inside the `if __name__ == "__main__":` block.

## Documentation & Comments
- **Timelessness**: Write comments as if a stranger is reading the code a year from now. Do not reference our conversation history, previous bugs, edits, or debugging context.
- **Docstrings**: Use clear, descriptive triple-quote `"""docstrings"""` for modules, classes, and public functions to explain purpose.
- **Inline Comments**: Keep inline comments brief and focused entirely on *why* complex code is written, not *what* basic code is doing.
