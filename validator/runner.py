import queue
import random
import threading
import warnings
from dataclasses import dataclass, field
from typing import Callable

import earthaccess
import requests as _requests

from .checks import (
    CheckResult,
    Status,
    check_collection_reference,
    check_daynight_consistency,
    check_duplicate_detection,
    check_file_availability,
    check_file_size_sanity,
    check_schema_completeness,
    check_spatial_validity,
    check_temporal_validity,
)

# Registry: check_id → (label, function)
# Per-granule checks take (granule,); collection_reference takes (granule, short_name)
CHECKS = {
    "schema":      ("Schema Completeness",        check_schema_completeness),
    "temporal":    ("Temporal Validity",           check_temporal_validity),
    "spatial":     ("Spatial Validity",            check_spatial_validity),
    "daynight":    ("Day/Night Consistency",       check_daynight_consistency),
    "file_avail":  ("File Availability",           check_file_availability),
    "file_size":   ("File Size Sanity",            check_file_size_sanity),
    "collection":  ("Collection Reference",        check_collection_reference),
    "duplicates":  ("Duplicate Detection",         None),  # handled separately (whole-sample check)
}

ALL_CHECK_IDS = list(CHECKS.keys())


@dataclass
class GranuleReport:
    granule_ur: str
    concept_id: str
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
    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._cancelled = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def result_queue(self) -> queue.Queue:
        return self._queue

    def run_async(
        self,
        short_name: str,
        sample_size: int,
        temporal: tuple[str, str] | None,
        enabled_checks: set[str],
    ) -> None:
        self._cancelled.clear()
        # Drain any leftover messages from a prior run
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._thread = threading.Thread(
            target=self._worker,
            args=(short_name, sample_size, temporal, enabled_checks),
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancelled.set()

    def _put(self, msg_type: str, payload):
        self._queue.put((msg_type, payload))

    def _worker(self, short_name, sample_size, temporal, enabled_checks):
        run = ValidationRun(collection_short_name=short_name, sample_size=sample_size)

        try:
            self._put("progress", (0, 1, f"Searching for granules in {short_name}..."))

            # One fetch builds the bucket. Use a random offset so the bucket
            # isn't always the same 50 most-recent granules.
            query = earthaccess.DataGranules().short_name(short_name)
            if temporal and temporal[0]:
                query = query.temporal(*temporal)

            total_count = query.hits()

            if total_count == 0:
                run.errors.append(f"No granules found for collection '{short_name}'")
                self._put("done", run)
                return

            if self._cancelled.is_set():
                self._put("cancelled", None)
                return

            # Each granule is fetched from an independently chosen random page,
            # so picks are spread across the full collection history rather than
            # clustered in one time window. CMR rejects page_num * page_size > 1,000,000.
            CMR_MAX_DEPTH = 1_000_000
            max_page = min(total_count, CMR_MAX_DEPTH)  # page_size=1 so max_page = max_depth

            from earthaccess.results import DataGranule
            session = earthaccess.get_requests_https_session()

            base_params = {"short_name": short_name, "page_size": 1}
            if temporal and temporal[0]:
                base_params["temporal[]"] = f"{temporal[0]},{temporal[1] or ''}"

            need = min(sample_size, total_count)
            sample = []
            total = need

            for i in range(need):
                if self._cancelled.is_set():
                    self._put("cancelled", None)
                    return

                self._put("progress", (i, total, f"Sampling granules ({i}/{total})..."))

                page_num = random.randint(1, max_page)
                resp = session.get(
                    "https://cmr.earthdata.nasa.gov/search/granules.umm_json",
                    params={**base_params, "page_num": page_num},
                )
                resp.raise_for_status()
                items = resp.json().get("items", [])
                if not items:
                    continue

                item = items[0]
                cloud = any(
                    "s3://" in (l.get("URL", "") if isinstance(l, dict) else "")
                    for l in item.get("umm", {}).get("RelatedUrls", [])
                )
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sample.append(DataGranule(item, cloud_hosted=cloud))

            if not sample:
                run.errors.append(f"No granules found for collection '{short_name}'")
                self._put("done", run)
                return
            total = len(sample)

            # Duplicate detection across the whole sample
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

                report = GranuleReport(granule_ur=granule_ur, concept_id=concept_id)

                # Per-granule checks
                for check_id, (_, fn) in CHECKS.items():
                    if check_id not in enabled_checks or fn is None:
                        continue
                    try:
                        if check_id == "collection":
                            result = fn(granule, short_name)
                        else:
                            result = fn(granule)
                    except Exception as exc:
                        from .checks import CheckResult, Status
                        result = CheckResult(
                            check_name=CHECKS[check_id][0],
                            status=Status.WARN,
                            message=f"Check raised an exception: {exc}",
                        )
                    report.checks.append(result)

                # Attach this granule's duplicate result
                if "duplicates" in enabled_checks and dup_results:
                    report.checks.append(dup_results[idx])

                run.granule_reports.append(report)

            self._put("progress", (total, total, "Validation complete"))
            self._put("done", run)

        except Exception as exc:
            run.errors.append(str(exc))
            self._put("error", str(exc))
