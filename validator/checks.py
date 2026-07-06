import collections
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

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


# ── helpers ──────────────────────────────────────────────────────────────────

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


# ── individual checks ────────────────────────────────────────────────────────

def check_schema_completeness(granule) -> CheckResult:
    name = "Schema Completeness"
    umm = granule.get("umm", {})
    required = ["GranuleUR", "TemporalExtent", "DataGranule", "RelatedUrls"]
    missing = [k for k in required if k not in umm]

    if missing:
        return CheckResult(name, Status.FAIL, f"Missing required UMM fields: {', '.join(missing)}")

    if "SpatialExtent" not in umm:
        return CheckResult(name, Status.WARN, "SpatialExtent absent (some collections legitimately omit it)")

    return CheckResult(name, Status.PASS, "All required UMM fields present")


def check_temporal_validity(granule) -> CheckResult:
    name = "Temporal Validity"
    try:
        rdt = granule["umm"]["TemporalExtent"]["RangeDateTime"]
        begin_str = rdt.get("BeginningDateTime")
        end_str = rdt.get("EndingDateTime")
    except (KeyError, TypeError):
        return CheckResult(name, Status.FAIL, "TemporalExtent.RangeDateTime missing or malformed")

    if not begin_str:
        return CheckResult(name, Status.FAIL, "BeginningDateTime is missing")

    try:
        begin_dt = dateutil_parser.isoparse(begin_str)
    except Exception:
        return CheckResult(name, Status.FAIL, f"BeginningDateTime not valid ISO8601: {begin_str!r}")

    now = datetime.now(tz=timezone.utc)
    if begin_dt.tzinfo is None:
        begin_dt = begin_dt.replace(tzinfo=timezone.utc)

    details: dict = {"beginning_datetime": begin_str}

    if begin_dt > now:
        return CheckResult(name, Status.FAIL, f"BeginningDateTime is in the future: {begin_str}", details)

    if end_str:
        details["ending_datetime"] = end_str
        try:
            end_dt = dateutil_parser.isoparse(end_str)
        except Exception:
            return CheckResult(name, Status.FAIL, f"EndingDateTime not valid ISO8601: {end_str!r}", details)

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
    name = "Spatial Validity"
    spatial = granule.get("umm", {}).get("SpatialExtent")
    if not spatial:
        return CheckResult(name, Status.WARN, "SpatialExtent absent — cannot validate")

    geom = spatial.get("HorizontalSpatialDomain", {}).get("Geometry", {})
    if not geom:
        return CheckResult(name, Status.WARN, "No Geometry found in SpatialExtent")

    errors = []
    details: dict = {"geometry_type": ", ".join(k for k in ("BoundingRectangles", "GPolygons", "Points") if k in geom)}

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
                    errors.append(f"GPolygon[{i}] point[{j}]: latitude {lat} out of range")
                if not (-180 <= lon <= 180):
                    errors.append(f"GPolygon[{i}] point[{j}]: longitude {lon} out of range")
            if pts and (pts[0] != pts[-1]):
                errors.append(f"GPolygon[{i}]: polygon is not closed (first != last point)")
        details["polygon_points"] = total_points

    if errors:
        details["errors"] = errors
        return CheckResult(name, Status.FAIL, f"{len(errors)} spatial error(s) found", details)

    return CheckResult(name, Status.PASS, "Spatial extent coordinates are valid", details)


def check_daynight_consistency(granule) -> CheckResult:
    name = "Day/Night Consistency"
    umm = granule.get("umm", {})
    # DayNightFlag lives under DataGranule in most real granules; top-level is a fallback
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
        return CheckResult(name, Status.WARN, f"Cannot compute centroid for sun-position check: {e}")

    try:
        begin_str = granule["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
        obs_time = dateutil_parser.isoparse(begin_str)
        if obs_time.tzinfo is None:
            obs_time = obs_time.replace(tzinfo=timezone.utc)
        else:
            obs_time = obs_time.astimezone(timezone.utc)
    except Exception as e:
        return CheckResult(name, Status.WARN, f"Cannot parse BeginningDateTime for sun check: {e}")

    try:
        from astral import LocationInfo
        from astral.sun import elevation

        location = LocationInfo(latitude=lat, longitude=lon)
        elev = elevation(location.observer, dateandtime=obs_time)
        is_day = elev > 0
        expected = "Day" if is_day else "Night"

        details = {
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "obs_time": str(obs_time),
            "sun_elevation_deg": round(elev, 2),
        }
        if flag == expected:
            return CheckResult(name, Status.PASS, f"Flag '{flag}' matches computed sun position", details)
        else:
            return CheckResult(
                name, Status.FAIL,
                f"Flag is '{flag}' but sun position indicates '{expected}'",
                details,
            )
    except Exception as e:
        # Polar day/night and other astral edge cases
        return CheckResult(name, Status.WARN, f"Sun position check inconclusive: {e}")


def check_url_health(granule) -> CheckResult:
    name = "URL Health"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            links = granule.data_links()
        except Exception:
            links = []

    if not links:
        related = granule.get("umm", {}).get("RelatedUrls", [])
        links = [u["URL"] for u in related if u.get("Type") in ("GET DATA", "GET DATA VIA DIRECT ACCESS")]

    if not links:
        return CheckResult(name, Status.FAIL, "No download URLs found")

    url = links[0]

    # S3 direct-access URLs cannot be probed via HTTP — presence alone is sufficient
    if url.startswith("s3://"):
        return CheckResult(name, Status.PASS, f"{len(links)} URL(s) found (S3 direct access)", {"urls": links})

    import earthaccess
    import requests

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
        # NASA Earthdata Cloud CDN sometimes presents a self-signed intermediate cert
        # that Python rejects but browsers accept. Retry without verification to
        # distinguish a real SSL/cert problem from a reachable file.
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                code = _probe(verify_ssl=False)
            ssl_warning = "SSL certificate could not be verified (self-signed CDN cert)"
        except Exception as exc:
            exc_summary = str(exc).splitlines()[0][:120]
            return CheckResult(
                name, Status.WARN,
                f"{len(links)} URL(s) found but health probe failed: {exc_summary}",
                {"probed_url": url, "urls": links},
            )
    except Exception as exc:
        exc_summary = str(exc).splitlines()[0][:120]
        return CheckResult(
            name, Status.WARN,
            f"{len(links)} URL(s) found but health probe failed: {exc_summary}",
            {"probed_url": url, "urls": links},
        )

    details = {"probed_url": url, "http_status": code, "urls": links}
    if ssl_warning:
        details["ssl_note"] = ssl_warning

    if 200 <= code < 300:
        # SSL cert issues on NASA's CDN are an infrastructure quirk, not a data problem —
        # the file is reachable, so this is still a PASS.
        return CheckResult(name, Status.PASS, f"{len(links)} URL(s) found; first URL reachable (HTTP {code})", details)
    elif code in (401, 403):
        return CheckResult(name, Status.WARN, f"URL access restricted (HTTP {code}) — may require different credentials", details)
    elif code == 404:
        return CheckResult(name, Status.FAIL, "URL not found (HTTP 404)", details)
    else:
        return CheckResult(name, Status.WARN, f"URL returned unexpected HTTP {code}", details)


def check_file_size_sanity(granule) -> CheckResult:
    name = "File Size Sanity"
    info_list = (
        granule.get("umm", {})
        .get("DataGranule", {})
        .get("ArchiveAndDistributionInformation", [])
    )

    if not info_list:
        return CheckResult(name, Status.WARN, "No ArchiveAndDistributionInformation entries found")

    def _human_size(size_bytes: float) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size_bytes < 1024:
                return f"{size_bytes:.2f} {unit}" if unit != "B" else f"{int(size_bytes)} B"
            size_bytes /= 1024
        return f"{size_bytes:.2f} PB"

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
            unit_to_bytes = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
            multiplier = unit_to_bytes.get(size_unit, 1024**2)
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
        return CheckResult(name, Status.FAIL, f"Zero-size file(s): {', '.join(zero_files)}", details)
    if tiny_files:
        return CheckResult(name, Status.WARN, f"Suspiciously small file(s) (<1 KB): {', '.join(tiny_files)}", details)

    return CheckResult(name, Status.PASS, f"{len(info_list)} file(s) — sizes look reasonable", details)


def check_production_date_sanity(granule) -> CheckResult:
    name = "Production Date Sanity"
    umm = granule.get("umm", {})

    prod_str = umm.get("DataGranule", {}).get("ProductionDateTime")
    if not prod_str:
        return CheckResult(name, Status.WARN, "ProductionDateTime is absent — cannot verify")

    try:
        prod_dt = dateutil_parser.isoparse(prod_str)
    except Exception:
        return CheckResult(name, Status.FAIL, f"ProductionDateTime not valid ISO8601: {prod_str!r}")

    if prod_dt.tzinfo is None:
        prod_dt = prod_dt.replace(tzinfo=timezone.utc)

    # Sentinel: Unix epoch zero is a known pipeline placeholder
    from datetime import timezone as _tz
    epoch = datetime(1970, 1, 1, tzinfo=_tz.utc)
    if prod_dt == epoch:
        return CheckResult(name, Status.FAIL, "ProductionDateTime is Unix epoch (1970-01-01) — likely a pipeline default placeholder")

    try:
        begin_str = umm["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
        begin_dt = dateutil_parser.isoparse(begin_str)
        if begin_dt.tzinfo is None:
            begin_dt = begin_dt.replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, Exception):
        return CheckResult(name, Status.WARN, "BeginningDateTime unavailable — cannot compare against ProductionDateTime",
                           {"production_datetime": prod_str})

    details = {
        "production_datetime": prod_str,
        "beginning_datetime": begin_str,
    }

    if prod_dt < begin_dt:
        return CheckResult(
            name, Status.FAIL,
            f"ProductionDateTime ({prod_str}) is before BeginningDateTime ({begin_str}) — data cannot be produced before it was collected",
            details,
        )

    now = datetime.now(tz=timezone.utc)
    if prod_dt > now:
        return CheckResult(name, Status.FAIL, f"ProductionDateTime is in the future: {prod_str}", details)

    return CheckResult(name, Status.PASS, "ProductionDateTime is after acquisition and not in the future", details)


def check_collection_reference(granule, expected_short_name: str) -> CheckResult:
    name = "Collection Reference"
    ref = granule.get("umm", {}).get("CollectionReference", {})
    if not ref:
        return CheckResult(name, Status.FAIL, "CollectionReference field is missing")

    actual = ref.get("ShortName", "")
    if not actual:
        return CheckResult(name, Status.FAIL, "CollectionReference.ShortName is empty")

    if actual.upper() != expected_short_name.upper():
        return CheckResult(
            name, Status.FAIL,
            f"CollectionReference ShortName '{actual}' does not match expected '{expected_short_name}'",
        )

    return CheckResult(name, Status.PASS, f"CollectionReference matches '{expected_short_name}'")


def check_duplicate_detection(granules: list) -> list[CheckResult]:
    """Returns one CheckResult per granule — FAIL for duplicates, PASS for unique."""
    name = "Duplicate Detection"
    id_counts = collections.Counter(g.get("meta", {}).get("concept-id", "") for g in granules)
    results = []
    for g in granules:
        cid = g.get("meta", {}).get("concept-id", "")
        if id_counts[cid] > 1:
            results.append(CheckResult(name, Status.FAIL, f"Duplicate concept-id: {cid}"))
        else:
            results.append(CheckResult(name, Status.PASS, "Unique granule in sample"))
    return results
