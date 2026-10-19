"""Static analysis stage after intake (P1-R02, P1-R04...P1-R07, P1-R10).

Writes into the job folder:
- `payload/` and `payload-files.json`: the extracted payload, every file hashed and stored
- `msi-tables.json`: MSI properties and custom-action inventory (MSI packages only)
- `bundle.json`: bundle, manifest attributes and per-component host versions
- `checks/static-package.json`: PKG-001...003
- `inspection.json`: mta-inspect / PE reports per binary, per-component GUI classification
- `checks/static-manifest.json`: PKG-004...006, MAN-001...004, MAN-006, MAN-007
- `checks/static-binary.json`: BIN-001...009, CMD-003, MAN-005
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mta.config import MtaConfig
from mta.intake.pipeline import IntakeResult
from mta.intake.store import ArtifactStore
from mta.models import CheckResult, JobState
from mta.static.binary_checks import BinaryAnalysis, analyze_binaries
from mta.static.bundle_checks import BundleAnalysis, analyze_bundle
from mta.static.extract import PackageExtraction, extract_package


@dataclass(frozen=True)
class StaticOutcome:
    extraction: PackageExtraction
    bundle: BundleAnalysis | None  # None when there is no payload
    binary: BinaryAnalysis | None = None

    @property
    def results(self) -> list[CheckResult]:
        later = [r for part in (self.bundle, self.binary) if part is not None for r in part.results]
        return self.extraction.results + later


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_results(path: Path, results: list[CheckResult]) -> None:
    _write_json(path, [r.model_dump(mode="json", exclude_none=True) for r in results])


def run_static_stage(intake: IntakeResult, cfg: MtaConfig, data_dir: Path) -> StaticOutcome:
    job_dir = intake.job_dir
    job = intake.job.model_copy(update={"state": JobState.STATIC_ANALYSIS})
    _write_json(job_dir / "job.json", job.model_dump(mode="json", by_alias=True, exclude_none=True))
    (job_dir / "checks").mkdir(exist_ok=True)

    extraction = extract_package(
        intake.package, intake.submission.package.kind, job_dir / "payload", cfg, work_dir=job_dir
    )

    # P1-R02: every extracted file is hashed and stored.
    store = ArtifactStore(data_dir / "artifacts")
    listing = []
    if extraction.payload_dir is not None:
        for file in extraction.files:
            stored = store.put_file(file)
            listing.append(
                {
                    "path": file.relative_to(extraction.payload_dir).as_posix(),
                    "sha256": stored.sha256,
                    "size_bytes": stored.size_bytes,
                }
            )
    _write_json(
        job_dir / "payload-files.json", {"files": listing, "nested_archives": extraction.nested_archives}
    )
    if extraction.msi is not None:
        _write_json(job_dir / "msi-tables.json", asdict(extraction.msi))
    _write_results(job_dir / "checks" / "static-package.json", extraction.results)

    bundle = None
    if extraction.payload_dir is not None:
        msi_version = extraction.msi.properties.get("ProductVersion") if extraction.msi else None
        bundle = analyze_bundle(
            extraction.payload_dir, extraction.files, intake.submission, cfg, msi_version=msi_version
        )
        _write_json(job_dir / "bundle.json", bundle.to_json(extraction.payload_dir))
        _write_results(job_dir / "checks" / "static-manifest.json", bundle.results)
        binary = analyze_binaries(extraction.payload_dir, extraction.files, bundle, intake.submission, cfg)
        _write_json(job_dir / "inspection.json", binary.to_json(cfg.command_flags("autocad")))
        _write_results(job_dir / "checks" / "static-binary.json", binary.results)
        return StaticOutcome(extraction, bundle, binary)
    return StaticOutcome(extraction, bundle)
