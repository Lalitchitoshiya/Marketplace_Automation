"""Shared enums and base model for MTA data contracts (specs/00-foundation/data-contracts.md)."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CheckId = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,4}-\d{3}$")]
HostId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9]*$")]


class Model(BaseModel):
    """Base for all contracts: unknown fields are rejected so typos never pass silently."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Status(StrEnum):
    PASS = "PASS"  # noqa: S105 (a check status, not a password)
    FAIL = "FAIL"
    WARN = "WARN"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"  # MTA / infrastructure failure, never the publisher's fault (Constitution §3)


class Severity(StrEnum):
    BLOCKER = "BLOCKER"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"


class Source(StrEnum):
    STATIC = "static"
    DYNAMIC = "dynamic"
    MONITOR = "monitor"
    AI = "ai"


class Recommendation(StrEnum):
    APPROVE = "RECOMMEND_APPROVE"
    REJECT = "RECOMMEND_REJECT"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class ArtifactKind(StrEnum):
    PACKAGE = "package"
    FILE = "file"
    LOG = "log"
    SCREENSHOT = "screenshot"
    VIDEO = "video"
    DUMP = "dump"
    TRACE = "trace"
    DRAWING = "drawing"
    DOCUMENT = "document"
    REPORT = "report"


class UiMode(StrEnum):
    HEADLESS = "headless"
    GUI = "gui"
