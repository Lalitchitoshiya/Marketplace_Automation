"""Data contracts (specs/00-foundation/data-contracts.md).

These models are the normative source of the JSON Schemas in mta.schemas.
"""

from mta.models.common import ArtifactKind, Recommendation, Severity, Source, Status, UiMode
from mta.models.job import Job, JobState, Run, RunState, Sandbox, SandboxKind
from mta.models.report import ArtifactEntry, Inventory, MatrixEntry, MtaInfo, Report, StatusSummary
from mta.models.results import CheckResult, CheckTarget, Evidence
from mta.models.submission import (
    DocumentRef,
    Feature,
    Listing,
    PackageKind,
    PackageRef,
    ProductDecl,
    Submission,
    TestHints,
)

__all__ = [
    "ArtifactEntry",
    "ArtifactKind",
    "CheckResult",
    "CheckTarget",
    "DocumentRef",
    "Evidence",
    "Feature",
    "Inventory",
    "Job",
    "JobState",
    "Listing",
    "MatrixEntry",
    "MtaInfo",
    "PackageKind",
    "PackageRef",
    "ProductDecl",
    "Recommendation",
    "Report",
    "Run",
    "RunState",
    "Sandbox",
    "SandboxKind",
    "Severity",
    "Source",
    "Status",
    "StatusSummary",
    "Submission",
    "TestHints",
    "UiMode",
]
