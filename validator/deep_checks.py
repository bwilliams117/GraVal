"""File-level validation checks for the Granule Inspector.

Each function accepts one or more local file paths and returns a CheckResult
or list[CheckResult].  All optional library imports are guarded at the top so
the module loads cleanly even when a library is absent; the affected function
then returns a WARN result explaining what to install.
"""

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from .checks import CheckResult, Status

try:
    import h5py as _h5py
    _HAS_H5PY = True
except ImportError:
    _HAS_H5PY = False

try:
    import rasterio as _rasterio
    _HAS_RASTERIO = True
except ImportError:
    _HAS_RASTERIO = False

try:
    import netCDF4 as _netCDF4
    _HAS_NETCDF4 = True
except ImportError:
    _HAS_NETCDF4 = False

try:
    from pyhdf.SD import SD as _SD, SDC as _SDC
    _HAS_PYHDF = True
except ImportError:
    _HAS_PYHDF = False

# CMR hosts — used by collection cross-reference check.
_CMR_HOST = {
    "OPS": "cmr.earthdata.nasa.gov",
    "UAT": "cmr.uat.earthdata.nasa.gov",
}

# Sentinel values found in fill-value searches for NoData detection.
_COMMON_FILL_VALUES = {-9999, 0, -28672, 255, 65535}

# COG: valid square tile sizes.
_VALID_BLOCK_SIZES = (256, 512, 1024)

# COG: files larger than this (pixels in either dimension) need >= 2 overview levels.
_MIN_OVR_SIZE = 512

# HDF4 data-type map (numeric type code → dtype string).
_HDF4_TYPE = {
    3: "uint8", 4: "int8", 5: "float32", 6: "float64",
    20: "int8", 21: "uint8", 22: "int16", 23: "uint16",
    24: "int32", 25: "uint32",
}

# ODL metadata keys to extract from CoreMetadata/ArchiveMetadata blocks.
_HDF4_REQUIRED_CORE = {
    "ShortName", "VersionID", "LocalGranuleID",
    "BeginningDateTime", "EndingDateTime",
}

# UAT-environment string markers used by the PROD readiness check.
_UAT_MARKERS = [
    "lp-uat-protected",
    ".uat.earthdata",
    "uat.earthdata.nasa.gov",
    "LPCLOUDUAT",
    "lpdaac-uat",
]


# ── helper functions ──────────────────────────────────────────────────────────

def _h5_str(val) -> str:
    """Decode an HDF5 attribute value to a plain string."""
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace").strip()
    try:
        import numpy as np
        if isinstance(val, np.ndarray):
            if val.size == 0:
                return ""
            if val.size == 1:
                inner = val.flat[0]
                if isinstance(inner, bytes):
                    return inner.decode("utf-8", errors="replace").strip()
                return str(inner)
            return str(val.tolist())
        if hasattr(val, "item"):
            return str(val.item())
    except ImportError:
        pass
    return str(val).strip()


def _odl_field(text: str, *field_names: str) -> str:
    """Return the first ODL field value matching any of *field_names*."""
    for field in field_names:
        m = re.search(
            rf"OBJECT\s*=\s*{re.escape(field)}\b.*?VALUE\s*=\s*\"?([^\n\"]+)\"?",
            text, re.DOTALL | re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
    return ""


def _odl_datetime(text: str, date_fields: tuple, time_fields: tuple) -> str:
    """Combine separate ODL date + time fields into a single ISO datetime string."""
    date_val = _odl_field(text, *date_fields)
    time_val = _odl_field(text, *time_fields)
    if date_val and time_val:
        return f"{date_val}T{time_val}"
    return date_val or ""


# ── HDF5 ──────────────────────────────────────────────────────────────────────

def check_hdf5_standard_metadata(
    path: Path,
    sm_path: str | None = None,
    required: list[str] | None = None,
    expected: dict | None = None,
    dataset_specs: dict | None = None,
) -> list[CheckResult]:
    """Inspect HDF5 file structure; optionally validate a StandardMetadata group.

    When *sm_path* is provided, checks that all keys in *required* are present
    and that keys in *expected* have the correct values.  *dataset_specs* maps
    dataset short-names to ``(dtype_kind, min_val, max_val, fill_value)`` tuples.
    """
    name = "HDF5 Standard Metadata"
    if not _HAS_H5PY:
        return [CheckResult(
            name, Status.WARN,
            "h5py not installed — run: pip install h5py",
        )]

    required = required or []
    expected = expected or {}
    dataset_specs = dataset_specs or {}
    results: list[CheckResult] = []

    try:
        with _h5py.File(path, "r") as hf:
            if sm_path:
                if sm_path not in hf:
                    results.append(CheckResult(
                        name, Status.FAIL,
                        f"StandardMetadata group not found at {sm_path}",
                        {"path": sm_path, "file": path.name},
                    ))
                    return results

                sm_grp = hf[sm_path]
                missing = [k for k in required if k not in sm_grp]
                wrong: dict[str, tuple] = {}
                for k, exp_val in expected.items():
                    if k in sm_grp:
                        actual = _h5_str(sm_grp[k][()])
                        if actual != str(exp_val):
                            wrong[k] = (actual, str(exp_val))

                status = Status.PASS
                msg = f"StandardMetadata at {sm_path}: {len(sm_grp)} attrs"
                details: dict = {}
                if missing:
                    status = Status.FAIL
                    details["missing_attrs"] = missing
                if wrong:
                    status = Status.WARN if status == Status.PASS else status
                    details["wrong_values"] = [
                        f"{k}: found '{v[0]}' expected '{v[1]}'"
                        for k, v in wrong.items()
                    ]
                if missing or wrong:
                    msg = (
                        f"StandardMetadata issues: "
                        f"{len(missing)} missing, {len(wrong)} wrong value(s)"
                    )
                results.append(CheckResult(name, status, msg, details))

            else:
                # No SM path — just report top-level structure.
                top_items = []
                for item_name, item in hf.items():
                    if isinstance(item, _h5py.Group):
                        kind = "Group"
                    elif isinstance(item, _h5py.Datatype):
                        kind = "Datatype"
                    else:
                        kind = f"Dataset {item.shape} {item.dtype}"
                    top_items.append(f"{item_name}: {kind}")
                results.append(CheckResult(
                    name, Status.PASS,
                    f"{path.name}: {len(top_items)} top-level item(s) — "
                    "set HDF5_SM_PATH for attribute checks",
                    {"top_level_items": top_items[:30]},
                ))

            # Dataset specification checks.
            if dataset_specs:
                ds_issues: list[str] = []
                found_ds: set[str] = set()

                def _visit(ds_name, obj):
                    if not isinstance(obj, _h5py.Dataset):
                        return
                    short = ds_name.split("/")[-1]
                    if short not in dataset_specs:
                        return
                    found_ds.add(short)
                    exp_kind, _, _, exp_fill = dataset_specs[short]
                    if obj.dtype.kind != exp_kind:
                        ds_issues.append(
                            f"{short}: dtype kind '{obj.dtype.kind}' "
                            f"!= expected '{exp_kind}'"
                        )
                    fv = obj.attrs.get("_FillValue")
                    if fv is not None and exp_fill is not None:
                        fv_val = fv.item() if hasattr(fv, "item") else float(fv)
                        if fv_val != exp_fill:
                            ds_issues.append(
                                f"{short}: _FillValue={fv_val} "
                                f"!= expected {exp_fill}"
                            )
                    elif fv is None and exp_fill is not None:
                        ds_issues.append(
                            f"{short}: _FillValue missing (expected {exp_fill})"
                        )

                hf.visititems(_visit)

                for ds in sorted(set(dataset_specs.keys()) - found_ds):
                    ds_issues.append(f"{ds}: dataset not found in file")

                ds_status = Status.FAIL if ds_issues else Status.PASS
                ds_msg = (
                    f"Dataset specs: {len(ds_issues)} issue(s)"
                    if ds_issues
                    else f"Dataset specs: {len(dataset_specs)} check(s) passed"
                )
                ds_details = {"dataset_issues": ds_issues} if ds_issues else {}
                results.append(CheckResult("HDF5 Dataset Specs", ds_status, ds_msg, ds_details))

    except Exception as exc:
        results.append(CheckResult(
            name, Status.FAIL,
            f"Could not open HDF5 file: {exc}",
            {"file": path.name},
        ))

    return results


# ── HDF4 ──────────────────────────────────────────────────────────────────────

def check_hdf4_core_metadata(path: Path) -> CheckResult:
    """Parse HDF4/MODIS CoreMetadata and ArchiveMetadata ODL groups."""
    name = "HDF4 Core Metadata"
    if not _HAS_PYHDF:
        return CheckResult(
            name, Status.WARN,
            "pyhdf not installed — run: brew install hdf4 && pip install pyhdf",
        )

    try:
        hdf = _SD(str(path), _SDC.READ)
    except Exception as exc:
        return CheckResult(
            name, Status.FAIL,
            f"Could not open HDF4 file: {exc}",
            {"file": path.name},
        )

    try:
        g_attrs = hdf.attributes()
        core_text = str(g_attrs.get("CoreMetadata.0", ""))
        archive_text = str(g_attrs.get("ArchiveMetadata.0", ""))

        if not core_text:
            return CheckResult(
                name, Status.WARN,
                "CoreMetadata.0 attribute not found",
                {"global_attrs_found": sorted(g_attrs.keys())[:20]},
            )

        beg_dt = (
            _odl_field(core_text, "BeginningDateTime")
            or _odl_datetime(
                core_text,
                ("RangeBeginningDate", "RANGEBEGINNINGDATE"),
                ("RangeBeginningTime", "RANGEBEGINNINGTIME"),
            )
        )
        end_dt = (
            _odl_field(core_text, "EndingDateTime")
            or _odl_datetime(
                core_text,
                ("RangeEndingDate", "RANGEENDINGDATE"),
                ("RangeEndingTime", "RANGEENDINGTIME"),
            )
        )

        def _bbox(field: str) -> str:
            return (
                _odl_field(core_text, field, field.upper())
                or _odl_field(archive_text, field, field.upper())
            )

        cm_vals = {
            "ShortName": _odl_field(core_text, "ShortName", "SHORTNAME"),
            "VersionID": _odl_field(core_text, "VersionID", "VERSIONID"),
            "LocalGranuleID": _odl_field(core_text, "LocalGranuleID", "LOCALGRANULEID"),
            "BeginningDateTime": beg_dt,
            "EndingDateTime": end_dt,
            "NorthBoundingCoordinate": _bbox("NorthBoundingCoordinate"),
            "SouthBoundingCoordinate": _bbox("SouthBoundingCoordinate"),
            "EastBoundingCoordinate": _bbox("EastBoundingCoordinate"),
            "WestBoundingCoordinate": _bbox("WestBoundingCoordinate"),
            "DayNightFlag": _odl_field(core_text, "DayNightFlag", "DAYNIGHTFLAG"),
            "ProductionDateTime": _odl_field(
                core_text, "ProductionDateTime", "PRODUCTIONDATETIME"
            ),
        }

        missing = [k for k in _HDF4_REQUIRED_CORE if not cm_vals.get(k)]
        status = Status.FAIL if missing else Status.PASS
        msg = (
            f"CoreMetadata: {len(missing)} required field(s) missing"
            if missing
            else "CoreMetadata: all required fields present"
        )
        details: dict = {k: v for k, v in cm_vals.items() if v}
        if missing:
            details["missing_required"] = missing

        # Dataset inventory summary.
        ds_info = hdf.datasets()
        details["dataset_count"] = len(ds_info)
        details["datasets"] = [
            f"{n}: shape={info[1]} dtype={_HDF4_TYPE.get(info[2], f'type{info[2]}')}"
            for n, info in sorted(ds_info.items())
        ][:30]

        return CheckResult(name, status, msg, details)

    except Exception as exc:
        return CheckResult(
            name, Status.FAIL,
            f"Error reading HDF4 metadata: {exc}",
            {"file": path.name},
        )
    finally:
        try:
            hdf.end()
        except Exception:
            pass


# ── NetCDF ────────────────────────────────────────────────────────────────────

def check_netcdf_structure(path: Path) -> CheckResult:
    """List global attributes and variables in a NetCDF3/4 file."""
    name = "NetCDF Structure"

    # Try h5py first for NetCDF4 (HDF5-based) files.
    if _HAS_H5PY:
        try:
            with _h5py.File(path, "r") as hf:
                g_attrs = {k: _h5_str(v) for k, v in hf.attrs.items()}
                variables = []
                def _list(n, obj):
                    if isinstance(obj, _h5py.Dataset):
                        variables.append(
                            f"{n}: shape={obj.shape} dtype={obj.dtype}"
                        )
                hf.visititems(_list)
                return CheckResult(
                    name, Status.PASS,
                    f"NetCDF4 (HDF5): {len(g_attrs)} global attrs, "
                    f"{len(variables)} variable(s)",
                    {
                        "global_attributes": [f"{k}: {v[:80]}" for k, v in g_attrs.items()],
                        "variables": variables[:50],
                    },
                )
        except Exception:
            pass  # fall through to netCDF4 library path

    if not _HAS_NETCDF4:
        return CheckResult(
            name, Status.WARN,
            "netCDF4 not installed — run: pip install netCDF4",
        )

    try:
        ds = _netCDF4.Dataset(str(path), "r")
    except Exception as exc:
        return CheckResult(
            name, Status.FAIL,
            f"Could not open NetCDF file: {exc}",
            {"file": path.name},
        )

    try:
        g_attrs = {k: str(getattr(ds, k, ""))[:80] for k in ds.ncattrs()}
        dims = {n: len(d) for n, d in ds.dimensions.items()}
        variables = []
        for var_name, var in ds.variables.items():
            fill = getattr(var, "_FillValue", "(none)")
            variables.append(
                f"{var_name}: shape={var.shape} dtype={var.dtype} fill={fill}"
            )
        return CheckResult(
            name, Status.PASS,
            f"NetCDF3: {len(g_attrs)} global attrs, "
            f"{len(dims)} dimension(s), {len(variables)} variable(s)",
            {
                "global_attributes": [f"{k}: {v}" for k, v in g_attrs.items()],
                "dimensions": [f"{k}: {v}" for k, v in dims.items()],
                "variables": variables[:50],
            },
        )
    except Exception as exc:
        return CheckResult(
            name, Status.FAIL,
            f"Error reading NetCDF structure: {exc}",
            {"file": path.name},
        )
    finally:
        try:
            ds.close()
        except Exception:
            pass


# ── COG ───────────────────────────────────────────────────────────────────────

def check_cog_tiling(path: Path) -> CheckResult:
    """Verify that a GeoTIFF uses square power-of-two block tiles (256/512/1024px)."""
    name = "COG Tiling"
    if not _HAS_RASTERIO:
        return CheckResult(
            name, Status.WARN,
            "rasterio not installed — run: pip install rasterio",
        )
    try:
        with _rasterio.open(path) as src:
            block_shapes = list(src.block_shapes)
            if not block_shapes:
                return CheckResult(
                    name, Status.FAIL,
                    "No block shapes found — file may have no bands",
                    {"file": path.name},
                )
            bh, bw = block_shapes[0]
            is_tiled = bh == bw and bh in _VALID_BLOCK_SIZES
            if is_tiled:
                return CheckResult(
                    name, Status.PASS,
                    f"Tiled: {bh}x{bw} px",
                    {"block_size": bh, "all_block_shapes": str(block_shapes[:5])},
                )
            return CheckResult(
                name, Status.FAIL,
                f"Not tiled with valid square blocks. blocks={block_shapes[:3]}",
                {
                    "found_blocks": str(block_shapes[:5]),
                    "expected": f"square tiles of {_VALID_BLOCK_SIZES}",
                    "fix": "gdal_translate -of COG -co BLOCKSIZE=512 ...",
                },
            )
    except Exception as exc:
        return CheckResult(name, Status.FAIL, f"Could not open file: {exc}")


def check_cog_overviews(path: Path) -> CheckResult:
    """Verify that files larger than 512px have at least 2 overview levels."""
    name = "COG Overviews"
    if not _HAS_RASTERIO:
        return CheckResult(
            name, Status.WARN,
            "rasterio not installed — run: pip install rasterio",
        )
    try:
        with _rasterio.open(path) as src:
            w, h = src.width, src.height
            ovrs = src.overviews(1) if src.count > 0 else []
            small = w <= _MIN_OVR_SIZE and h <= _MIN_OVR_SIZE
            if small:
                return CheckResult(
                    name, Status.PASS,
                    f"Small file ({w}x{h}) — overviews not required",
                    {"width": w, "height": h, "overview_levels": ovrs},
                )
            if len(ovrs) < 2:
                return CheckResult(
                    name, Status.FAIL,
                    f"{w}x{h} file has {len(ovrs)} overview level(s) — need >= 2",
                    {
                        "width": w, "height": h,
                        "overview_levels_found": len(ovrs),
                        "fix": "gdaladdo -r average file.tif 2 4 8 16 32",
                    },
                )
            return CheckResult(
                name, Status.PASS,
                f"Overviews present: {ovrs}",
                {"width": w, "height": h, "overview_levels": ovrs},
            )
    except Exception as exc:
        return CheckResult(name, Status.FAIL, f"Could not open file: {exc}")


def check_cog_crs(path: Path) -> CheckResult:
    """Verify that the GeoTIFF has a defined CRS."""
    name = "COG CRS"
    if not _HAS_RASTERIO:
        return CheckResult(
            name, Status.WARN,
            "rasterio not installed — run: pip install rasterio",
        )
    try:
        with _rasterio.open(path) as src:
            crs = src.crs
            if not crs or str(crs) in ("None", "null", ""):
                return CheckResult(
                    name, Status.FAIL,
                    "No Coordinate Reference System defined",
                    {
                        "file": path.name,
                        "fix": "gdal_translate -a_srs EPSG:4326 ...",
                    },
                )
            epsg = crs.to_epsg()
            if epsg is None:
                return CheckResult(
                    name, Status.WARN,
                    "CRS defined but cannot resolve to a standard EPSG code",
                    {
                        "crs": str(crs)[:120],
                        "note": (
                            "Non-standard WKT datum name "
                            "(e.g. HLS products) — verify CRS is intentional"
                        ),
                    },
                )
            return CheckResult(
                name, Status.PASS,
                f"CRS: EPSG:{epsg}",
                {"epsg": epsg},
            )
    except Exception as exc:
        return CheckResult(name, Status.FAIL, f"Could not open file: {exc}")


def check_cog_nodata(path: Path, nan_ok: bool = True) -> CheckResult:
    """Verify that the GeoTIFF has a NoData value set."""
    name = "COG NoData"
    if not _HAS_RASTERIO:
        return CheckResult(
            name, Status.WARN,
            "rasterio not installed — run: pip install rasterio",
        )
    try:
        with _rasterio.open(path) as src:
            nodata = src.nodata
            w, h = src.width, src.height

            if nodata is None:
                # Scan the first band for common fill sentinel values.
                try:
                    import numpy as np
                    band = src.read(1)
                    fill_found = [v for v in _COMMON_FILL_VALUES if (band == v).any()]
                except ImportError:
                    fill_found = []

                if fill_found:
                    return CheckResult(
                        name, Status.FAIL,
                        f"NoData tag missing; fill value(s) {fill_found} present in data",
                        {
                            "fill_values_in_data": fill_found,
                            "fix": f"gdal_translate -a_nodata {fill_found[0]} ...",
                        },
                    )
                return CheckResult(
                    name, Status.WARN,
                    "NoData tag not set; no common fill values found in this tile",
                    {
                        "note": (
                            "NoData should be declared even if no fill pixels are present "
                            "in this sample tile"
                        ),
                        "file_size": f"{w}x{h}",
                    },
                )

            if isinstance(nodata, float) and math.isnan(nodata):
                if nan_ok:
                    return CheckResult(
                        name, Status.WARN,
                        "NoData=NaN (approved; NaN can be unreliable across some tools)",
                        {"nodata": "NaN"},
                    )
                return CheckResult(
                    name, Status.FAIL,
                    "NoData=NaN — unreliable across ArcGIS/GDAL/S3 streaming",
                    {
                        "nodata": "NaN",
                        "fix": "Replace NaN with a numeric sentinel",
                    },
                )

            return CheckResult(
                name, Status.PASS,
                f"NoData: {nodata}",
                {"nodata": nodata},
            )
    except Exception as exc:
        return CheckResult(name, Status.FAIL, f"Could not open file: {exc}")


# ── Format-agnostic ───────────────────────────────────────────────────────────

def check_file_size_accuracy(
    actual_files: list[Path],
    declared_mb: float | None,
    tolerance_pct: int = 20,
) -> CheckResult:
    """Compare sum of actual file sizes on disk against the declared SizeMBDataGranule."""
    name = "File Size Accuracy"

    if not actual_files:
        return CheckResult(
            name, Status.WARN,
            "No science files provided for size comparison",
        )

    disk_bytes = sum(
        f.stat().st_size for f in actual_files if f.exists()
    )
    disk_mb = disk_bytes / 1_048_576

    if declared_mb is None:
        return CheckResult(
            name, Status.WARN,
            f"SizeMBDataGranule not available for comparison "
            f"(disk: {disk_mb:.2f} MB)",
            {"disk_mb": round(disk_mb, 3)},
        )

    try:
        decl_mb = float(declared_mb)
    except (TypeError, ValueError):
        return CheckResult(
            name, Status.WARN,
            f"SizeMBDataGranule is non-numeric: {declared_mb!r}",
            {"disk_mb": round(disk_mb, 3)},
        )

    if decl_mb <= 0:
        return CheckResult(
            name, Status.WARN,
            f"SizeMBDataGranule = {decl_mb} — skipping size check",
            {"disk_mb": round(disk_mb, 3)},
        )

    pct_diff = abs(disk_mb - decl_mb) / decl_mb * 100
    details = {
        "disk_mb": round(disk_mb, 3),
        "declared_mb": round(decl_mb, 3),
        "diff_pct": round(pct_diff, 1),
        "tolerance_pct": tolerance_pct,
    }

    if pct_diff > tolerance_pct:
        return CheckResult(
            name, Status.WARN,
            (
                f"Disk size ({disk_mb:.2f} MB) differs from declared "
                f"SizeMBDataGranule ({decl_mb:.2f} MB) by {pct_diff:.1f}% "
                f"(tolerance: ±{tolerance_pct}%)"
            ),
            details,
        )

    return CheckResult(
        name, Status.PASS,
        f"Disk: {disk_mb:.2f} MB  ·  Declared: {decl_mb:.2f} MB  ·  Diff: {pct_diff:.1f}%",
        details,
    )


def check_prod_readiness(sidecar_text: str, env: str) -> CheckResult:
    """Scan sidecar text for UAT-environment strings when env is OPS."""
    name = "PROD Readiness"

    found = [m for m in _UAT_MARKERS if m.lower() in sidecar_text.lower()]

    if found:
        if env == "UAT":
            return CheckResult(
                name, Status.PASS,
                f"UAT markers present (expected in UAT environment): {found}",
                {"uat_markers_found": found},
            )
        return CheckResult(
            name, Status.FAIL,
            f"Sidecar contains UAT-specific strings: {found}",
            {
                "uat_markers_found": found,
                "fix": "Replace all UAT endpoints with production equivalents before OPS ingest",
            },
        )

    return CheckResult(
        name, Status.PASS,
        "No UAT-specific URL markers found",
    )


def check_collection_cross_reference(
    std_meta: dict,
    concept_id: str,
    env: str,
    uat_token: str | None = None,
) -> list[CheckResult]:
    """Fetch collection UMM-C and compare platforms, instruments, and format.

    *std_meta* is the normalised metadata dict produced by
    ``deep_runner._parse_sidecar()``.  *concept_id* is the collection
    (not granule) concept-id.
    """
    name = "Collection Cross-Reference"

    if not concept_id:
        return [CheckResult(
            name, Status.WARN,
            "Collection concept-id not provided — cross-reference skipped",
        )]

    host = _CMR_HOST.get(env, _CMR_HOST["OPS"])
    headers = {}
    if env == "UAT" and uat_token:
        headers["Authorization"] = f"Bearer {uat_token}"

    try:
        resp = requests.get(
            f"https://{host}/search/collections.umm_json",
            params={"concept_id": concept_id},
            headers=headers,
            timeout=20,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception as exc:
        return [CheckResult(
            name, Status.WARN,
            f"Could not fetch collection record: {exc}",
            {"concept_id": concept_id},
        )]

    if not items:
        return [CheckResult(
            name, Status.WARN,
            f"Collection {concept_id} not found in {env} CMR",
        )]

    coll_umm = items[0].get("umm", {})
    results: list[CheckResult] = []

    # ── DataFormat cross-check ────────────────────────────────────────────────
    gran_fmt = (std_meta.get("DataFormatType") or "").strip()
    adis_top = coll_umm.get("ArchiveAndDistributionInformation", {})
    coll_adis = (
        adis_top.get("FileDistributionInformation", [])
        or adis_top.get("FileArchiveInformation", [])
    )
    coll_fmts = [a.get("Format", "").strip() for a in coll_adis if a.get("Format")]

    if gran_fmt and coll_fmts:
        fmt_match = any(
            gran_fmt.upper() in f.upper() or f.upper() in gran_fmt.upper()
            for f in coll_fmts
        )
        if fmt_match:
            results.append(CheckResult(
                "Cross-Reference: DataFormat", Status.PASS,
                f"Granule format '{gran_fmt}' matches collection: {coll_fmts}",
            ))
        else:
            results.append(CheckResult(
                "Cross-Reference: DataFormat", Status.WARN,
                f"Granule DataFormat '{gran_fmt}' not in collection formats {coll_fmts}",
                {
                    "granule_format": gran_fmt,
                    "collection_formats": coll_fmts,
                    "fix": "Verify DataFormat in sidecar matches collection ArchiveAndDistributionInformation",
                },
            ))

    # ── Platform cross-check ──────────────────────────────────────────────────
    gran_plats = std_meta.get("Platforms") or []
    coll_plats = [
        p.get("ShortName", "").strip()
        for p in coll_umm.get("Platforms", [])
        if p.get("ShortName")
    ]

    if gran_plats and coll_plats:
        unmatched = [
            gp for gp in gran_plats
            if not any(gp.upper() == cp.upper() for cp in coll_plats)
        ]
        if unmatched:
            results.append(CheckResult(
                "Cross-Reference: Platforms", Status.WARN,
                f"Granule platform(s) not in collection: {unmatched}",
                {
                    "unmatched_granule_platforms": unmatched,
                    "collection_platforms": coll_plats,
                },
            ))
        else:
            results.append(CheckResult(
                "Cross-Reference: Platforms", Status.PASS,
                f"Platforms match: {gran_plats}",
            ))

    # ── Instrument cross-check ────────────────────────────────────────────────
    gran_insts = std_meta.get("Instruments") or []
    coll_insts = []
    for p in coll_umm.get("Platforms", []):
        for inst in p.get("Instruments", []):
            iname = inst.get("ShortName", "").strip()
            if iname and iname not in coll_insts:
                coll_insts.append(iname)

    if gran_insts and coll_insts:
        unmatched_i = [
            gi for gi in gran_insts
            if not any(gi.upper() == ci.upper() for ci in coll_insts)
        ]
        if unmatched_i:
            results.append(CheckResult(
                "Cross-Reference: Instruments", Status.WARN,
                f"Granule instrument(s) not in collection: {unmatched_i}",
                {
                    "unmatched_granule_instruments": unmatched_i,
                    "collection_instruments": coll_insts,
                },
            ))
        else:
            results.append(CheckResult(
                "Cross-Reference: Instruments", Status.PASS,
                f"Instruments match: {gran_insts}",
            ))

    if not results:
        results.append(CheckResult(
            name, Status.WARN,
            "Cross-reference skipped — insufficient platform/instrument/format data "
            "in sidecar or collection record",
            {"collection_concept_id": concept_id},
        ))

    return results
