"""Background runner for the Granule Inspector: downloads science files and runs checks."""

import queue
import re
import shutil
import threading
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import earthaccess
import requests
from earthaccess.results import DataGranule

from .checks import (
    CheckResult,
    Status,
    check_collection_reference,
    check_daynight_consistency,
    check_file_size_sanity,
    check_production_date_sanity,
    check_schema_completeness,
    check_spatial_validity,
    check_temporal_validity,
    check_url_health,
)
from .deep_checks import (
    check_cog_crs,
    check_cog_nodata,
    check_cog_overviews,
    check_cog_tiling,
    check_collection_cross_reference,
    check_file_size_accuracy,
    check_hdf4_core_metadata,
    check_hdf5_standard_metadata,
    check_netcdf_structure,
    check_prod_readiness,
)

# ── constants ─────────────────────────────────────────────────────────────────

_CMR_HOST = {
    "OPS": "cmr.earthdata.nasa.gov",
    "UAT": "cmr.uat.earthdata.nasa.gov",
}
_PROVIDER = {
    "OPS": "LPCLOUD",
    "UAT": "LPCLOUDUAT",
}
_DOWNLOAD_ROOT = Path.home() / "Documents" / "GraVal" / "downloads"
_CHUNK_SIZE = 1024 * 256   # 256 KB chunks for streaming downloads

# Registry of file-level check_id → (display_label, function | None).
DEEP_CHECKS: dict[str, tuple[str, Callable | None]] = {
    "hdf5_sm":        ("HDF5 Standard Metadata",  None),   # dispatched by format
    "cog_compliance": ("COG Compliance",           None),   # dispatched by format
    "hdf4_core":      ("HDF4 Core Metadata",       None),   # dispatched by format
    "netcdf_struct":  ("NetCDF Structure",         None),   # dispatched by format
    "file_size":      ("File Size Accuracy",       check_file_size_accuracy),
    "prod_readiness": ("PROD Readiness",           check_prod_readiness),
    "coll_xref":      ("Collection Cross-Reference", check_collection_cross_reference),
}


# ── data classes ──────────────────────────────────────────────────────────────

@dataclass
class DeepGranuleReport:
    """Aggregated validation results for a single inspected granule."""

    granule_ur: str
    concept_id: str
    browse_url: str | None = None
    local_folder: Path | None = None
    local_files: list[Path] = field(default_factory=list)
    sidecar_path: Path | None = None
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def overall_status(self) -> Status:
        statuses = {c.status for c in self.checks}
        if Status.FAIL in statuses:
            return Status.FAIL
        if Status.WARN in statuses:
            return Status.WARN
        return Status.PASS


@dataclass
class DeepValidationRun:
    """Complete results for a single Inspector session."""

    collection_short_name: str
    granule_count: int
    granule_reports: list[DeepGranuleReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(
            1 for r in self.granule_reports if r.overall_status == Status.PASS
        )

    @property
    def warn_count(self) -> int:
        return sum(
            1 for r in self.granule_reports if r.overall_status == Status.WARN
        )

    @property
    def fail_count(self) -> int:
        return sum(
            1 for r in self.granule_reports if r.overall_status == Status.FAIL
        )


# ── format detection & sidecar helpers ───────────────────────────────────────

# Magic byte signatures for supported science formats.
_MAGIC = {
    b"\x89HDF\r\n\x1a\n": "HDF5",
    b"\x0e\x03\x13\x01":  "HDF4",
    b"CDF\x01":            "NC3",
    b"CDF\x02":            "NC3",
    b"II*\x00":            "TIFF",
    b"MM\x00*":            "TIFF",
}


def _detect_format(path: Path) -> str:
    """Return a format string based on magic bytes, or 'UNKNOWN'."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(8)
        for magic, fmt in _MAGIC.items():
            if header.startswith(magic):
                # An HDF5 file whose magic matches and whose path ends in .nc/.nc4
                # is a NetCDF4 (HDF5-based) file.
                if fmt == "HDF5" and path.suffix.lower() in (".nc", ".nc4", ".nc3"):
                    return "NC4"
                return fmt
    except OSError:
        pass
    return "UNKNOWN"


def _locate_sidecar(folder: Path) -> Path | None:
    """Return the sidecar metadata file in *folder* using CURATOR's priority order."""
    # Priority 1: explicit CMR sidecar extensions
    for pattern in ("*.cmr.xml", "*.echo10", "*.xml"):
        for p in sorted(folder.glob(pattern)):
            name_lower = p.name.lower()
            if "echo10" in name_lower or "cmr" in name_lower:
                return p

    # Priority 2: JSON with UMM-G keys
    for p in sorted(folder.glob("*.json")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            if any(
                key in text
                for key in ("MetadataSpecification", "CollectionReference", "GranuleUR")
            ):
                return p
        except OSError:
            continue

    # Priority 3: any XML, then any JSON, then .inf
    for pattern in ("*.xml", "*.json", "*.inf"):
        candidates = sorted(folder.glob(pattern))
        if candidates:
            return candidates[0]

    return None


def _parse_sidecar(sidecar_path: Path) -> dict:
    """Return a normalised std_meta dict from an ECHO10 XML or UMM-G JSON sidecar."""
    import json

    text = sidecar_path.read_text(encoding="utf-8", errors="replace")
    suffix = sidecar_path.suffix.lower()

    std: dict = {
        "ShortName": "",
        "VersionId": "",
        "GranuleUR": "",
        "ProducerGranuleId": "",
        "BeginningDateTime": "",
        "EndingDateTime": "",
        "DayNightFlag": "",
        "ProductionDateTime": "",
        "SizeMBDataGranule": None,
        "DataFormatType": "",
        "NorthBoundingCoordinate": None,
        "SouthBoundingCoordinate": None,
        "EastBoundingCoordinate": None,
        "WestBoundingCoordinate": None,
        "DOI": "",
        "RelatedUrls": [],
        "Platforms": [],
        "Instruments": [],
    }

    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return std

        std["GranuleUR"] = data.get("GranuleUR", "")
        std["ProducerGranuleId"] = (
            data.get("DataGranule", {}).get("ProducerGranuleId", "")
        )
        ref = data.get("CollectionReference", {})
        std["ShortName"] = ref.get("ShortName", "")
        std["VersionId"] = ref.get("Version", "")

        rdt = data.get("TemporalExtent", {}).get("RangeDateTime", {})
        std["BeginningDateTime"] = rdt.get("BeginningDateTime", "")
        std["EndingDateTime"] = rdt.get("EndingDateTime", "")

        dg = data.get("DataGranule", {})
        std["DayNightFlag"] = dg.get("DayNightFlag", "")
        std["ProductionDateTime"] = dg.get("ProductionDateTime", "")
        for entry in dg.get("ArchiveAndDistributionInformation", []):
            mb = entry.get("Size")
            unit = entry.get("SizeUnit", "MB").upper()
            if mb is not None:
                multiplier = {"KB": 1/1024, "MB": 1, "GB": 1024, "TB": 1024**2}.get(
                    unit, 1
                )
                std["SizeMBDataGranule"] = (std["SizeMBDataGranule"] or 0) + mb * multiplier

        geom = (
            data.get("SpatialExtent", {})
            .get("HorizontalSpatialDomain", {})
            .get("Geometry", {})
        )
        rects = geom.get("BoundingRectangles", [])
        if rects:
            r = rects[0]
            std["NorthBoundingCoordinate"] = r.get("NorthBoundingCoordinate")
            std["SouthBoundingCoordinate"] = r.get("SouthBoundingCoordinate")
            std["EastBoundingCoordinate"] = r.get("EastBoundingCoordinate")
            std["WestBoundingCoordinate"] = r.get("WestBoundingCoordinate")

        std["RelatedUrls"] = data.get("RelatedUrls", [])
        for p in data.get("Platforms", []):
            std["Platforms"].append(p.get("ShortName", ""))
            for inst in p.get("Instruments", []):
                std["Instruments"].append(inst.get("ShortName", ""))

        return std

    # ECHO10 XML path
    def _tx(elem, *paths) -> str:
        """Extract text from the first matching child path."""
        if elem is None:
            return ""
        for path in paths:
            found = elem.find(path)
            if found is not None and found.text:
                return found.text.strip()
        return ""

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return std

    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    pfx = f"{{{ns}}}" if ns else ""

    def _find(path: str):
        return root.find(path.replace("/", f"/{pfx}").lstrip(f"/{pfx}"))

    std["GranuleUR"] = _tx(root, f"{pfx}GranuleUR")
    std["ProducerGranuleId"] = _tx(
        root, f"{pfx}DataGranule/{pfx}ProducerGranuleId"
    )

    coll = root.find(f"{pfx}Collection")
    if coll is not None:
        std["ShortName"] = _tx(coll, f"{pfx}ShortName")
        std["VersionId"] = _tx(coll, f"{pfx}VersionId")

    tr = root.find(f"{pfx}Temporal/{pfx}RangeDateTime")
    if tr is not None:
        std["BeginningDateTime"] = _tx(tr, f"{pfx}BeginningDateTime")
        std["EndingDateTime"] = _tx(tr, f"{pfx}EndingDateTime")

    dg = root.find(f"{pfx}DataGranule")
    if dg is not None:
        std["DayNightFlag"] = _tx(dg, f"{pfx}DayNightFlag")
        std["ProductionDateTime"] = _tx(dg, f"{pfx}ProductionDateTime")
        size_str = _tx(dg, f"{pfx}SizeMBDataGranule")
        if size_str:
            try:
                std["SizeMBDataGranule"] = float(size_str)
            except ValueError:
                pass

    sp = root.find(f"{pfx}Spatial/{pfx}HorizontalSpatialDomain/{pfx}Geometry/{pfx}BoundingRectangle")
    if sp is not None:
        for key, tag in (
            ("NorthBoundingCoordinate", "NorthBoundingCoordinate"),
            ("SouthBoundingCoordinate", "SouthBoundingCoordinate"),
            ("EastBoundingCoordinate", "EastBoundingCoordinate"),
            ("WestBoundingCoordinate", "WestBoundingCoordinate"),
        ):
            val = _tx(sp, f"{pfx}{tag}")
            if val:
                try:
                    std[key] = float(val)
                except ValueError:
                    pass

    for url_elem in root.findall(f".//{pfx}OnlineResource") + root.findall(f".//{pfx}OnlineAccessURL"):
        url = _tx(url_elem, f"{pfx}URL")
        url_type = _tx(url_elem, f"{pfx}Type", f"{pfx}URLContentType")
        desc = _tx(url_elem, f"{pfx}Description", f"{pfx}URLDescription")
        if url:
            std["RelatedUrls"].append({"URL": url, "Type": url_type, "Description": desc})

    return std


# ── runner ────────────────────────────────────────────────────────────────────

class DeepValidationRunner:
    """Downloads science files and runs metadata + file-level checks on a background thread."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._cancelled = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def result_queue(self) -> queue.Queue:
        return self._queue

    def run_async(self, check_config: dict) -> None:
        """Start a new inspection run, replacing any previous state."""
        self._cancelled.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._thread = threading.Thread(
            target=self._worker, args=(check_config,), daemon=True
        )
        self._thread.start()

    def cancel(self) -> None:
        """Signal the worker to stop; it will clean up the in-progress folder."""
        self._cancelled.set()

    def _put(self, msg_type: str, payload):
        self._queue.put((msg_type, payload))

    # ── worker ────────────────────────────────────────────────────────────────

    def _worker(self, cfg: dict):
        short_name = cfg["short_name"]
        version = cfg["version"]
        concept_id = cfg["concept_id"]
        env = cfg["env"]
        uat_token = cfg.get("uat_token") or ""
        file_format = cfg.get("file_format", "AUTO")
        max_granules = cfg.get("max_granules", 1)
        enabled_meta = cfg.get("enabled_metadata_checks", set())
        enabled_file = cfg.get("enabled_file_checks", set())

        run = DeepValidationRun(
            collection_short_name=short_name,
            granule_count=max_granules,
        )

        try:
            self._put("progress", (0, max_granules, f"Searching for granules in {short_name}..."))

            granules = self._search_granules(
                short_name, version, concept_id, env, uat_token, max_granules
            )

            if not granules:
                run.errors.append(f"No granules found for '{short_name}' in {env}")
                self._put("done", run)
                return

            total = len(granules)

            for idx, granule in enumerate(granules):
                if self._cancelled.is_set():
                    self._put("cancelled", None)
                    return

                granule_ur = granule.get("umm", {}).get("GranuleUR", f"granule_{idx}")
                concept_id_g = granule.get("meta", {}).get("concept-id", "unknown")

                self._put("progress", (idx, total, f"Downloading {granule_ur}..."))
                self._put(
                    "download_progress",
                    (idx, granule_ur, 0, 0, "starting"),
                )

                related = granule.get("umm", {}).get("RelatedUrls", [])
                browse_url = next(
                    (
                        u["URL"] for u in related
                        if u.get("Type") == "GET RELATED VISUALIZATION"
                        and u.get("URL", "").startswith("https://")
                    ),
                    None,
                )

                report = DeepGranuleReport(
                    granule_ur=granule_ur,
                    concept_id=concept_id_g,
                    browse_url=browse_url,
                )

                # ── metadata checks (same as existing Validator) ──────────────
                self._run_metadata_checks(
                    report, granule, short_name, enabled_meta,
                    granule.get("umm", {}).get("EntryTitle", ""),
                )

                if self._cancelled.is_set():
                    self._put("cancelled", None)
                    return

                # ── download ──────────────────────────────────────────────────
                granule_folder = self._build_folder_path(
                    env, short_name, version, concept_id, granule_ur
                )
                report.local_folder = granule_folder
                current_folder = granule_folder

                try:
                    granule_folder.mkdir(parents=True, exist_ok=True)
                    download_ok = self._download_granule(
                        granule, env, uat_token, granule_folder, idx, granule_ur
                    )
                except Exception as exc:
                    shutil.rmtree(current_folder, ignore_errors=True)
                    report.checks.append(CheckResult(
                        "Download", Status.FAIL, str(exc)[:200],
                    ))
                    run.granule_reports.append(report)
                    self._put("download_progress", (idx, granule_ur, 0, 0, "failed"))
                    continue

                if self._cancelled.is_set():
                    shutil.rmtree(current_folder, ignore_errors=True)
                    self._put("cancelled", None)
                    return

                if not download_ok:
                    report.checks.append(CheckResult(
                        "Download", Status.FAIL,
                        "No downloadable files found for this granule",
                    ))
                    run.granule_reports.append(report)
                    continue

                # ── file inventory ────────────────────────────────────────
                local_files = [
                    p for p in granule_folder.iterdir()
                    if p.is_file() and not p.name.startswith(".")
                ]
                report.local_files = local_files
                report.sidecar_path = _locate_sidecar(granule_folder)

                science_files = [
                    p for p in local_files
                    if p != report.sidecar_path
                    and p.suffix.lower() not in (".xml", ".json", ".inf", ".met")
                ]

                # ── file-level checks ─────────────────────────────────────
                self._put(
                    "progress",
                    (idx, total, f"Inspecting {granule_ur}..."),
                )
                try:
                    self._run_file_checks(
                        report, science_files, report.sidecar_path,
                        file_format, cfg, enabled_file,
                    )
                except Exception as exc:
                    report.checks.append(CheckResult(
                        "File Checks", Status.FAIL, str(exc)[:200],
                    ))

                run.granule_reports.append(report)
                self._put("download_progress", (idx, granule_ur, 1, 1, "done"))

            self._put("progress", (total, total, "Inspection complete"))
            self._put("done", run)

        except Exception as exc:
            run.errors.append(str(exc))
            self._put("error", str(exc))

    # ── CMR search ────────────────────────────────────────────────────────────

    def _search_granules(
        self,
        short_name: str,
        version: str,
        concept_id: str,
        env: str,
        uat_token: str,
        max_granules: int,
    ) -> list:
        if env == "OPS":
            return self._search_ops(short_name, version, max_granules)
        return self._search_uat(
            short_name, version, concept_id, uat_token, max_granules
        )

    def _search_ops(self, short_name: str, version: str, max_granules: int) -> list:
        """Fetch granules from OPS CMR using earthaccess."""
        query = earthaccess.DataGranules().short_name(short_name)
        if version:
            query = query.version(version)
        total = query.hits()
        if total == 0:
            return []

        import random
        session = earthaccess.get_requests_https_session()
        params: dict = {"short_name": short_name, "page_size": 1}
        if version:
            params["version"] = version

        max_page = min(total, 1_000_000)
        results = []
        for _ in range(min(max_granules, total)):
            page_num = random.randint(1, max_page)
            resp = session.get(
                f"https://{_CMR_HOST['OPS']}/search/granules.umm_json",
                params={**params, "page_num": page_num},
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if items:
                item = items[0]
                cloud = any(
                    "s3://" in (
                        ln.get("URL", "") if isinstance(ln, dict) else ""
                    )
                    for ln in item.get("umm", {}).get("RelatedUrls", [])
                )
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    results.append(DataGranule(item, cloud_hosted=cloud))
        return results

    def _search_uat(
        self,
        short_name: str,
        version: str,
        concept_id: str,
        token: str,
        max_granules: int,
    ) -> list:
        """Fetch granules from UAT CMR via direct requests call."""
        import random

        headers = {"Authorization": f"Bearer {token}"} if token else {}
        base_url = f"https://{_CMR_HOST['UAT']}/search/granules.umm_json"
        params: dict = {"page_size": 1}
        if concept_id:
            params["collection_concept_id"] = concept_id
        elif short_name:
            params["short_name"] = short_name
            if version:
                params["version"] = version

        # Get total count first.
        count_resp = requests.get(
            base_url, params={**params, "page_size": 1},
            headers=headers, timeout=20,
        )
        count_resp.raise_for_status()
        total = int(count_resp.headers.get("CMR-Hits", 0))
        if total == 0:
            return []

        max_page = min(total, 1_000_000)
        results = []
        for _ in range(min(max_granules, total)):
            page_num = random.randint(1, max_page)
            resp = requests.get(
                base_url, params={**params, "page_num": page_num},
                headers=headers, timeout=20,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if items:
                item = items[0]
                cloud = any(
                    "s3://" in (
                        ln.get("URL", "") if isinstance(ln, dict) else ""
                    )
                    for ln in item.get("umm", {}).get("RelatedUrls", [])
                )
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    results.append(DataGranule(item, cloud_hosted=cloud))
        return results

    # ── download ──────────────────────────────────────────────────────────────

    def _build_folder_path(
        self,
        env: str,
        short_name: str,
        version: str,
        concept_id: str,
        granule_ur: str,
    ) -> Path:
        safe_ur = re.sub(r"[^\w.\-]", "_", granule_ur)[:80]
        return (
            _DOWNLOAD_ROOT / env / f"{short_name}_v{version}" / concept_id / safe_ur
        )

    def _download_granule(
        self,
        granule,
        env: str,
        uat_token: str,
        dest_folder: Path,
        granule_idx: int,
        granule_ur: str,
    ) -> bool:
        """Download all science and sidecar files for *granule* into *dest_folder*.

        Returns True if at least one file was downloaded.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                data_links = granule.data_links()
            except Exception:
                data_links = []

        related = granule.get("umm", {}).get("RelatedUrls", [])

        # Collect all downloadable science file URLs across ECHO10 and UMM-G
        # type vocabularies. Older UAT granules often use "GET DATA VIA DIRECT
        # ACCESS" or non-standard types instead of "GET DATA".
        _DATA_TYPES = {
            "GET DATA",
            "GET DATA VIA DIRECT ACCESS",
            "DIRECT DOWNLOAD",
            "GET RELATED DATA",
        }
        get_data_https = [
            u["URL"] for u in related
            if (
                u.get("Type") in _DATA_TYPES
                or u.get("Subtype") in _DATA_TYPES
            )
            and u.get("URL", "").startswith(("https://", "http://"))
        ]

        # Sidecar/metadata links (XML/JSON).
        sidecar_links = [
            u["URL"] for u in related
            if u.get("Type") in (
                "EXTENDED METADATA",
                "METADATA",
                "DATA QUALITY",
                "VIEW RELATED INFORMATION",
            )
            and u.get("URL", "").lower().endswith((".xml", ".json", ".cmr.xml"))
        ]

        # all_links is the union used by UAT streaming and OPS fallback.
        all_links = list(dict.fromkeys(get_data_https + data_links + sidecar_links))
        if not all_links and not data_links:
            return False

        if env == "OPS":
            self._download_ops(granule, all_links, dest_folder, granule_idx, granule_ur)
        else:
            self._download_uat(all_links, uat_token, dest_folder, granule_idx, granule_ur)

        return any(dest_folder.iterdir())

    def _download_ops(self, granule, links: list[str], dest: Path, idx: int, gur: str):
        """Download OPS files, preferring cancellable HTTPS streaming over earthaccess."""
        https_links = [l for l in links if l.startswith("https://")]
        if https_links:
            # Stream via authenticated HTTPS so cancel checks fire between chunks.
            session = earthaccess.get_requests_https_session()
            self._stream_links(https_links, dest, session.get, {}, idx, gur)
            if any(dest.iterdir()):
                return

        if self._cancelled.is_set():
            return

        # S3-only granule: fall back to earthaccess (blocking, not interruptible).
        try:
            earthaccess.download([granule], local_path=str(dest))
        except Exception:
            pass

    def _download_uat(self, links: list[str], token: str, dest: Path, idx: int, gur: str):
        """Download UAT files via HTTPS streaming with Bearer token auth."""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._stream_links(links, dest, requests.get, headers, idx, gur)

    def _stream_links(
        self,
        links: list[str],
        dest: Path,
        get_fn,
        headers: dict,
        idx: int,
        gur: str,
    ):
        """Stream each URL to disk, emitting download_progress queue messages per chunk."""
        for file_num, url in enumerate(links):
            if self._cancelled.is_set():
                return
            filename = url.split("/")[-1].split("?")[0] or f"file_{file_num}"
            out_path = dest / filename
            try:
                try:
                    resp = get_fn(url, headers=headers, stream=True, timeout=60)
                except requests.exceptions.SSLError:
                    resp = get_fn(
                        url, headers=headers, stream=True, timeout=60, verify=False
                    )
                resp.raise_for_status()
                total_bytes = int(resp.headers.get("Content-Length", 0))
                bytes_so_far = 0
                with open(out_path, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                        if self._cancelled.is_set():
                            return
                        if chunk:
                            fh.write(chunk)
                            bytes_so_far += len(chunk)
                            self._put(
                                "download_progress",
                                (idx, gur, bytes_so_far, total_bytes, "downloading"),
                            )
            except Exception:
                out_path.unlink(missing_ok=True)

    # ── check dispatch ────────────────────────────────────────────────────────

    def _run_metadata_checks(
        self,
        report: DeepGranuleReport,
        granule,
        short_name: str,
        enabled: set[str],
        entry_title: str,
    ):
        """Run the existing UMM-G metadata checks against the CMR granule object."""
        meta_dispatch = {
            "schema":     (check_schema_completeness,    lambda g, _s, _e: check_schema_completeness(g)),
            "temporal":   (check_temporal_validity,      lambda g, _s, _e: check_temporal_validity(g)),
            "spatial":    (check_spatial_validity,       lambda g, _s, _e: check_spatial_validity(g)),
            "daynight":   (check_daynight_consistency,   lambda g, _s, _e: check_daynight_consistency(g)),
            "url_health": (check_url_health,             lambda g, _s, _e: check_url_health(g)),
            "file_size":  (check_file_size_sanity,       lambda g, _s, _e: check_file_size_sanity(g)),
            "prod_date":  (check_production_date_sanity, lambda g, _s, _e: check_production_date_sanity(g)),
            "collection": (check_collection_reference,  lambda g, s, e: check_collection_reference(g, s, e)),
        }
        for check_id, (_, fn) in meta_dispatch.items():
            if check_id not in enabled:
                continue
            try:
                result = fn(granule, short_name, entry_title)
            except Exception as exc:
                result = CheckResult(
                    check_id, Status.WARN, f"Check raised an exception: {exc}"
                )
            report.checks.append(result)

    def _run_file_checks(
        self,
        report: DeepGranuleReport,
        science_files: list[Path],
        sidecar_path: Path | None,
        file_format: str,
        cfg: dict,
        enabled: set[str],
    ):
        """Dispatch file-level checks based on detected format."""
        if not science_files:
            report.checks.append(CheckResult(
                "File Inventory", Status.WARN,
                "No science files found in downloaded folder",
            ))
            return

        for sci_path in science_files:
            fmt = file_format if file_format != "AUTO" else _detect_format(sci_path)

            if fmt == "HDF5" and "hdf5_sm" in enabled:
                for res in check_hdf5_standard_metadata(
                    sci_path,
                    sm_path=cfg.get("hdf5_sm_path") or None,
                    required=cfg.get("hdf5_sm_required") or [],
                    expected=cfg.get("hdf5_sm_expected") or {},
                    dataset_specs=cfg.get("hdf5_dataset_specs") or {},
                ):
                    report.checks.append(res)

            elif fmt in ("NC3", "NC4") and "netcdf_struct" in enabled:
                report.checks.append(check_netcdf_structure(sci_path))

            elif fmt == "HDF4" and "hdf4_core" in enabled:
                report.checks.append(check_hdf4_core_metadata(sci_path))

            elif fmt == "TIFF" and "cog_compliance" in enabled:
                report.checks.append(check_cog_tiling(sci_path))
                report.checks.append(check_cog_overviews(sci_path))
                report.checks.append(check_cog_crs(sci_path))
                report.checks.append(check_cog_nodata(sci_path))

        # Format-agnostic checks.
        if "file_size" in enabled:
            declared_mb = None
            if sidecar_path:
                std = _parse_sidecar(sidecar_path)
                declared_mb = std.get("SizeMBDataGranule")
            report.checks.append(
                check_file_size_accuracy(
                    science_files, declared_mb,
                    cfg.get("size_tolerance_pct", 20),
                )
            )

        if "prod_readiness" in enabled and sidecar_path:
            sidecar_text = sidecar_path.read_text(encoding="utf-8", errors="replace")
            report.checks.append(
                check_prod_readiness(sidecar_text, cfg["env"])
            )

        if "coll_xref" in enabled:
            std = _parse_sidecar(sidecar_path) if sidecar_path else {}
            for res in check_collection_cross_reference(
                std, cfg["concept_id"], cfg["env"],
                uat_token=cfg.get("uat_token"),
            ):
                report.checks.append(res)
