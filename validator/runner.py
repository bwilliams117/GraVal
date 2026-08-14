"""Background validation runner: samples granules from CMR and runs checks."""

import queue
import random
import threading
import warnings
from dataclasses import dataclass, field
from typing import Callable

import earthaccess
import requests as _requests
from earthaccess.results import DataGranule

from .checks import (
    CheckResult,
    Status,
    check_collection_reference,
    check_daynight_consistency,
    check_duplicate_detection,
    check_file_size_sanity,
    check_production_date_sanity,
    check_schema_completeness,
    check_spatial_validity,
    check_temporal_validity,
    check_url_health,
)


_CMR_HOST = {
    "OPS": "cmr.earthdata.nasa.gov",
    "UAT": "cmr.uat.earthdata.nasa.gov",
}

# Registry of check_id → (display_label, function).
# Per-granule checks receive (granule,); collection_reference receives
# (granule, short_name, entry_title).  None marks a whole-sample check
# handled outside the per-granule loop.
CHECKS: dict[str, tuple[str, Callable | None]] = {
    "schema":       ("Schema Completeness",   check_schema_completeness),
    "temporal":     ("Temporal Validity",      check_temporal_validity),
    "spatial":      ("Spatial Validity",       check_spatial_validity),
    "daynight":     ("Day/Night Consistency",  check_daynight_consistency),
    "url_health":   ("URL Health",             check_url_health),
    "file_size":    ("File Size Sanity",       check_file_size_sanity),
    "prod_date":    ("Production Date Sanity", check_production_date_sanity),
    "collection":   ("Collection Reference",   check_collection_reference),
    "duplicates":   ("Duplicate Detection",    None),
}

ALL_CHECK_IDS = list(CHECKS.keys())

# CMR rejects page_num * page_size > 1,000,000; page_size=1 so this is the
# maximum page_num we can request.
_CMR_MAX_DEPTH = 1_000_000


@dataclass
class GranuleReport:
    """Aggregated validation results for a single granule."""

    granule_ur: str
    concept_id: str
    browse_url: str | None = None
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
class ValidationRun:
    """Complete results for a single validation session."""

    collection_short_name: str
    sample_size: int
    granule_reports: list[GranuleReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.granule_reports if r.overall_status == Status.PASS)

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.granule_reports if r.overall_status == Status.WARN)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.granule_reports if r.overall_status == Status.FAIL)


class ValidationRunner:
    """Executes a validation run on a background thread and exposes results via a queue."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._cancelled = threading.Event()
        self._thread: threading.Thread | None = None
        self.http_session: _requests.Session | None = None

    @property
    def result_queue(self) -> queue.Queue:
        return self._queue

    def run_async(
        self,
        short_name: str,
        sample_size: int,
        temporal: tuple[str, str] | None,
        enabled_checks: set[str],
        entry_title: str = "",
        env: str = "OPS",
        uat_token: str | None = None,
        concept_id: str = "",
    ) -> None:
        """Start a new validation run, replacing any previous state."""
        self._cancelled.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._thread = threading.Thread(
            target=self._worker,
            args=(
                short_name, sample_size, temporal,
                enabled_checks, entry_title,
                env, uat_token, concept_id,
            ),
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        """Signal the worker thread to stop at its next cancellation checkpoint."""
        self._cancelled.set()

    def _put(self, msg_type: str, payload):
        self._queue.put((msg_type, payload))

    def _worker(
        self, short_name, sample_size, temporal, enabled_checks,
        entry_title="", env="OPS", uat_token=None, concept_id="",
    ):
        run = ValidationRun(collection_short_name=short_name, sample_size=sample_size)

        try:
            self._put("progress", (0, 1, f"Searching for granules in {short_name}..."))

            host = _CMR_HOST.get(env, _CMR_HOST["OPS"])
            granule_url = f"https://{host}/search/granules.umm_json"

            # Build the base CMR search params.
            # Pin to the exact collection concept_id when available — this is the
            # only reliable way to stay within the selected collection across both
            # OPS and UAT, because short_name alone can match collections in the
            # other environment.
            base_params: dict = {"page_size": 1}
            if concept_id:
                base_params["collection_concept_id"] = concept_id
            else:
                base_params["short_name"] = short_name
            if temporal and temporal[0]:
                base_params["temporal[]"] = f"{temporal[0]},{temporal[1] or ''}"

            # UAT requires a Bearer token; OPS uses the earthaccess session
            # which handles its own auth internally.
            if env == "UAT":
                session = _requests.Session()
                if uat_token:
                    session.headers["Authorization"] = f"Bearer {uat_token}"
                hit_resp = session.get(
                    granule_url, params={**base_params, "page_size": 1},
                    timeout=20,
                )
                hit_resp.raise_for_status()
                total_count = int(hit_resp.headers.get("CMR-Hits", 0))
            else:
                # For OPS use the authenticated earthaccess session so it can
                # reach protected collections.
                session = earthaccess.get_requests_https_session()
                hit_resp = session.get(
                    granule_url,
                    params={**base_params, "page_size": 1},
                )
                hit_resp.raise_for_status()
                total_count = int(hit_resp.headers.get("CMR-Hits", 0))

            self.http_session = session

            if total_count == 0:
                run.errors.append(f"No granules found for collection '{short_name}'")
                self._put("done", run)
                return

            if self._cancelled.is_set():
                self._put("cancelled", None)
                return

            max_page = min(total_count, _CMR_MAX_DEPTH)

            need = min(sample_size, total_count)
            # Pre-select unique page offsets so we never fetch the same CMR
            # offset twice — sampling without replacement at the page level.
            pages = random.sample(range(1, max_page + 1), need)
            sample = []

            for i, page_num in enumerate(pages):
                if self._cancelled.is_set():
                    self._put("cancelled", None)
                    return

                self._put("progress", (i, need, f"Sampling granules ({i}/{need})..."))

                resp = session.get(
                    granule_url,
                    params={**base_params, "page_num": page_num},
                    timeout=20,
                )
                resp.raise_for_status()
                items = resp.json().get("items", [])
                if not items:
                    continue

                item = items[0]
                cloud = any(
                    "s3://" in (
                        ln.get("URL", "") if isinstance(ln, dict) else ""
                    )
                    for ln in item.get("umm", {}).get("RelatedUrls", [])
                )
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sample.append(DataGranule(item, cloud_hosted=cloud))

            if not sample:
                run.errors.append(f"No granules found for collection '{short_name}'")
                self._put("done", run)
                return

            total = len(sample)

            dup_results: list[CheckResult] = []
            if "duplicates" in enabled_checks:
                dup_results = check_duplicate_detection(sample)

            for idx, granule in enumerate(sample):
                if self._cancelled.is_set():
                    self._put("cancelled", None)
                    return

                granule_ur = granule.get("umm", {}).get("GranuleUR", "unknown")
                concept_id = granule.get("meta", {}).get("concept-id", "unknown")
                self._put("progress", (idx, total, f"Checking {granule_ur}"))

                related = granule.get("umm", {}).get("RelatedUrls", [])
                browse_url = next(
                    (
                        u["URL"] for u in related
                        if u.get("Type") == "GET RELATED VISUALIZATION"
                        and u.get("URL", "").startswith("http")
                    ),
                    None,
                )
                report = GranuleReport(
                    granule_ur=granule_ur,
                    concept_id=concept_id,
                    browse_url=browse_url,
                )

                for check_id, (_, fn) in CHECKS.items():
                    if check_id not in enabled_checks or fn is None:
                        continue
                    try:
                        if check_id == "collection":
                            result = fn(granule, short_name, entry_title)
                        elif check_id == "url_health":
                            result = fn(granule, session)
                        else:
                            result = fn(granule)
                    except Exception as exc:
                        result = CheckResult(
                            check_name=CHECKS[check_id][0],
                            status=Status.WARN,
                            message=f"Check raised an exception: {exc}",
                        )
                    report.checks.append(result)

                if "duplicates" in enabled_checks and dup_results:
                    report.checks.append(dup_results[idx])

                run.granule_reports.append(report)

            self._put("progress", (total, total, "Validation complete"))
            self._put("done", run)

        except Exception as exc:
            run.errors.append(str(exc))
            self._put("error", str(exc))
