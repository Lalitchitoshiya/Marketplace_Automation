"""Static analysis stage after intake (P1-R02, P1-R04...P1-R11).

Writes into the job folder:
- `payload/` and `payload-files.json`: the extracted payload, every file hashed and stored
- `msi-tables.json`: MSI properties and custom-action inventory (MSI packages only)
- `bundle.json`: bundle, manifest attributes and per-component host versions
- `inspection.json`: mta-inspect / PE reports per binary, per-component GUI classification
- `signatures.json`, `static-gate.json`: Authenticode results; whether dynamic runs may start
- `checks/static-package.json`: PKG-001...003
- `checks/static-manifest.json`: PKG-004...006, MAN-001...004, MAN-006, MAN-007
- `checks/static-binary.json`: BIN-001...009, CMD-003, MAN-005
- `checks/static-security.json`: SIG-001...003; `checks/static-listing.json`: LST-001...003
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mta.config import MtaConfig
from mta.intake.pipeline import IntakeResult
from mta.intake.store import ArtifactStore
from mta.models import CheckResult, JobState
from mta.models.report import Inventory
from mta.static import dotnet, malware, signing
from mta.static import listing as listing_module
from mta.static.binary_checks import BinaryAnalysis, Inspect, analyze_binaries
from mta.static.bundle_checks import BundleAnalysis, analyze_bundle
from mta.static.extract import PackageExtraction, extract_package
from mta.static.listing import OpenUrl, Resolve, listing_checks
from mta.static.security_checks import (
    CheckSignatures,
    Gate,
    Scanner,
    SecurityAnalysis,
    analyze_security,
    dynamic_gate,
)


@dataclass(frozen=True)
class StaticServices:
    """Everything that touches the machine or the network; tests replace these with fakes."""

    scanner: Scanner | None = malware.scan  # None = explicit --no-scan (trusted MTA fixtures only)
    signatures: CheckSignatures = signing.check_signatures
    open_url: OpenUrl = listing_module.open_url
    resolve: Resolve = listing_module.resolve
    offline: bool = False  # no network: LST-001/LST-002 SKIPPED
    inspect: Inspect = dotnet.inspect_files


@dataclass
class StaticOutcome:
    extraction: PackageExtraction
    bundle: BundleAnalysis | None = None  # None when there is no payload
    binary: BinaryAnalysis | None = None
    security: SecurityAnalysis | None = None
    listing: list[CheckResult] = field(default_factory=list)
    gate: Gate = field(default_factory=lambda: Gate(False, ["static stage incomplete"]))

    @property
    def results(self) -> list[CheckResult]:
        parts = [
            self.extraction.results,
            self.bundle.results if self.bundle else [],
            self.binary.results if self.binary else [],
            self.security.results if self.security else [],
            self.listing,
        ]
        return [r for part in parts for r in part]

    def versions(self, intake: IntakeResult, host_id: str = "autocad") -> list[int]:
        """Host versions the report covers: declared on the listing or supported by a component."""
        found = {v for p in intake.submission.products if p.host_id == host_id for v in p.versions}
        if self.bundle:
            found |= {y for c in self.bundle.components for y in c.host_versions}
        return sorted(found)

    def inventory(self, intake: IntakeResult) -> Inventory:
        components: list[dict[str, object]] = []
        for c in self.bundle.components if self.bundle else []:
            entry: dict[str, object] = asdict(c)
            binary = (
                next((b for b in self.binary.components if b.path == c.path), None) if self.binary else None
            )
            if binary:
                entry["gui_required"] = binary.gui_required
                entry["gui_reasons"] = binary.gui_reasons
            if self.security and c.path in self.security.signatures:
                signature = self.security.signatures[c.path]
                entry["signature"] = {"status": signature.status, "signer": signature.signer}
            components.append(entry)
        commands: list[dict[str, object]] = []
        urls: set[str] = set()
        for rel, report in self.binary.assemblies.items() if self.binary else []:
            urls |= set(report.urls)
            commands += [
                {
                    "name": c.global_name,
                    "group": c.group,
                    "file": rel,
                    "registered": c.registered,
                    "flags": c.flags,
                }
                for c in report.commands
            ]
        network: list[dict[str, object]] = [{"source": "binary", "url": u} for u in sorted(urls)]
        listing = intake.submission.listing
        if listing:
            network += [{"source": "listing", "domain": d} for d in listing.external_domains]
            if listing.privacy_policy_url:
                network.append({"source": "listing", "url": listing.privacy_policy_url})
        return Inventory(components=components, commands=commands, network=network)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_results(path: Path, results: list[CheckResult]) -> None:
    _write_json(path, [r.model_dump(mode="json", exclude_none=True) for r in results])


def run_static_stage(
    intake: IntakeResult, cfg: MtaConfig, data_dir: Path, services: StaticServices | None = None
) -> StaticOutcome:
    services = services or StaticServices()
    job_dir = intake.job_dir
    job = intake.job.model_copy(update={"state": JobState.STATIC_ANALYSIS})
    _write_json(job_dir / "job.json", job.model_dump(mode="json", by_alias=True, exclude_none=True))
    checks = job_dir / "checks"
    checks.mkdir(exist_ok=True)

    extraction = extract_package(
        intake.package, intake.submission.package.kind, job_dir / "payload", cfg, work_dir=job_dir
    )
    outcome = StaticOutcome(extraction)

    # P1-R02: every extracted file is hashed and stored.
    store = ArtifactStore(data_dir / "artifacts")
    stored_files = []
    payload = extraction.payload_dir
    if payload is not None:
        for file in extraction.files:
            stored = store.put_file(file)
            rel = file.relative_to(payload).as_posix()
            stored_files.append({"path": rel, "sha256": stored.sha256, "size_bytes": stored.size_bytes})
    _write_json(
        job_dir / "payload-files.json", {"files": stored_files, "nested_archives": extraction.nested_archives}
    )
    if extraction.msi is not None:
        _write_json(job_dir / "msi-tables.json", asdict(extraction.msi))
    _write_results(checks / "static-package.json", extraction.results)

    if payload is not None:
        msi_version = extraction.msi.properties.get("ProductVersion") if extraction.msi else None
        outcome.bundle = analyze_bundle(
            payload, extraction.files, intake.submission, cfg, msi_version=msi_version
        )
        _write_json(job_dir / "bundle.json", outcome.bundle.to_json(payload))
        _write_results(checks / "static-manifest.json", outcome.bundle.results)
        outcome.binary = analyze_binaries(
            payload, extraction.files, outcome.bundle, intake.submission, cfg, inspect=services.inspect
        )
        _write_json(job_dir / "inspection.json", outcome.binary.to_json(cfg.command_flags("autocad")))
        _write_results(checks / "static-binary.json", outcome.binary.results)

    outcome.security = analyze_security(
        payload, extraction.files, intake.package, cfg, scanner=services.scanner, check=services.signatures
    )
    _write_json(job_dir / "signatures.json", {k: asdict(v) for k, v in outcome.security.signatures.items()})
    _write_results(checks / "static-security.json", outcome.security.results)

    covered = {y for c in outcome.bundle.components for y in c.host_versions} if outcome.bundle else set()
    outcome.listing = listing_checks(
        intake.submission,
        covered,
        outcome.binary.results if outcome.binary else [],
        cfg,
        open_url=services.open_url,
        resolve=services.resolve,
        offline=services.offline,
    )
    _write_results(checks / "static-listing.json", outcome.listing)

    outcome.gate = dynamic_gate(outcome.results, scan_skipped=services.scanner is None)
    _write_json(job_dir / "static-gate.json", asdict(outcome.gate))
    return outcome
