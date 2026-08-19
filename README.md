<img width="1280" height="640" alt="gv_github_banner" src="https://github.com/user-attachments/assets/1040f3be-168a-4640-b2d9-046cb8ce9c18" />

# GraVal — NASA Granule Validation Tool

**Version 1.0.0**

GraVal is a desktop GUI for validating NASA Earthdata granule collections. It provides two instruments — a fast metadata spot-checker and a deep file-level inspector — accessible from a card-based home dashboard. Built with Python and customtkinter, GraVal supports both the OPS and UAT Earthdata environments.
<br><br>
[![GitHub Release](https://img.shields.io/badge/Click%20Here%20For-Latest%20Release-78D68B?style=for-the-badge)](https://github.com/bwilliams117/GraVal/releases)


---

https://github.com/user-attachments/assets/878f9099-e253-431b-80f1-7d4121a6ab85

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
<br>

[![GitHub Release](https://img.shields.io/badge/Latest%20Release-78D68B?style=for-the-badge)](https://github.com/bwilliams117/GraVal/releases)


| Platform | File | Notes |
|---|---|---|
| macOS | `GraVal-macOS.zip` | Extract → right-click → Open |
| Windows | `GraVal-Windows.zip` | Extract → run `GraVal.exe` |

> **macOS:** if blocked with "damaged" message, run `xattr -cr GraVal.app` in Terminal, then right-click → Open.  
> **Windows:** SmartScreen may warn on first run — click **More info** → **Run anyway**.

The app may take a few seconds to open on first launch while the bundled environment initializes.

---

## Requirements

- Python 3.11+
- **macOS (pyhdf):** HDF4 is no longer in Homebrew. Install via conda-forge: `conda install -c conda-forge pyhdf`, then skip it when running pip: `grep -iv "pyhdf" requirements.txt | pip install -r /dev/stdin`
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

- The day/night check returns WARN at extreme polar latitudes where sun-position calculation is unreliable.
- Collections where `SpatialExtent` is legitimately absent produce WARN on spatial and day/night checks.
- CMR rate limiting (~10 req/s) means larger sample sizes take proportionally longer to complete.

---

## Authors and Contributors

| [<img src="https://github.com/bwilliams117.png" width="100"/>](https://github.com/bwilliams117) | [<img src="https://github.com/dnilsen13.png" width="100"/>](https://github.com/dnilsen13) | [<img src="https://github.com/GeoKetch.png" width="100"/>](https://github.com/GeoKetch) | [<img src="https://github.com/rquenzer-usgs.png" width="100"/>](https://github.com/rquenzer-usgs) |
| :---: | :---: | :---: | :---: |
| **Bentley Williams** <br> <sub>Author and Developer</sub> | **David Nilsen** <br> <sub>Developer</sub> | **Alexander Ketchpaw** <br> <sub>Code Reviewer</sub> | **Robert Quenzer** <br/> <sub>Project Manager and Code Reviewer</sub> |
