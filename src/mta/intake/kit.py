"""Input Kit: reading, validating and creating kits (specs/00-foundation/submission-inputs.md)."""

import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field, StringConstraints, ValidationError

from mta.config.models import ExtractThresholds, KitThresholds
from mta.intake.package import PackageError, detect_kind
from mta.intake.prefill import Prefill
from mta.models import Feature, PackageKind, ProductDecl, TestHints
from mta.models.common import Model
from mta.models.submission import AppType, DocumentKind, Pricing
from mta.static.malware import ScanOutcome, ScanResult

MANIFEST = "submission.yaml"
AppId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{1,99}$")]

# Allowed file types per kit folder (submission-inputs.md §2). None = any type (host sample files).
FOLDER_RULES: dict[str, set[str] | None] = {
    "docs": {".pdf", ".docx", ".md", ".txt", ".html", ".htm"},
    "media/screenshots": {".png", ".jpg", ".jpeg"},
    "media/videos": {".mp4", ".webm"},
    "samples": None,
    "scenarios": {".yaml", ".yml"},
}
KIT_FOLDERS = ("package", *FOLDER_RULES)


# ---- submission.yaml -------------------------------------------------------------------------------------


class KitApp(Model):
    id: AppId
    version: str = Field(min_length=1)
    title: str | None = None
    publisher: str | None = None
    type: AppType = AppType.DESKTOP
    pricing: Pricing | None = None


class KitListing(Model):
    short_description: str | None = None
    description: str | None = None
    description_file: str | None = None
    support_email: str | None = None
    privacy_policy_url: str | None = None
    documentation_urls: list[str] = Field(default_factory=list)
    external_domains: list[str] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)


class KitDocument(Model):
    path: str
    kind: DocumentKind = DocumentKind.OTHER


class KitManifest(Model):
    kit_version: Literal[1]
    app: KitApp
    products: list[ProductDecl] = Field(default_factory=list)
    listing: KitListing | None = None
    documents: list[KitDocument] = Field(default_factory=list)
    features: list[Feature] = Field(default_factory=list)
    test_hints: TestHints = Field(default_factory=TestHints)

    def referenced_paths(self) -> list[tuple[str, str]]:
        """(field, relative path) for every file the manifest points to."""
        refs: list[tuple[str, str]] = []
        if self.listing:
            if self.listing.description_file:
                refs.append(("listing.description_file", self.listing.description_file))
            refs += [(f"listing.screenshots[{i}]", p) for i, p in enumerate(self.listing.screenshots)]
        refs += [(f"documents[{i}].path", d.path) for i, d in enumerate(self.documents)]
        refs += [(f"features[{i}].sample", f.sample) for i, f in enumerate(self.features) if f.sample]
        return refs


# ---- validation ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class KitProblem:
    level: Literal["error", "warning"]
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.path}: {self.message}"


@dataclass
class KitCheck:
    root: Path
    manifest: KitManifest | None = None
    package: Path | None = None
    package_kind: PackageKind | None = None
    files: dict[str, list[Path]] = field(default_factory=dict)  # kit folder -> files
    scan: ScanResult | None = None
    problems: list[KitProblem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(p.level == "error" for p in self.problems)

    def error(self, path: str, message: str) -> None:
        self.problems.append(KitProblem("error", path, message))

    def warn(self, path: str, message: str) -> None:
        self.problems.append(KitProblem("warning", path, message))


Scanner = Callable[[Path], ScanResult]


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or os.path.isjunction(path)


def _read_manifest(check: KitCheck) -> None:
    path = check.root / MANIFEST
    if not path.is_file():
        check.error(MANIFEST, "missing (create one with `mta kit init`)")
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        check.error(MANIFEST, f"invalid YAML: {exc}")
        return
    try:
        check.manifest = KitManifest.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            location = ".".join(str(p) for p in err["loc"]) or "<root>"
            check.error(f"{MANIFEST}:{location}", err["msg"])


def _walk(check: KitCheck, extract: ExtractThresholds) -> list[Path]:
    """All files in the kit. Links are rejected: they could point outside the kit (PKG-001 rules)."""
    files: list[Path] = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(check.root):
        current = Path(dirpath)
        for name in list(dirnames):
            if _is_link(current / name):
                check.error(_rel(check.root, current / name), "links are not allowed in a kit")
                dirnames.remove(name)
        for name in filenames:
            file = current / name
            if _is_link(file):
                check.error(_rel(check.root, file), "links are not allowed in a kit")
                continue
            files.append(file)
            total += file.stat().st_size
    if len(files) > extract.max_files:
        check.error(".", f"{len(files)} files exceed the limit of {extract.max_files}")
    if total > extract.max_bytes:
        check.error(".", f"{total} bytes exceed the limit of {extract.max_bytes}")
    return files


def _check_package(check: KitCheck) -> None:
    folder = check.root / "package"
    entries = sorted(folder.iterdir()) if folder.is_dir() else []
    if len(entries) != 1:
        found = ", ".join(e.name for e in entries) or "nothing"
        check.error("package/", f"must contain exactly one MSI, ZIP or .bundle folder (found: {found})")
        return
    try:
        check.package_kind = detect_kind(entries[0])
        check.package = entries[0]
    except PackageError as exc:
        check.error(_rel(check.root, entries[0]), str(exc))


def _size_limit(folder: str, kit: KitThresholds) -> int | None:
    return {
        "docs": kit.doc_max_bytes,
        "media/screenshots": kit.screenshot_max_bytes,
        "media/videos": kit.video_max_bytes,
        "samples": kit.sample_max_bytes,
    }.get(folder)


def _check_folders(check: KitCheck, files: list[Path], kit: KitThresholds) -> None:
    check.files = {name: [] for name in FOLDER_RULES}
    for file in files:
        rel = _rel(check.root, file)
        if rel == MANIFEST or rel.startswith("package/"):
            continue
        folder = next((f for f in FOLDER_RULES if rel.startswith(f + "/")), None)
        if folder is None:
            check.warn(rel, "not in a known kit folder; ignored")
            continue
        allowed = FOLDER_RULES[folder]
        if allowed is not None and file.suffix.lower() not in allowed:
            check.error(rel, f"file type not allowed in {folder}/ (allowed: {', '.join(sorted(allowed))})")
            continue
        limit = _size_limit(folder, kit)
        if limit is not None and file.stat().st_size > limit:
            check.error(rel, f"{file.stat().st_size} bytes exceed the {limit} byte limit for {folder}/")
            continue
        check.files[folder].append(file)
    if len(check.files["media/screenshots"]) > kit.screenshot_max_count:
        check.error("media/screenshots/", f"more than {kit.screenshot_max_count} screenshots")


def _check_references(check: KitCheck) -> None:
    if check.manifest is None:
        return
    root = check.root.resolve()
    for field_name, rel in check.manifest.referenced_paths():
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            check.error(f"{MANIFEST}:{field_name}", f"'{rel}' points outside the kit")
        elif not target.is_file():
            check.error(f"{MANIFEST}:{field_name}", f"'{rel}' does not exist")
    listed = {(root / d.path).resolve() for d in check.manifest.documents}
    for doc in check.files.get("docs", []):
        if doc.resolve() not in listed:
            check.warn(_rel(check.root, doc), "not listed under `documents:`; treated as kind 'other'")


def validate_kit(
    root: Path,
    kit: KitThresholds,
    extract: ExtractThresholds,
    scanner: Scanner | None = None,
) -> KitCheck:
    """Validate a kit.

    With a scanner, all kit files are malware-scanned (P1-R01) before anything parses them.
    """
    check = KitCheck(root)
    if not root.is_dir():
        check.error(str(root), "kit folder does not exist")
        return check
    _read_manifest(check)
    files = _walk(check, extract)
    _check_package(check)
    _check_folders(check, files, kit)
    _check_references(check)
    if scanner is not None:
        check.scan = scanner(root)
        if check.scan.outcome is ScanOutcome.THREATS:
            check.error(".", f"malware scan found threats: {', '.join(check.scan.threats)}")
        elif check.scan.outcome is ScanOutcome.UNAVAILABLE:
            check.error(".", f"malware scan could not run, kit not trusted: {check.scan.output.strip()}")
    return check


# ---- kit init --------------------------------------------------------------------------------------------

_TEMPLATE = """\
# MTA Input Kit (specs/00-foundation/submission-inputs.md).
# Required: kit_version, app.id, app.version and exactly one package in package/.
kit_version: 1

app:
  id: {app_id}
  version: "{version}"               # TODO: check against the app version on the listing
  title: {title}                        # e.g. "MyTools for AutoCAD"
  publisher: {publisher}
  type: desktop
  pricing: null                      # free | trial | paid | subscription

# Declared hosts and versions, as on the listing.{products_note}
products: {products}
#  - host_id: autocad
#    versions: [2025, 2026]

listing: null
#  short_description: "..."
#  description_file: docs/listing-description.md
#  support_email: support@example.com
#  privacy_policy_url: https://example.com/privacy
#  external_domains: [api.example.com]
#  screenshots: [media/screenshots/01-ribbon.png]

documents: []
#  - path: docs/user-guide.pdf
#    kind: user_guide              # user_guide | quick_start | release_notes | install_guide | other

# Feature hints: the most useful input for testing.{commands_note}
features: []
#  - id: F1
#    name: "Dimension all lines"
#    commands: [ACME_DIMALL]
#    sample: samples/site-plan.dwg
#    expected: "Every line gets a dimension"

test_hints:
  needs_login: false
  credentials_ref: null              # secret NAME only; never put passwords in the kit
  needs_internet: false
"""


def app_id_from_name(name: str) -> str:
    stem = re.sub(r"\.(msi|zip|bundle)$", "", name, flags=re.IGNORECASE)
    slug = re.sub(r"[^a-z0-9._-]+", "-", stem.lower()).strip("-._")
    return slug if len(slug) >= 2 else f"app-{slug or 'unknown'}"


def _yaml_text(value: str | None) -> str:
    return json.dumps(value) if value else "null"  # JSON strings are valid YAML scalars


def _render(app_id: str, version: str | None, prefill: Prefill | None) -> str:
    p = prefill or Prefill()
    products = "[]"
    note = ""
    if p.products:
        products = "".join(
            f"\n  - host_id: {d.host_id}\n    versions: [{', '.join(map(str, d.versions))}]"
            for d in p.products
        )
        note = "\n# Pre-filled from the package manifest (what it supports): check against the listing."
    commands = ""
    if p.commands:
        commands = "\n# Commands found in the package: " + ", ".join(p.commands)
    return _TEMPLATE.format(
        app_id=app_id,
        version=version or p.version or "0.0.0",
        title=_yaml_text(p.title),
        publisher=_yaml_text(p.publisher),
        products=products,
        products_note=note,
        commands_note=commands,
    )


def init_kit(
    root: Path,
    package: Path,
    app_id: str | None = None,
    version: str | None = None,
    prefill: Prefill | None = None,
) -> Path:
    """Create the kit layout, copy the package into package/ and write a submission.yaml template.

    `version` given explicitly wins over the pre-filled one.
    """
    detect_kind(package)  # fail early on unsupported packages
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"{root} is not empty")
    for folder in KIT_FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    target = root / "package" / package.name
    if package.is_dir():
        shutil.copytree(package, target)
    else:
        shutil.copy2(package, target)
    text = _render(app_id or app_id_from_name(package.name), version, prefill)
    (root / MANIFEST).write_text(text, encoding="utf-8")
    return root
