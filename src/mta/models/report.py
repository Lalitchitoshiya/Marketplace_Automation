"""report.json: the job-level result handed to the reviewer."""

from typing import Literal

from pydantic import Field

from mta.models.common import ArtifactKind, HostId, Model, Recommendation, Sha256, UiMode
from mta.models.results import CheckResult
from mta.models.submission import Submission


class StatusSummary(Model):
    pass_: int = Field(default=0, ge=0, alias="pass")
    fail: int = Field(default=0, ge=0)
    warn: int = Field(default=0, ge=0)
    needs_review: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    error: int = Field(default=0, ge=0)


class MatrixEntry(Model):
    host_id: HostId
    host_version: int
    ui_mode: UiMode
    summary: StatusSummary


class Inventory(Model):
    components: list[dict[str, object]] = Field(default_factory=list)
    commands: list[dict[str, object]] = Field(default_factory=list)
    ui: list[dict[str, object]] = Field(default_factory=list)
    network: list[dict[str, object]] = Field(default_factory=list)
    files_written: list[dict[str, object]] = Field(default_factory=list)


class ArtifactEntry(Model):
    sha256: Sha256
    kind: ArtifactKind
    path: str
    run_id: str | None = None


class MtaInfo(Model):
    version: str
    config_sha256: Sha256
    duration_ms: int = Field(ge=0)


class Report(Model):
    report_version: Literal[1] = 1
    job_id: str
    submission: Submission
    recommendation: Recommendation
    recommendation_reasons: list[str] = Field(default_factory=list)
    matrix: list[MatrixEntry] = Field(default_factory=list)
    results: list[CheckResult] = Field(default_factory=list)
    inventory: Inventory = Field(default_factory=Inventory)
    artifacts: list[ArtifactEntry] = Field(default_factory=list)
    mta: MtaInfo
