# GraVal — NASA Granule Validation Tool

**Version 1.0.0**

GraVal is a desktop GUI for validating NASA Earthdata granule collections. It provides two instruments — a fast metadata spot-checker and a deep file-level inspector — accessible from a card-based home dashboard. Built with Python and customtkinter, GraVal supports both the OPS and UAT Earthdata environments.

---

## Tools

### Granule Validator

Metadata-only spot-check tool for any NASA collection. Search by DAAC and keyword, choose a collection, configure a sample size (1–50 granules) and optional date range, then run. Results are presented as a PASS / WARN / FAIL report per granule with collapsible per-check detail, browse thumbnails, and a direct link to Earthdata Search. No files are downloaded.

| Check | What it verifies |
|---|---|
| Schema Completeness | Required UMM-G fields present (GranuleUR, TemporalExtent, DataGranule, RelatedUrls); WARN if SpatialExtent absent |
| Temporal Validity | BeginningDateTime ≤ EndingDateTime; neither is an epoch/placeholder; neither is in the future |
| Spatial Validity | Coordinates within valid ranges; polygon closure; WARN on antimeridian crossing |
| Day/Night Consistency | DayNightFlag matches computed sun elevation at granule centroid via `astral` |
| URL Health | GET DATA URL present; no `http://` URLs; descriptions present; first URL probed for a 2xx response; S3 URLs accepted on presence alone |
| File Size Sanity | No zero-byte or suspiciously small (<1 KB) files in ArchiveAndDistributionInformation |
| Production Date Sanity | ProductionDateTime present, not a placeholder, after BeginningDateTime, not in the future |
| Collection Reference | CollectionReference.ShortName matches the selected collection |
| Duplicate Detection | No repeated concept-ids across the sample |

Results export to CSV on `~/Desktop/`.

---

### Granule Inspector

File-level pre-ingest validator for LP DAAC curators. Uses the same collection-search screen, then adds a format selector (AUTO / HDF5 / COG / HDF4 / NetCDF), a granules slider (1–3 files), and a two-column check grid separating UMM metadata checks from file-level checks. Files are downloaded to `~/Documents/GraVal/downloads/{env}/{collection}/{concept_id}/` and inspected in place.

**UMM Metadata checks:** same nine checks as the Granule Validator.

**File-Level checks:**

| Check | Requires | What it inspects |
|---|---|---|
| HDF5 Standard Metadata | `h5py` | Top-level structure and StandardMetadata group attributes, dataset dtypes, and fill values |
| COG Compliance | `rasterio` | Tiling (256/512/1024 px blocks), overviews (≥2 for files >512 px), CRS resolvability, NoData presence |
| HDF4 Core Metadata | `pyhdf` | CoreMetadata.0 ODL block: ShortName, VersionID, LocalGranuleID, temporal extents; dataset inventory |
| NetCDF Structure | `netCDF4` | Global attributes, dimensions, variables with shapes and fill values |
| File Size Accuracy | — | Actual disk size vs. declared SizeMBDataGranule; WARN if >±20% |
| PROD Readiness | — | Scans sidecars for UAT endpoint strings that must be absent in OPS granules |
| Collection Cross-Check | — | Fetches collection UMM-C from CMR; compares granule platforms, instruments, and DataFormat |

Checks that require an optional library are shown greyed in the config screen with the install command when the library is not available. Results export to CSV.

---

## Project Structure

```
main.py          — entry point; launches the GUI
gui/             — all screens, theming, and assets
  theme.py       — centralised color palette and font definitions
  app.py         — root window and screen navigation
  *_screen.py    — one module per screen (login, home, search, config, results,
                   inspector_config, inspector_results)
  assets/        — icons and background images
validator/
  checks.py      — the 9 UMM metadata check functions
  runner.py      — background thread that samples CMR and runs checks.py
  deep_checks.py — file-level check functions (HDF5, COG, HDF4, NetCDF, etc.)
  deep_runner.py — background thread that downloads files and runs deep_checks.py
  report.py      — CSV export helpers
```

The `gui/` layer is pure presentation — it reads results from queues and never touches validation logic directly. The `validator/` layer has no GUI imports and can be used independently.

---

## Pre-built Releases

Pre-built executables for Windows and macOS are available from the GitHub Releases page.

**Windows (.exe):** Windows may show a SmartScreen warning the first time you run the app. Click **More info** → **Run anyway** to proceed.

**macOS (.app):** macOS may block the app on first launch because it is not notarized. Right-click (or Control-click) the app, select **Open**, then confirm in the dialog that appears.

The app may take a few seconds to open on first launch while the bundled environment initializes.

---

## Requirements

- Python 3.11+
- **macOS (pyhdf):** `brew install hdf4` before `pip install pyhdf`
- **rasterio** may require system GDAL libraries on some platforms

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Opens a 1600×900 dark-mode window. Minimum window size is 800×560.

---

## Authentication

Enter your [NASA Earthdata](https://urs.earthdata.nasa.gov) username and password directly in the login form. Use the OPS / UAT toggle to select your target environment. No configuration files are needed — your credentials are never stored.

- **OPS:** authenticates via `earthaccess` using the credentials you enter.
- **UAT:** authenticates directly against `uat.urs.earthdata.nasa.gov` and retrieves or creates a Bearer token for the session.

---

## Known Limitations

- The Granule Validator is metadata-only — no science files are downloaded.
- The day/night check returns WARN at extreme polar latitudes where sun-position calculation is unreliable.
- Collections where `SpatialExtent` is legitimately absent produce WARN on spatial and day/night checks.
- CMR rate limiting (~10 req/s) means larger sample sizes take proportionally longer to complete.
