"""Job (one MTA execution for a submission) and Run (one host x version execution unit)."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from mta.models.common import HostId, Model, Sha256, UiMode


class JobState(StrEnum):
    RECEIVED = "RECEIVED"
    STATIC_ANALYSIS = "STATIC_ANALYSIS"
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    AGGREGATING = "AGGREGATING"
    REPORTED = "REPORTED"
    FAILED = "FAILED"


class RunState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class SandboxKind(StrEnum):
    LOCAL = "local"
    HYPERV = "hyperv"


class Sandbox(Model):
    kind: SandboxKind = SandboxKind.LOCAL
    image: str | None = None


class Job(Model):
    job_id: str
    submission_id: str
    state: JobState = JobState.RECEIVED
    config_snapshot_sha256: Sha256
    runs: list[str] = Field(default_factory=list)
    rerun_of: str | None = None
    created_at: datetime


class Run(Model):
    run_id: str
    job_id: str
    host_id: HostId
    host_version: int
    ui_mode: UiMode = UiMode.HEADLESS
    sandbox: Sandbox = Field(default_factory=Sandbox)
    state: RunState = RunState.PENDING
    started_at: datetime | None = None
    ended_at: datetime | None = None
