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

    if begin_dt > now:
        return CheckResult(name, Status.FAIL, f"BeginningDateTime is in the future: {begin_str}")

    if end_str:
        try:
            end_dt = dateutil_parser.isoparse(end_str)
        except Exception:
            return CheckResult(name, Status.FAIL, f"EndingDateTime not valid ISO8601: {end_str!r}")

        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        if begin_dt > end_dt:
            return CheckResult(
                name, Status.FAIL,
                f"BeginningDateTime ({begin_str}) is after EndingDateTime ({end_str})",
            )

    return CheckResult(name, Status.PASS, "Temporal extent is valid")


def check_spatial_validity(granule) -> CheckResult:
    name = "Spatial Validity"
    spatial = granule.get("umm", {}).get("SpatialExtent")
    if not spatial:
        return CheckResult(name, Status.WARN, "SpatialExtent absent — cannot validate")

    geom = spatial.get("HorizontalSpatialDomain", {}).get("Geometry", {})
    if not geom:
        return CheckResult(name, Status.WARN, "No Geometry found in SpatialExtent")

    errors = []

    if "BoundingRectangles" in geom:
        for i, r in enumerate(geom["BoundingRectangles"]):
            west = r.get("WestBoundingCoordinate", 0)
            east = r.get("EastBoundingCoordinate", 0)
            north = r.get("NorthBoundingCoordinate", 0)
            south = r.get("SouthBoundingCoordinate", 0)
            if not (-180 <= west <= 180 and -180 <= east <= 180):
                errors.append(f"BoundingRect[{i}]: longitude out of range")
            if not (-90 <= south <= 90 and -90 <= north <= 90):
                errors.append(f"BoundingRect[{i}]: latitude out of range")
            if south > north:
                errors.append(f"BoundingRect[{i}]: south > north")

    if "GPolygons" in geom:
        for i, poly in enumerate(geom["GPolygons"]):
            pts = poly.get("Boundary", {}).get("Points", [])
            for j, p in enumerate(pts):
                lat, lon = p.get("Latitude", 0), p.get("Longitude", 0)
                if not (-90 <= lat <= 90):
                    errors.append(f"GPolygon[{i}] point[{j}]: latitude {lat} out of range")
                if not (-180 <= lon <= 180):
                    errors.append(f"GPolygon[{i}] point[{j}]: longitude {lon} out of range")
            if pts and (pts[0] != pts[-1]):
                errors.append(f"GPolygon[{i}]: polygon is not closed (first != last point)")

    if errors:
        return CheckResult(name, Status.FAIL, f"{len(errors)} spatial error(s) found", {"errors": errors})

    return CheckResult(name, Status.PASS, "Spatial extent coordinates are valid")


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


def check_file_availability(granule) -> CheckResult:
    name = "File Availability"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            links = granule.data_links()
        except Exception:
            links = []

    if not links:
        # Fall back to raw RelatedUrls
        related = granule.get("umm", {}).get("RelatedUrls", [])
        links = [u["URL"] for u in related if u.get("Type") in ("GET DATA", "GET DATA VIA DIRECT ACCESS")]

    if not links:
        return CheckResult(name, Status.FAIL, "No download URLs found")

    return CheckResult(name, Status.PASS, f"{len(links)} download URL(s) present", {"urls": links[:3]})


def check_file_size_sanity(granule) -> CheckResult:
    name = "File Size Sanity"
    info_list = (
        granule.get("umm", {})
        .get("DataGranule", {})
        .get("ArchiveAndDistributionInformation", [])
    )

    if not info_list:
        return CheckResult(name, Status.WARN, "No ArchiveAndDistributionInformation entries found")

    zero_files = []
    tiny_files = []
    for entry in info_list:
        fname = entry.get("Name", "unknown")
        size_bytes = entry.get("SizeInBytes")
        size_mb = entry.get("Size")

        size_unit = entry.get("SizeUnit", "").upper()

        if size_bytes is not None:
            if size_bytes == 0:
                zero_files.append(fname)
            elif size_bytes < 1024:
                tiny_files.append(f"{fname} ({size_bytes} B)")
        elif size_mb is not None:
            # Normalise to bytes for comparison based on declared unit
            unit_to_bytes = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
            multiplier = unit_to_bytes.get(size_unit, 1024**2)  # default assume MB
            size_in_bytes = size_mb * multiplier
            if size_in_bytes == 0:
                zero_files.append(fname)
            elif size_in_bytes < 1024:
                tiny_files.append(f"{fname} ({size_mb} {size_unit or 'MB'})")

    if zero_files:
        return CheckResult(name, Status.FAIL, f"Zero-size files: {', '.join(zero_files)}")
    if tiny_files:
        return CheckResult(name, Status.WARN, f"Suspiciously small files (<1KB): {', '.join(tiny_files)}")

    return CheckResult(name, Status.PASS, f"File size(s) look reasonable ({len(info_list)} file(s))")


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
