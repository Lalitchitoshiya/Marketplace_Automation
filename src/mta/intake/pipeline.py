"""Intake: Input Kit -> validated, stored Submission + Job (P1-R01, P1-R02, P1-R27).

Order matters for safety: validate layout and limits, malware-scan everything, and only then hash, store and
parse documents.
"""

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from mta import schemas
from mta.config import MtaConfig
from mta.intake.docs import DocumentError, Mention, extract_text, index_command_mentions
from mta.intake.kit import KitCheck, KitManifest, KitProblem, Scanner, init_kit, validate_kit
from mta.intake.package import bundle_files, package_sha256, package_size
from mta.intake.store import ArtifactStore
from mta.models import (
    ArtifactEntry,
    ArtifactKind,
    DocumentRef,
    Job,
    Listing,
    PackageKind,
    PackageRef,
    Submission,
)
from mta.models.submission import DocumentKind, ReviewerInputs


class IntakeError(Exception):
    def __init__(self, check: KitCheck) -> None:
        super().__init__(f"Input Kit invalid: {sum(p.level == 'error' for p in check.problems)} error(s)")
        self.check = check


@dataclass(frozen=True)
class IntakeResult:
    job: Job
    submission: Submission
    job_dir: Path
    package: Path  # the package inside the kit
    artifacts: list[ArtifactEntry]
    mentions: dict[str, list[Mention]]
    warnings: list[KitProblem]


def _new_ids(now: datetime) -> tuple[str, str]:
    stamp = now.strftime("%Y%m%d-%H%M%S")
    suffix = secrets.token_hex(3)
    return f"sub-{stamp}-{suffix}", f"job-{stamp}-{suffix}"


def _store_package(store: ArtifactStore, check: KitCheck, artifacts: list[ArtifactEntry]) -> PackageRef:
    package, kind = check.package, check.package_kind
    if package is None or kind is None:
        raise ValueError("kit has no valid package")  # validate_kit guarantees this; defensive only
    if kind is PackageKind.BUNDLE:
        tree = []
        for file in bundle_files(package):
            stored = store.put_file(file)
            rel = file.relative_to(package).as_posix()
            tree.append({"path": rel, "sha256": stored.sha256, "size_bytes": stored.size_bytes})
            artifacts.append(
                ArtifactEntry(sha256=stored.sha256, kind=ArtifactKind.FILE, path=f"package/{rel}")
            )
        # The tree listing is stored too, so the bundle can be rebuilt from the store.
        listing = store.put_bytes(json.dumps(tree, indent=1).encode())
        artifacts.append(
            ArtifactEntry(sha256=listing.sha256, kind=ArtifactKind.PACKAGE, path="package-tree.json")
        )
    else:
        stored = store.put_file(package)
        artifacts.append(ArtifactEntry(sha256=stored.sha256, kind=ArtifactKind.PACKAGE, path=package.name))
    return PackageRef(
        filename=package.name,
        sha256=package_sha256(package, kind),
        size_bytes=package_size(package, kind),
        kind=kind,
    )


def _listing(manifest: KitManifest, root: Path) -> Listing | None:
    kit_listing = manifest.listing
    if kit_listing is None:
        return None
    description = kit_listing.description
    if kit_listing.description_file and description is None:
        description = (root / kit_listing.description_file).read_text(encoding="utf-8", errors="replace")
    return Listing(
        title=manifest.app.title or manifest.app.id,
        publisher=manifest.app.publisher or "unknown",
        app_type=manifest.app.type,
        pricing=manifest.app.pricing,
        short_description=kit_listing.short_description,
        description=description,
        support_email=kit_listing.support_email,
        privacy_policy_url=kit_listing.privacy_policy_url,
        documentation_urls=kit_listing.documentation_urls,
        external_domains=kit_listing.external_domains,
        screenshots=kit_listing.screenshots,
    )


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def intake_kit(kit_dir: Path, cfg: MtaConfig, data_dir: Path, scanner: Scanner | None) -> IntakeResult:
    """Validate the kit, store everything content-addressed and create a RECEIVED Job.

    `scanner=None` skips the malware scan; only for trusted fixtures (`--no-scan`).
    """
    check = validate_kit(kit_dir, cfg.thresholds.kit, cfg.thresholds.extract, scanner)
    if not check.ok or check.manifest is None:
        raise IntakeError(check)
    manifest, root = check.manifest, check.root

    now = datetime.now(UTC)
    submission_id, job_id = _new_ids(now)
    job_dir = data_dir / "jobs" / job_id
    (job_dir / "docs-text").mkdir(parents=True)
    store = ArtifactStore(data_dir / "artifacts")
    artifacts: list[ArtifactEntry] = []
    warnings = [p for p in check.problems if p.level == "warning"]

    package_ref = _store_package(store, check, artifacts)
    package_path = check.package
    if package_path is None:  # pragma: no cover - _store_package already checked
        raise ValueError("kit has no valid package")

    # Every non-package kit file is stored; documents also get text extraction.
    kinds = {(root / d.path).resolve(): d.kind for d in manifest.documents}
    documents: list[DocumentRef] = []
    texts: dict[str, str] = {}
    folder_kinds = {
        "docs": ArtifactKind.DOCUMENT,
        "media/screenshots": ArtifactKind.SCREENSHOT,
        "media/videos": ArtifactKind.VIDEO,
        "samples": ArtifactKind.DRAWING,
        "scenarios": ArtifactKind.FILE,
    }
    for folder, files in check.files.items():
        for file in files:
            rel = file.relative_to(root).as_posix()
            stored = store.put_file(file)
            artifacts.append(ArtifactEntry(sha256=stored.sha256, kind=folder_kinds[folder], path=rel))
            if folder != "docs":
                continue
            documents.append(
                DocumentRef(
                    path=rel, kind=kinds.get(file.resolve(), DocumentKind.OTHER), sha256=stored.sha256
                )
            )
            try:
                texts[rel] = extract_text(file)
            except DocumentError as exc:
                warnings.append(KitProblem("warning", rel, f"text extraction failed: {exc}"))
                continue
            (job_dir / "docs-text" / (Path(rel).name + ".txt")).write_text(texts[rel], encoding="utf-8")

    known_commands = {c for f in manifest.features for c in f.commands}
    mentions = index_command_mentions(texts, known_commands)

    submission = Submission(
        submission_id=submission_id,
        app_id=manifest.app.id,
        app_version=manifest.app.version,
        package=package_ref,
        products=manifest.products,
        listing=_listing(manifest, root),
        documents=documents,
        features=manifest.features,
        test_hints=manifest.test_hints,
        reviewer_inputs=ReviewerInputs(
            scenarios=[f.relative_to(root).as_posix() for f in check.files.get("scenarios", [])]
        ),
        received_at=now,
    )
    job = Job(job_id=job_id, submission_id=submission_id, config_snapshot_sha256=cfg.sha256, created_at=now)

    submission_json = submission.model_dump(mode="json", by_alias=True, exclude_none=True)
    job_json = job.model_dump(mode="json", by_alias=True, exclude_none=True)
    for name, document in (("submission", submission_json), ("job", job_json)):
        errors = schemas.validate(name, document)
        if errors:  # a bug in MTA, never a publisher problem
            raise RuntimeError(f"{name}.json does not match its schema: {errors}")

    _write_json(job_dir / "submission.json", submission_json)
    _write_json(job_dir / "job.json", job_json)
    _write_json(job_dir / "artifacts.json", [a.model_dump(mode="json", exclude_none=True) for a in artifacts])
    _write_json(job_dir / "kit-check.json", [asdict(p) for p in check.problems])
    _write_json(
        job_dir / "command-mentions.json",
        {token: [asdict(m) for m in found] for token, found in mentions.items()},
    )
    if check.scan is not None:
        _write_json(
            job_dir / "malware-scan.json", {"outcome": check.scan.outcome, "output": check.scan.output}
        )
    return IntakeResult(job, submission, job_dir, package_path, artifacts, mentions, warnings)


def intake_package(package: Path, cfg: MtaConfig, data_dir: Path, scanner: Scanner | None) -> IntakeResult:
    """`mta run <package>`: wrap a bare package in a minimal kit, then intake it (P1-R01)."""
    kit_dir = data_dir / "kits" / f"{package.name}-{secrets.token_hex(3)}"
    init_kit(kit_dir, package, version="unknown")
    return intake_kit(kit_dir, cfg, data_dir, scanner)
