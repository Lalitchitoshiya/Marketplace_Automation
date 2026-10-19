from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from mta.models import (
    CheckResult,
    CheckTarget,
    Evidence,
    PackageKind,
    PackageRef,
    Severity,
    Source,
    Status,
    Submission,
)

SHA = "a" * 64


def _submission(**overrides: object) -> Submission:
    data: dict[str, object] = {
        "submission_id": "sub-1",
        "app_id": "acme.tools",
        "app_version": "1.0.0",
        "package": PackageRef(filename="t.msi", sha256=SHA, size_bytes=1, kind=PackageKind.MSI),
        "received_at": datetime(2026, 10, 19, tzinfo=UTC),
    }
    data.update(overrides)
    return Submission.model_validate(data)


def _result(**overrides: object) -> CheckResult:
    data: dict[str, object] = {
        "check_id": "CMD-002",
        "target": CheckTarget(subject="command:X"),
        "status": Status.PASS,
        "severity": Severity.BLOCKER,
        "source": Source.DYNAMIC,
        "message": "ok",
    }
    data.update(overrides)
    return CheckResult.model_validate(data)


def test_submission_round_trips_through_json() -> None:
    sub = _submission()
    assert Submission.model_validate_json(sub.model_dump_json()) == sub


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        _submission(unexpected="x")


def test_sha256_must_be_lowercase_hex() -> None:
    with pytest.raises(ValidationError):
        PackageRef(filename="t.msi", sha256="XYZ", size_bytes=1, kind=PackageKind.MSI)


@pytest.mark.parametrize("check_id", ["CMD-002", "MAYA-001", "AI-003"])
def test_valid_check_ids(check_id: str) -> None:
    assert _result(check_id=check_id).check_id == check_id


@pytest.mark.parametrize("check_id", ["cmd-002", "CMD-2", "CMD002", "TOOLONG-001"])
def test_invalid_check_ids(check_id: str) -> None:
    with pytest.raises(ValidationError):
        _result(check_id=check_id)


@pytest.mark.parametrize("status", [Status.FAIL, Status.WARN, Status.NEEDS_REVIEW])
def test_findings_require_evidence(status: Status) -> None:
    with pytest.raises(ValidationError, match="requires evidence"):
        _result(status=status)
    assert _result(status=status, evidence=[Evidence(kind="excerpt", excerpt="boom")]).status is status


def test_ai_checks_cannot_fail() -> None:
    with pytest.raises(ValidationError, match="AI checks may not emit FAIL"):
        _result(source=Source.AI, status=Status.FAIL, evidence=[Evidence(kind="excerpt", excerpt="x")])


def test_evidence_needs_ref_or_excerpt() -> None:
    with pytest.raises(ValidationError, match="ref or an excerpt"):
        Evidence(kind="log")
