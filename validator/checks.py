"""Per-granule validation functions, each returning a CheckResult."""

import collections
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import earthaccess
import requests
from astral import LocationInfo
from astral.sun import elevation as sun_elevation
from dateutil import parser as dateutil_parser


class Status(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    check_name: str
    status: Status
    message: str
    details: dict[str, Any] = field(default_factory=dict)


# ── helpers ───────────────────────────────────────────────────────────────────

_EPOCH_PLACEHOLDERS = frozenset({
    "1970-01-01t00:00:00z",
    "1970-01-01t00:00:00",
    "1970-01-01",
    "0001-01-01t00:00:00z",
    "0001-01-01",
})


def _is_epoch_placeholder(dt_str: str) -> bool:
    """Return True if *dt_str* matches a known pipeline-default sentinel value."""
    return dt_str.strip().lower() in _EPOCH_PLACEHOLDERS


def _get_beginning_datetime_str(umm: dict) -> str | None:
    """Return the beginning datetime string from RangeDateTime or SingleDateTime."""
    te = umm.get("TemporalExtent", {})
    return (
        te.get("RangeDateTime", {}).get("BeginningDateTime")
        or te.get("SingleDateTime")
    )


def _get_centroid(granule) -> tuple[float, float]:
    """Return (lat, lon) centroid from the granule's bounding geometry."""
    geom = (
        granule.get("umm", {})
        .get("SpatialExtent", {})
        .get("HorizontalSpatialDomain", {})
        .get("Geometry", {})
    )
    if "BoundingRectangles" in geom:
        r = geom["BoundingRectangles"][0]
        lat = (r["NorthBoundingCoordinate"] + r["SouthBoundingCoordinate"]) / 2
        lon = (r["EastBoundingCoordinate"] + r["WestBoundingCoordinate"]) / 2
        return lat, lon
    if "GPolygons" in geom:
        pts = geom["GPolygons"][0]["Boundary"]["Points"]
        lat = sum(p["Latitude"] for p in pts) / len(pts)
        lon = sum(p["Longitude"] for p in pts) / len(pts)
        return lat, lon
    if "Points" in geom:
        pts = geom["Points"]
        lat = sum(p["Latitude"] for p in pts) / len(pts)
        lon = sum(p["Longitude"] for p in pts) / len(pts)
        return lat, lon
    raise ValueError("Cannot compute centroid: no supported geometry type found")


def _human_size(size_bytes: float) -> str:
    """Convert a byte count to a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{int(size_bytes)} B" if unit == "B" else f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


# ── individual checks ─────────────────────────────────────────────────────────

def check_schema_completeness(granule) -> CheckResult:
    """Verify required top-level UMM-G fields are present."""
    name = "Schema Completeness"
    umm = granule.get("umm", {})
    required = ["GranuleUR", "TemporalExtent", "DataGranule", "RelatedUrls"]
    missing = [k for k in required if k not in umm]

    if missing:
        return CheckResult(
            name, Status.FAIL,
            f"Missing required UMM fields: {', '.join(missing)}",
        )
    if "SpatialExtent" not in umm:
        return CheckResult(
            name, Status.WARN,
            "SpatialExtent absent (some collections legitimately omit it)",
        )
    return CheckResult(name, Status.PASS, "All required UMM fields present")


def check_temporal_validity(granule) -> CheckResult:
    """Verify that the temporal extent is well-formed, non-epoch, and not future-dated."""
    name = "Temporal Validity"
    umm = granule.get("umm", {})
    te = umm.get("TemporalExtent", {})
    if not te:
        return CheckResult(name, Status.FAIL, "TemporalExtent missing or malformed")

    rdt = te.get("RangeDateTime", {})
    begin_str = rdt.get("BeginningDateTime") or te.get("SingleDateTime")
    end_str = rdt.get("EndingDateTime")

    if begin_str is None:
        return CheckResult(
            name, Status.FAIL,
            "TemporalExtent has neither RangeDateTime.BeginningDateTime nor SingleDateTime",
        )

    if not begin_str:
        return CheckResult(name, Status.FAIL, "BeginningDateTime is missing")

    if _is_epoch_placeholder(begin_str):
        return CheckResult(
            name, Status.FAIL,
            f"BeginningDateTime is a placeholder/epoch value: {begin_str!r}"
            " — likely a pipeline default",
            {"beginning_datetime": begin_str},
        )

    try:
        begin_dt = dateutil_parser.isoparse(begin_str)
    except Exception:
        return CheckResult(
            name, Status.FAIL,
            f"BeginningDateTime not valid ISO8601: {begin_str!r}",
        )

    now = datetime.now(tz=timezone.utc)
    if begin_dt.tzinfo is None:
        begin_dt = begin_dt.replace(tzinfo=timezone.utc)

    details: dict = {"beginning_datetime": begin_str}

    if begin_dt > now:
        return CheckResult(
            name, Status.FAIL,
            f"BeginningDateTime is in the future: {begin_str}",
            details,
        )

    if end_str:
        details["ending_datetime"] = end_str

        if _is_epoch_placeholder(end_str):
            return CheckResult(
                name, Status.FAIL,
                f"EndingDateTime is a placeholder/epoch value: {end_str!r}"
                " — likely a pipeline default",
                details,
            )

        try:
            end_dt = dateutil_parser.isoparse(end_str)
        except Exception:
            return CheckResult(
                name, Status.FAIL,
                f"EndingDateTime not valid ISO8601: {end_str!r}",
                details,
            )

        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        duration_days = (end_dt - begin_dt).total_seconds() / 86400
        details["duration_days"] = round(duration_days, 4)

        if begin_dt > end_dt:
            return CheckResult(
                name, Status.FAIL,
                f"BeginningDateTime ({begin_str}) is after EndingDateTime ({end_str})",
                details,
            )

    return CheckResult(name, Status.PASS, "Temporal extent is valid", details)


def check_spatial_validity(granule) -> CheckResult:
    """Verify that spatial coordinates are within valid ranges and polygons are closed."""
    name = "Spatial Validity"
    spatial = granule.get("umm", {}).get("SpatialExtent")
    if not spatial:
        return CheckResult(name, Status.WARN, "SpatialExtent absent — cannot validate")

    geom = spatial.get("HorizontalSpatialDomain", {}).get("Geometry", {})
    if not geom:
        return CheckResult(name, Status.WARN, "No Geometry found in SpatialExtent")

    errors: list[str] = []
    warnings_list: list[str] = []
    details: dict = {
        "geometry_type": ", ".join(
            k for k in ("BoundingRectangles", "GPolygons", "Points") if k in geom
        )
    }

    if "BoundingRectangles" in geom:
        rects = geom["BoundingRectangles"]
        details["bounding_rectangles"] = len(rects)
        for i, r in enumerate(rects):
            west = r.get("WestBoundingCoordinate", 0)
            east = r.get("EastBoundingCoordinate", 0)
            north = r.get("NorthBoundingCoordinate", 0)
            south = r.get("SouthBoundingCoordinate", 0)
            details[f"rect_{i}"] = f"W:{west} E:{east} S:{south} N:{north}"
            if not (-180 <= west <= 180 and -180 <= east <= 180):
                errors.append(f"BoundingRect[{i}]: longitude out of range")
            if not (-90 <= south <= 90 and -90 <= north <= 90):
                errors.append(f"BoundingRect[{i}]: latitude out of range")
            if south > north:
                errors.append(f"BoundingRect[{i}]: south > north")
            if west >= east:
                # Antimeridian-crossing granules legitimately have west > east.
                warnings_list.append(
                    f"BoundingRect[{i}]: west ({west}) >= east ({east})"
                    " — inverted box or antimeridian crossing"
                )

    if "GPolygons" in geom:
        polys = geom["GPolygons"]
        details["polygons"] = len(polys)
        total_points = 0
        for i, poly in enumerate(polys):
            pts = poly.get("Boundary", {}).get("Points", [])
            total_points += len(pts)
            for j, p in enumerate(pts):
                lat, lon = p.get("Latitude", 0), p.get("Longitude", 0)
                if not (-90 <= lat <= 90):
                    errors.append(
                        f"GPolygon[{i}] point[{j}]: latitude {lat} out of range"
                    )
                if not (-180 <= lon <= 180):
                    errors.append(
                        f"GPolygon[{i}] point[{j}]: longitude {lon} out of range"
                    )
            if pts and pts[0] != pts[-1]:
                errors.append(
                    f"GPolygon[{i}]: polygon is not closed (first != last point)"
                )
        details["polygon_points"] = total_points

    if errors:
        details["errors"] = errors
        if warnings_list:
            details["warnings"] = warnings_list
        return CheckResult(
            name, Status.FAIL, f"{len(errors)} spatial error(s) found", details
        )

    if warnings_list:
        details["warnings"] = warnings_list
        return CheckResult(name, Status.WARN, warnings_list[0], details)

    return CheckResult(
        name, Status.PASS, "Spatial extent coordinates are valid", details
    )


def check_daynight_consistency(granule) -> CheckResult:
    """Verify that DayNightFlag matches the computed sun elevation at acquisition time."""
    name = "Day/Night Consistency"
    umm = granule.get("umm", {})
    # DayNightFlag lives under DataGranule in most granules; top-level is a fallback.
    flag = (
        umm.get("DataGranule", {}).get("DayNightFlag")
        or umm.get("DayNightFlag")
        or "Unspecified"
    )

    if flag == "Unspecified":
        return CheckResult(name, Status.WARN, "DayNightFlag is 'Unspecified' — cannot verify")
    if flag not in ("Day", "Night", "Both"):
        return CheckResult(name, Status.WARN, f"Unrecognised DayNightFlag value: {flag!r}")
    if flag == "Both":
        return CheckResult(name, Status.PASS, "DayNightFlag is 'Both' — no single-value check needed")

    try:
        lat, lon = _get_centroid(granule)
    except Exception as e:
        return CheckResult(
            name, Status.WARN,
            f"Cannot compute centroid for sun-position check: {e}",
        )

    begin_str = _get_beginning_datetime_str(granule.get("umm", {}))
    try:
        if not begin_str:
            raise ValueError("no BeginningDateTime or SingleDateTime")
        obs_time = dateutil_parser.isoparse(begin_str)
        if obs_time.tzinfo is None:
            obs_time = obs_time.replace(tzinfo=timezone.utc)
        else:
            obs_time = obs_time.astimezone(timezone.utc)
    except Exception as e:
        return CheckResult(
            name, Status.WARN,
            f"Cannot parse BeginningDateTime for sun check: {e}",
        )

    try:
        location = LocationInfo(latitude=lat, longitude=lon)
        elev = sun_elevation(location.observer, dateandtime=obs_time)
        expected = "Day" if elev > 0 else "Night"
        details = {
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "obs_time": str(obs_time),
            "sun_elevation_deg": round(elev, 2),
        }
        if flag == expected:
            return CheckResult(
                name, Status.PASS,
                f"Flag '{flag}' matches computed sun position",
                details,
            )
        return CheckResult(
            name, Status.FAIL,
            f"Flag is '{flag}' but sun position indicates '{expected}'",
            details,
        )
    except Exception as e:
        # astral raises at extreme latitudes (polar day/night).
        return CheckResult(name, Status.WARN, f"Sun position check inconclusive: {e}")


def check_url_health(granule, session=None) -> CheckResult:
    """Check that download URLs exist, use HTTPS, have descriptions, and are reachable."""
    name = "URL Health"
    related = granule.get("umm", {}).get("RelatedUrls", [])

    quality_issues: list[str] = []

    has_get_data = any(
        u.get("Type") in ("GET DATA", "GET DATA VIA DIRECT ACCESS")
        for u in related
    )
    if not has_get_data:
        quality_issues.append("No RelatedUrl with Type 'GET DATA' found")

    http_urls = [u["URL"] for u in related if u.get("URL", "").startswith("http://")]
    if http_urls:
        quality_issues.append(
            f"{len(http_urls)} URL(s) use http:// instead of https://:"
            f" {http_urls[0][:80]}"
        )

    no_desc = [u.get("URL", "")[:60] for u in related if not u.get("Description", "").strip()]
    if no_desc:
        quality_issues.append(f"{len(no_desc)} RelatedUrl(s) missing a Description")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            links = granule.data_links()
        except Exception:
            links = []

    if not links:
        links = [
            u["URL"] for u in related
            if u.get("Type") in ("GET DATA", "GET DATA VIA DIRECT ACCESS")
        ]

    if not links:
        details: dict = {}
        if quality_issues:
            details["quality_issues"] = quality_issues
        return CheckResult(name, Status.FAIL, "No download URLs found", details)

    url = links[0]

    # S3 direct-access URLs cannot be probed over HTTP — presence alone is sufficient.
    if url.startswith("s3://"):
        s3_details: dict = {"urls": links}
        if quality_issues:
            s3_details["quality_issues"] = quality_issues
        status = Status.WARN if quality_issues else Status.PASS
        msg = f"{len(links)} URL(s) found (S3 direct access)"
        if quality_issues:
            msg += f"; {len(quality_issues)} quality issue(s)"
        return CheckResult(name, status, msg, s3_details)

    if session is None:
        session = earthaccess.get_requests_https_session()

    def _probe(verify_ssl: bool) -> int:
        resp = session.head(url, timeout=8, allow_redirects=True, verify=verify_ssl)
        if resp.status_code == 405:
            resp = session.get(url, timeout=8, stream=True, verify=verify_ssl)
            resp.close()
        return resp.status_code

    ssl_warning = None
    try:
        code = _probe(verify_ssl=True)
    except requests.exceptions.SSLError:
        # NASA Earthdata Cloud CDN sometimes presents a self-signed intermediate cert.
        # Retry without verification to distinguish a reachable file from a real cert failure.
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                code = _probe(verify_ssl=False)
            ssl_warning = "SSL certificate could not be verified (self-signed CDN cert)"
        except Exception as exc:
            exc_summary = str(exc).splitlines()[0][:120]
            probe_fail: dict = {"probed_url": url, "urls": links}
            if quality_issues:
                probe_fail["quality_issues"] = quality_issues
            return CheckResult(
                name, Status.WARN,
                f"{len(links)} URL(s) found but health probe failed: {exc_summary}",
                probe_fail,
            )
    except Exception as exc:
        exc_summary = str(exc).splitlines()[0][:120]
        probe_fail = {"probed_url": url, "urls": links}
        if quality_issues:
            probe_fail["quality_issues"] = quality_issues
        return CheckResult(
            name, Status.WARN,
            f"{len(links)} URL(s) found but health probe failed: {exc_summary}",
            probe_fail,
        )

    details = {"probed_url": url, "http_status": code, "urls": links}
    if ssl_warning:
        details["ssl_note"] = ssl_warning
    if quality_issues:
        details["quality_issues"] = quality_issues

    if 200 <= code < 300:
        if quality_issues:
            return CheckResult(
                name, Status.WARN,
                f"{len(links)} URL(s) found; first URL reachable (HTTP {code});"
                f" {len(quality_issues)} quality issue(s)",
                details,
            )
        return CheckResult(
            name, Status.PASS,
            f"{len(links)} URL(s) found; first URL reachable (HTTP {code})",
            details,
        )
    if code in (401, 403):
        return CheckResult(
            name, Status.WARN,
            f"URL access restricted (HTTP {code}) — may require different credentials",
            details,
        )
    if code == 404:
        return CheckResult(name, Status.FAIL, "URL not found (HTTP 404)", details)
    return CheckResult(
        name, Status.WARN, f"URL returned unexpected HTTP {code}", details
    )


def check_file_size_sanity(granule) -> CheckResult:
    """Verify that no files in ArchiveAndDistributionInformation are zero-byte or tiny."""
    name = "File Size Sanity"
    info_list = (
        granule.get("umm", {})
        .get("DataGranule", {})
        .get("ArchiveAndDistributionInformation", [])
    )

    if not info_list:
        return CheckResult(
            name, Status.WARN,
            "No ArchiveAndDistributionInformation entries found",
        )

    zero_files = []
    tiny_files = []
    file_sizes = {}

    for entry in info_list:
        fname = entry.get("Name", "unknown")
        size_bytes = entry.get("SizeInBytes")
        size_mb = entry.get("Size")
        size_unit = entry.get("SizeUnit", "").upper()

        if size_bytes is not None:
            file_sizes[fname] = _human_size(size_bytes)
            if size_bytes == 0:
                zero_files.append(fname)
            elif size_bytes < 1024:
                tiny_files.append(fname)
        elif size_mb is not None:
            unit_to_bytes = {
                "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4
            }
            multiplier = unit_to_bytes.get(size_unit, 1024 ** 2)
            size_in_bytes = size_mb * multiplier
            file_sizes[fname] = _human_size(size_in_bytes)
            if size_in_bytes == 0:
                zero_files.append(fname)
            elif size_in_bytes < 1024:
                tiny_files.append(fname)
        else:
            file_sizes[fname] = "size unknown"

    details = {"files": [f"{n}: {s}" for n, s in file_sizes.items()]}

    if zero_files:
        return CheckResult(
            name, Status.FAIL,
            f"Zero-size file(s): {', '.join(zero_files)}",
            details,
        )
    if tiny_files:
        return CheckResult(
            name, Status.WARN,
            f"Suspiciously small file(s) (<1 KB): {', '.join(tiny_files)}",
            details,
        )
    return CheckResult(
        name, Status.PASS,
        f"{len(info_list)} file(s) — sizes look reasonable",
        details,
    )


def check_production_date_sanity(granule) -> CheckResult:
    """Verify ProductionDateTime is present, not an epoch, and not before acquisition."""
    name = "Production Date Sanity"
    umm = granule.get("umm", {})

    prod_str = umm.get("DataGranule", {}).get("ProductionDateTime")
    if not prod_str:
        return CheckResult(name, Status.WARN, "ProductionDateTime is absent — cannot verify")

    try:
        prod_dt = dateutil_parser.isoparse(prod_str)
    except Exception:
        return CheckResult(
            name, Status.FAIL,
            f"ProductionDateTime not valid ISO8601: {prod_str!r}",
        )

    if prod_dt.tzinfo is None:
        prod_dt = prod_dt.replace(tzinfo=timezone.utc)

    if _is_epoch_placeholder(prod_str):
        return CheckResult(
            name, Status.FAIL,
            f"ProductionDateTime is a placeholder/epoch value: {prod_str!r}"
            " — likely a pipeline default",
        )

    begin_str = _get_beginning_datetime_str(umm)
    try:
        if not begin_str:
            raise ValueError("no BeginningDateTime or SingleDateTime")
        begin_dt = dateutil_parser.isoparse(begin_str)
        if begin_dt.tzinfo is None:
            begin_dt = begin_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return CheckResult(
            name, Status.WARN,
            "BeginningDateTime unavailable — cannot compare against ProductionDateTime",
            {"production_datetime": prod_str},
        )

    details = {
        "production_datetime": prod_str,
        "beginning_datetime": begin_str,
    }

    if prod_dt < begin_dt:
        return CheckResult(
            name, Status.FAIL,
            f"ProductionDateTime ({prod_str}) is before BeginningDateTime ({begin_str})"
            " — data cannot be produced before it was collected",
            details,
        )

    now = datetime.now(tz=timezone.utc)
    if prod_dt > now:
        return CheckResult(
            name, Status.FAIL,
            f"ProductionDateTime is in the future: {prod_str}",
            details,
        )

    return CheckResult(
        name, Status.PASS,
        "ProductionDateTime is after acquisition and not in the future",
        details,
    )


def check_collection_reference(
    granule, expected_short_name: str, expected_entry_title: str = ""
) -> CheckResult:
    """Verify CollectionReference matches the selected collection."""
    name = "Collection Reference"
    ref = granule.get("umm", {}).get("CollectionReference", {})
    if not ref:
        return CheckResult(name, Status.FAIL, "CollectionReference field is missing")

    short_name = ref.get("ShortName", "")
    entry_title = ref.get("EntryTitle", "")

    if not short_name and not entry_title:
        return CheckResult(
            name, Status.FAIL,
            "CollectionReference has neither ShortName nor EntryTitle",
        )

    if short_name:
        if short_name.upper() != expected_short_name.upper():
            return CheckResult(
                name, Status.FAIL,
                f"CollectionReference ShortName '{short_name}' does not match"
                f" expected '{expected_short_name}'",
            )
        return CheckResult(
            name, Status.PASS,
            f"CollectionReference ShortName matches '{expected_short_name}'",
        )

    # Granule uses EntryTitle only (valid per UMM-G spec).
    if not expected_entry_title:
        return CheckResult(
            name, Status.WARN,
            f"CollectionReference uses EntryTitle only: '{entry_title[:80]}'"
            " — no EntryTitle to compare against",
        )
    if entry_title.lower() != expected_entry_title.lower():
        return CheckResult(
            name, Status.FAIL,
            f"CollectionReference EntryTitle '{entry_title[:80]}' does not match expected",
        )
    return CheckResult(name, Status.PASS, "CollectionReference EntryTitle matches")


def check_duplicate_detection(granules: list) -> list[CheckResult]:
    """Return one CheckResult per granule — FAIL for duplicate concept-ids, PASS otherwise."""
    name = "Duplicate Detection"
    id_counts = collections.Counter(
        g.get("meta", {}).get("concept-id", "") for g in granules
    )
    results = []
    for g in granules:
        cid = g.get("meta", {}).get("concept-id", "")
        if id_counts[cid] > 1:
            results.append(
                CheckResult(name, Status.FAIL, f"Duplicate concept-id: {cid}")
            )
        else:
            results.append(CheckResult(name, Status.PASS, "Unique granule in sample"))
    return results
