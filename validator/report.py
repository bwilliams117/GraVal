import csv
import datetime
import json
from pathlib import Path

from .checks import Status
from .runner import ValidationRun


def export_csv(run: ValidationRun, output_path: Path) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["granule_ur", "concept_id", "check_name", "status", "message", "details"])
        for report in run.granule_reports:
            for check in report.checks:
                writer.writerow([
                    report.granule_ur,
                    report.concept_id,
                    check.check_name,
                    check.status.value,
                    check.message,
                    json.dumps(check.details) if check.details else "",
                ])


def export_summary_text(run: ValidationRun) -> str:
    lines = [
        f"Collection: {run.collection_short_name}",
        f"Sample size: {len(run.granule_reports)} granule(s)",
        f"Results: {run.pass_count} PASS  |  {run.warn_count} WARN  |  {run.fail_count} FAIL",
        "",
    ]
    for report in run.granule_reports:
        status_str = report.overall_status.value
        lines.append(f"  [{status_str:4}] {report.granule_ur}")
        for check in report.checks:
            symbol = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}.get(check.status.value, "?")
            lines.append(f"         {symbol} {check.check_name}: {check.message}")
        lines.append("")

    if run.errors:
        lines.append("Errors encountered:")
        for err in run.errors:
            lines.append(f"  - {err}")

    return "\n".join(lines)


def default_report_path(collection_short_name: str, run: "ValidationRun | None" = None) -> Path:
    timestamp = datetime.datetime.now().strftime("%Y%m%d")
    if run is not None:
        n = len(run.granule_reports)
        summary = f"{n}g_{run.pass_count}P_{run.warn_count}W_{run.fail_count}F"
        filename = f"{collection_short_name}_validation_{summary}_{timestamp}.csv"
    else:
        filename = f"{collection_short_name}_validation_{timestamp}.csv"
    return Path.home() / "Desktop" / filename
