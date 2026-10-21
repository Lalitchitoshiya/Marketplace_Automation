"""Builds and writes report.json (data-contracts.md §4), validated against the committed schema."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from mta import __version__, schemas
from mta.config import MtaConfig
from mta.engine.recommend import recommend
from mta.intake.pipeline import IntakeResult
from mta.models import CheckResult, Job, JobState, Status, Submission
from mta.models.common import UiMode
from mta.models.report import ArtifactEntry, Inventory, MatrixEntry, MtaInfo, Report, StatusSummary
from mta.report.html import render_html, screenshot_uris
from mta.static.stage import StaticOutcome

if TYPE_CHECKING:
    from mta.adapters.autocad.dynamic import DynamicOutcome

_FIELDS = {
    Status.PASS: "pass_",
    Status.FAIL: "fail",
    Status.WARN: "warn",
    Status.NEEDS_REVIEW: "needs_review",
    Status.SKIPPED: "skipped",
    Status.ERROR: "error",
}


class ReportError(Exception):
    """The report does not match its schema: a bug in MTA, never a publisher problem."""


def summarize(results: list[CheckResult]) -> StatusSummary:
    counts = dict.fromkeys(_FIELDS.values(), 0)
    for r in results:
        counts[_FIELDS[r.status]] += 1
    return StatusSummary(**counts)


def matrix(
    results: list[CheckResult], versions: list[int], host_id: str, ui_mode: UiMode
) -> list[MatrixEntry]:
    """One row per version: that version's results plus the results that apply to every version."""
    return [
        MatrixEntry(
            host_id=host_id,
            host_version=year,
            ui_mode=ui_mode,
            summary=summarize([r for r in results if r.target.host_version in (None, year)]),
        )
        for year in sorted(versions)
    ]


def build_report(
    job: Job,
    submission: Submission,
    results: list[CheckResult],
    cfg: MtaConfig,
    *,
    versions: list[int],
    inventory: Inventory,
    artifacts: list[ArtifactEntry],
    duration_ms: int,
    host_id: str = "autocad",
    ui_mode: UiMode = UiMode.HEADLESS,
) -> Report:
    recommendation, reasons = recommend(results, cfg)
    ordered = sorted(results, key=lambda r: (r.check_id, r.target.host_version or 0, r.target.subject))
    return Report(
        job_id=job.job_id,
        submission=submission,
        recommendation=recommendation,
        recommendation_reasons=reasons,
        matrix=matrix(results, versions, host_id, ui_mode),
        results=ordered,
        inventory=inventory,
        artifacts=artifacts,
        mta=MtaInfo(version=__version__, config_sha256=cfg.sha256, duration_ms=duration_ms),
    )


def write_report(report: Report, path: Path) -> dict[str, object]:
    document: dict[str, object] = report.model_dump(mode="json", by_alias=True, exclude_none=True)
    errors = schemas.validate("report", document)
    if errors:
        raise ReportError(f"report.json does not match its schema: {errors[:5]}")
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return document


def write_job_report(
    intake: IntakeResult,
    outcome: StaticOutcome,
    cfg: MtaConfig,
    duration_ms: int,
    dynamic: "DynamicOutcome | None" = None,
) -> Report:
    """report.json and report.html for a finished job (static, plus dynamic results for `mta run`)."""
    job = intake.job.model_copy(update={"state": JobState.REPORTED})
    inventory = outcome.inventory(intake)
    if dynamic is not None:
        by_name: dict[str, dict[str, str]] = {}
        for year, outcomes in dynamic.commands.items():
            for o in outcomes:
                by_name.setdefault(o.name.upper(), {})[str(year)] = o.outcome
        for command in inventory.commands:
            command["outcomes"] = by_name.get(str(command["name"]).upper(), {})
    report = build_report(
        job,
        intake.submission,
        outcome.results + (dynamic.results if dynamic else []),
        cfg,
        versions=outcome.versions(intake),
        inventory=inventory,
        artifacts=intake.artifacts,
        duration_ms=duration_ms,
    )
    document = write_report(report, intake.job_dir / "report.json")
    job_json = job.model_dump(mode="json", by_alias=True, exclude_none=True)
    (intake.job_dir / "job.json").write_text(json.dumps(job_json, indent=2) + "\n", encoding="utf-8")

    kit_root = intake.package.parent.parent
    listing = intake.submission.listing
    screenshots = screenshot_uris(kit_root, listing.screenshots) if listing else []
    sessions = []
    for s in dynamic.sessions if dynamic else []:
        sessions.append({
            "run_id": s.layout.run_id, "run_uri": s.layout.root.as_uri(), "kind": s.kind, "year": s.year,
            "exit": s.console.exit_hex if s.console else None,
            "timed_out": s.console.timed_out if s.console else None,
            "duration_s": round(s.console.duration_s, 1) if s.console else None,
            "clean": s.log.clean, "infra_error": s.infra_error, "notes": s.notes,
        })  # fmt: skip
    html = render_html(document, screenshots=screenshots, sessions=sessions)
    (intake.job_dir / "report.html").write_text(html, encoding="utf-8")
    return report
