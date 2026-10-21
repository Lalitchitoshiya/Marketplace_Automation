"""Recommendation rule (data-contracts.md §5): BLOCKER FAIL > ERROR > MAJOR FAIL / NEEDS_REVIEW > approve."""

from mta.config import MtaConfig
from mta.models import CheckResult, Recommendation, Severity, Status


def label(result: CheckResult) -> str:
    """'SIG-003 FAIL (BLOCKER)', with the host version and subject when they narrow it down."""
    text = f"{result.check_id} {result.status} ({result.severity})"
    if result.target.host_version is not None:
        text += f" on AutoCAD {result.target.host_version}"
    if result.target.subject != "package":
        text += f" [{result.target.subject}]"
    return text


def _labels(results: list[CheckResult]) -> list[str]:
    return list(dict.fromkeys(label(r) for r in results))


def recommend(results: list[CheckResult], cfg: MtaConfig) -> tuple[Recommendation, list[str]]:
    blockers = [r for r in results if r.status is Status.FAIL and r.severity is Severity.BLOCKER]
    if blockers:
        return Recommendation.REJECT, _labels(blockers)
    errors = [r for r in results if r.status is Status.ERROR]
    if errors and cfg.checks.recommendation.error_means_needs_human:
        return Recommendation.NEEDS_HUMAN, _labels(errors)
    review = [
        r
        for r in results
        if (r.status is Status.FAIL and r.severity is Severity.MAJOR) or r.status is Status.NEEDS_REVIEW
    ]
    if review:
        return Recommendation.NEEDS_HUMAN, _labels(review)
    return Recommendation.APPROVE, []
