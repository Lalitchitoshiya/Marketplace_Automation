"""Pre-fill `submission.yaml` from the package for `mta kit init` (P1-R27).

This runs before the intake malware scan, so it only uses the hostile-input-safe readers: safe ZIP extraction,
defusedxml, and read-only MSI tables. `msiexec` is never started here.
"""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from mta.config import MtaConfig
from mta.intake.package import detect_kind
from mta.models import PackageKind, ProductDecl
from mta.static.bundle import (
    BundleManifest,
    ManifestError,
    component_versions,
    find_bundles,
    manifest_path,
    parse_package_contents,
)
from mta.static.dotnet import InspectError, inspect_files
from mta.static.extract import ExtractError, safe_extract_zip
from mta.static.msi import MsiError, msi_read_tables


@dataclass
class Prefill:
    version: str | None = None
    title: str | None = None
    publisher: str | None = None
    products: list[ProductDecl] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # why something could not be detected


def _from_manifest(manifest: BundleManifest, cfg: MtaConfig, host_id: str) -> Prefill:
    host = cfg.hosts.hosts[host_id]
    years = sorted({v.year for c in manifest.components for v in component_versions(c.requirements, host)})
    commands = sorted({cmd.global_name for c in manifest.components for cmd in c.commands})
    return Prefill(
        version=manifest.attr("AppVersion"),
        title=manifest.attr("Name"),
        publisher=manifest.attr("Author") or manifest.company.get("Name") or None,
        products=[ProductDecl(host_id=host_id, versions=years)] if years else [],
        commands=commands,
    )


def _from_payload(payload: Path, cfg: MtaConfig, host_id: str) -> Prefill:
    bundles = find_bundles(payload)
    if len(bundles) != 1:
        return Prefill(notes=[f"expected one *.bundle folder, found {len(bundles)}"])
    return _from_bundle(bundles[0], cfg, host_id)


def _from_bundle(bundle: Path, cfg: MtaConfig, host_id: str) -> Prefill:
    host = cfg.hosts.hosts[host_id]
    file_name = host.manifest.file if host.manifest else "PackageContents.xml"
    source = manifest_path(bundle, file_name)
    if source is None:
        return Prefill(notes=[f"{bundle.name} has no {file_name}"])
    try:
        found = _from_manifest(parse_package_contents(source), cfg, host_id)
    except ManifestError as exc:
        return Prefill(notes=[f"{file_name}: {exc}"])
    _add_binary_commands(found, bundle)
    return found


def _add_binary_commands(found: Prefill, bundle: Path) -> None:
    """Commands from [CommandMethod] attributes (mta-inspect reads metadata only: safe before the scan)."""
    dlls = sorted(p for p in bundle.rglob("*") if p.is_file() and p.suffix.lower() == ".dll")
    try:
        reports = inspect_files(dlls)
    except InspectError as exc:
        found.notes.append(f"binary commands not read: {exc}")
        return
    binary = {c.global_name for r in reports for c in r.commands if c.registered}
    found.commands = sorted(set(found.commands) | binary)


def prefill_from_package(package: Path, cfg: MtaConfig, host_id: str = "autocad") -> Prefill:
    kind = detect_kind(package)
    if kind is PackageKind.BUNDLE:
        return _from_bundle(package, cfg, host_id)
    if kind is PackageKind.ZIP:
        with tempfile.TemporaryDirectory(prefix="mta-prefill-") as temp:
            try:
                safe_extract_zip(package, Path(temp) / "x", cfg.thresholds.extract)
            except ExtractError as exc:
                return Prefill(notes=[f"ZIP not extracted: {exc.problems[0]}"])
            return _from_payload(Path(temp) / "x", cfg, host_id)
    try:
        tables = msi_read_tables(package)
    except MsiError as exc:
        return Prefill(notes=[str(exc)])
    return Prefill(
        version=tables.properties.get("ProductVersion"),
        title=tables.properties.get("ProductName"),
        publisher=tables.properties.get("Manufacturer"),
        notes=[
            "MSI: products and commands are detected at intake (the MSI is only extracted after the scan)"
        ],
    )
