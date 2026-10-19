"""CheckResult: the outcome of one check on one target, always with evidence (Constitution §2)."""

from typing import Self

from pydantic import Field, model_validator

from mta.models.common import CheckId, HostId, Model, Severity, Source, Status


class CheckTarget(Model):
    run_id: str | None = None  # None for static checks
    host_id: HostId | None = None
    host_version: int | None = None
    subject: str  # e.g. "package", "command:ACME_DIMALL", "file:Contents/MyTools.dll"


class Evidence(Model):
    kind: str  # an ArtifactKind value or "excerpt"
    ref: str | None = None  # "sha256:<hash>" of a stored artifact
    excerpt: str | None = None

    @model_validator(mode="after")
    def _needs_ref_or_excerpt(self) -> Self:
        if self.ref is None and self.excerpt is None:
            raise ValueError("evidence needs a ref or an excerpt")
        return self


class CheckResult(Model):
    check_id: CheckId
    target: CheckTarget
    status: Status
    severity: Severity
    source: Source
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    message: str
    evidence: list[Evidence] = Field(default_factory=list)
    remediation: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _enforce_contract_rules(self) -> Self:
        # Constitution §2: every FAIL / NEEDS_REVIEW / WARN carries evidence.
        if self.status in (Status.FAIL, Status.NEEDS_REVIEW, Status.WARN) and not self.evidence:
            raise ValueError(f"{self.check_id}: {self.status} requires evidence")
        # Constitution §7: AI checks never produce a blocking FAIL.
        if self.source is Source.AI and self.status is Status.FAIL:
            raise ValueError(f"{self.check_id}: AI checks may not emit FAIL")
        return self
