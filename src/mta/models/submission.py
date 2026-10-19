"""Submission: one app version to test, built from the Input Kit.

See specs/00-foundation/submission-inputs.md.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from mta.models.common import HostId, Model, Sha256


class PackageKind(StrEnum):
    MSI = "msi"
    BUNDLE = "bundle"
    ZIP = "zip"


class AppType(StrEnum):
    DESKTOP = "desktop"
    WEB = "web"
    MCP = "mcp"


class Pricing(StrEnum):
    FREE = "free"
    TRIAL = "trial"
    PAID = "paid"
    SUBSCRIPTION = "subscription"


class DocumentKind(StrEnum):
    USER_GUIDE = "user_guide"
    QUICK_START = "quick_start"
    RELEASE_NOTES = "release_notes"
    INSTALL_GUIDE = "install_guide"
    LISTING_DESCRIPTION = "listing_description"
    OTHER = "other"


class PackageRef(Model):
    filename: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    kind: PackageKind


class ProductDecl(Model):
    host_id: HostId
    versions: list[int] = Field(min_length=1)
    verticals: list[str] = Field(default_factory=list)


class Listing(Model):
    title: str
    publisher: str
    app_type: AppType = AppType.DESKTOP
    pricing: Pricing | None = None
    short_description: str | None = None
    description: str | None = None
    support_email: str | None = None
    privacy_policy_url: str | None = None
    documentation_urls: list[str] = Field(default_factory=list)
    external_domains: list[str] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)


class DocumentRef(Model):
    path: str
    kind: DocumentKind = DocumentKind.OTHER
    sha256: Sha256 | None = None


class Feature(Model):
    id: str
    name: str
    how_to: str | None = None
    commands: list[str] = Field(default_factory=list)
    sample: str | None = None
    expected: str | None = None


class TestHints(Model):
    __test__ = False  # not a pytest test class

    needs_login: bool = False
    credentials_ref: str | None = None  # secret name only, never the secret (submission-inputs.md §3)
    licence_key_ref: str | None = None
    needs_internet: bool = False
    known_limitations: str | None = None
    reviewer_notes: str | None = None


class ReviewerInputs(Model):
    scenarios: list[str] = Field(default_factory=list)
    notes: str = ""


class Submission(Model):
    submission_id: str
    app_id: str
    app_version: str
    previous_submission_id: str | None = None
    package: PackageRef
    products: list[ProductDecl] = Field(default_factory=list)
    listing: Listing | None = None
    documents: list[DocumentRef] = Field(default_factory=list)
    features: list[Feature] = Field(default_factory=list)
    test_hints: TestHints = Field(default_factory=TestHints)
    reviewer_inputs: ReviewerInputs = Field(default_factory=ReviewerInputs)
    received_at: datetime
