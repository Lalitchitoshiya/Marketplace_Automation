"""Bundle and manifest rules PKG-004...006 and MAN-001...007 (P1-R05; requirements.md rule table)."""

from dataclasses import asdict, dataclass, field
from pathlib import Path

from mta.config import MtaConfig
from mta.config.models import HostConfig
from mta.models import CheckResult, Status, Submission
from mta.static.bundle import (
    BundleManifest,
    ManifestError,
    component_versions,
    find_bundles,
    is_guid,
    loads_in_plain_host,
    manifest_path,
    parse_package_contents,
    series,
)
from mta.static.extract import check_member_name
from mta.static.results import ResultSink, excerpt

SCRIPT_SUFFIXES = frozenset(
    {".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".scr", ".hta"}
)
_MAN_AFTER_001 = ("MAN-002", "MAN-003", "MAN-004", "MAN-006", "MAN-007")


@dataclass
class ComponentInfo:
    """One manifest component as later steps need it (written to bundle.json)."""

    app_name: str
    module: str
    path: str | None  # relative to the payload; None when the module path is unsafe
    exists: bool
    host_versions: list[int]
    loads_in_plain_host: bool
    load_reasons: list[str]
    commands: list[str]
    requirements_level: str | None


@dataclass
class BundleAnalysis:
    bundle: Path | None = None
    manifest: BundleManifest | None = None
    components: list[ComponentInfo] = field(default_factory=list)
    results: list[CheckResult] = field(default_factory=list)

    def to_json(self, payload: Path) -> dict[str, object]:
        return {
            "bundle": self.bundle.relative_to(payload).as_posix() if self.bundle else None,
            "attributes": self.manifest.attributes if self.manifest else None,
            "company": self.manifest.company if self.manifest else None,
            "components": [asdict(c) for c in self.components],
        }


def normalize_version(text: str) -> tuple[str, ...]:
    """'v2.3.0' -> ('2', '3'): leading v and trailing zero parts are ignored."""
    parts = text.strip().lstrip("vV").split(".")
    while len(parts) > 1 and parts[-1].strip("0") == "":
        parts.pop()
    return tuple(p.strip().lower() for p in parts)


def _module_path(bundle: Path, module: str) -> Path | None:
    rel = module.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    if not rel or check_member_name(rel) is not None:
        return None
    return bundle / rel


def _components(
    bundle: Path, payload: Path, manifest: BundleManifest, host: HostConfig
) -> list[ComponentInfo]:
    infos = []
    for c in manifest.components:
        path = _module_path(bundle, c.module)
        infos.append(
            ComponentInfo(
                app_name=c.app_name,
                module=c.module,
                path=path.relative_to(payload).as_posix() if path else None,
                exists=bool(path and path.is_file()),
                host_versions=[v.year for v in component_versions(c.requirements, host)],
                loads_in_plain_host=loads_in_plain_host(c.requirements, host),
                load_reasons=c.load_reasons,
                commands=[cmd.global_name for cmd in c.commands],
                requirements_level=c.requirements.level if c.requirements else None,
            )
        )
    return infos


def _pkg004(results: ResultSink, payload: Path, file_name: str) -> Path | None:
    bundles = find_bundles(payload)
    names = [b.relative_to(payload).as_posix() for b in bundles]
    fix = f"Ship exactly one <Name>.bundle folder with {file_name} directly inside it."
    if not bundles:
        results.add("PKG-004", Status.FAIL, "No *.bundle folder in the package", "(none)", fix)
        return None
    if len(bundles) > 1:
        results.add(
            "PKG-004",
            Status.FAIL,
            f"{len(bundles)} bundle folders; exactly one expected",
            excerpt(names),
            fix,
        )
        return None
    if manifest_path(bundles[0], file_name) is None:
        results.add("PKG-004", Status.FAIL, f"{names[0]} has no {file_name}", names[0], fix)
        return None
    results.add("PKG-004", Status.PASS, f"Bundle layout valid: {names[0]}")
    return bundles[0]


def _man002(results: ResultSink, m: BundleManifest) -> None:
    missing = []
    if not is_guid(m.attr("ProductCode")):
        missing.append(f"ProductCode is not a GUID: {m.attr('ProductCode')!r}")
    missing += [f"{a} missing" for a in ("AppVersion", "Name", "AutodeskProduct") if m.attr(a) is None]
    if m.attr("Author") is None and not m.company.get("Name", "").strip():
        missing.append("Author / CompanyDetails Name missing")
    if missing:
        results.add("MAN-002", Status.FAIL, "Required manifest metadata missing", excerpt(missing))
    else:
        results.add("MAN-002", Status.PASS, "Required manifest metadata present")


def _man003(results: ResultSink, infos: list[ComponentInfo], submission: Submission, host_id: str) -> None:
    declared = sorted({v for p in submission.products if p.host_id == host_id for v in p.versions})
    if not declared:
        results.skip("MAN-003", reason="no versions declared for this host in the submission")
        return
    covered = {y for c in infos for y in c.host_versions}
    uncovered = [y for y in declared if y not in covered]
    if uncovered:
        results.add(
            "MAN-003",
            Status.FAIL,
            f"Manifest version range does not cover declared version(s) {uncovered}",
            f"declared: {declared}\ncovered by components: {sorted(covered)}",
            "Widen SeriesMin/SeriesMax in RuntimeRequirements, or correct the listing's supported versions.",
        )
    else:
        results.add("MAN-003", Status.PASS, f"Manifest covers declared versions {declared}")


def _man004(results: ResultSink, infos: list[ComponentInfo]) -> None:
    bad = [
        f"{c.app_name}: {c.module} " + ("escapes the bundle" if c.path is None else "not found")
        for c in infos
        if not c.exists
    ]
    if bad:
        results.add("MAN-004", Status.FAIL, "Component module path(s) missing", excerpt(bad))
    else:
        results.add("MAN-004", Status.PASS, f"All {len(infos)} component module(s) exist")


def _man006(results: ResultSink, m: BundleManifest, host: HostConfig) -> None:
    facts = host.manifest
    if facts is None:  # pragma: no cover - configuration guarantees facts for bundle hosts
        results.skip("MAN-006", reason="no manifest facts configured for the host")
        return
    problems = []
    if (m.attr("AutodeskProduct") or "").lower() != facts.autodesk_product.lower():
        problems.append(f"AutodeskProduct={m.attr('AutodeskProduct')!r}, expected {facts.autodesk_product!r}")
    product_type = m.attr("ProductType")
    if product_type and product_type.lower() not in {t.lower() for t in facts.product_types}:
        problems.append(f"ProductType={product_type!r}, expected one of {facts.product_types}")
    unknown_platforms: set[str] = set()
    known = {p.lower() for p in facts.known_platforms}
    for req in m.all_requirements:
        where = f"RuntimeRequirements ({req.level})"
        bad_os = [o for o in req.os if o.lower() not in {v.lower() for v in facts.os_values}]
        if bad_os:
            problems.append(f"{where}: invalid OS {bad_os}")
        elif req.os and facts.required_os.lower() not in {o.lower() for o in req.os}:
            problems.append(f"{where}: OS={'|'.join(req.os)} does not include {facts.required_os}")
        for name, value in (("SeriesMin", req.series_min), ("SeriesMax", req.series_max)):
            if value is not None and series(value) is None:
                problems.append(f"{where}: {name}={value!r} is not like 'R25.0'")
        unknown_platforms.update(p for p in req.platforms if p.lower() not in known)
    if problems:
        results.add("MAN-006", Status.FAIL, "Invalid manifest values", excerpt(problems))
    elif unknown_platforms:
        results.add("MAN-006", Status.WARN, "Unknown Platform value(s)", excerpt(sorted(unknown_platforms)))
    else:
        results.add("MAN-006", Status.PASS, "Manifest values valid")


def _man007(results: ResultSink, infos: list[ComponentInfo], m: BundleManifest) -> None:
    by_name = {c.app_name: c for c in m.components}
    orphans = []
    for info in infos:
        if not info.host_versions:
            req = by_name[info.app_name].requirements
            span = f"{req.series_min or '-'}..{req.series_max or '-'}" if req else "-"
            orphans.append(f"{info.app_name}: range {span} matches no configured host version")
    if orphans:
        results.add(
            "MAN-007", Status.FAIL, "Component(s) load in no configured host version", excerpt(orphans)
        )
    else:
        results.add("MAN-007", Status.PASS, "Every component maps to a configured host version")


def _pkg005(results: ResultSink, payload: Path, files: list[Path], infos: list[ComponentInfo]) -> None:
    declared = {c.path.lower() for c in infos if c.path}
    scripts = [
        rel
        for f in files
        if f.suffix.lower() in SCRIPT_SUFFIXES
        and (rel := f.relative_to(payload).as_posix()).lower() not in declared
    ]
    if scripts:
        results.add(
            "PKG-005",
            Status.WARN,
            f"{len(scripts)} script/executable file(s) outside the declared components",
            excerpt(scripts),
            "Remove helper scripts from the package, or explain them to the reviewer.",
        )
    else:
        results.add("PKG-005", Status.PASS, "No unexpected script or executable files")


def _pkg006(
    results: ResultSink, m: BundleManifest | None, submission: Submission, msi_version: str | None
) -> None:
    if submission.app_version.lower() == "unknown":
        results.skip("PKG-006", reason="no app version given in the kit")
        return
    wanted = normalize_version(submission.app_version)
    found = {"manifest AppVersion": m.attr("AppVersion") if m else None, "MSI ProductVersion": msi_version}
    mismatches = [
        f"{where} = {value!r}, listing = {submission.app_version!r}"
        for where, value in found.items()
        if value is not None and normalize_version(value) != wanted
    ]
    if mismatches:
        results.add("PKG-006", Status.FAIL, "Package version differs from the listing", excerpt(mismatches))
    elif any(v is not None for v in found.values()):
        results.add("PKG-006", Status.PASS, f"Package version matches {submission.app_version}")
    else:
        results.skip("PKG-006", reason="the package declares no version")


def analyze_bundle(
    payload: Path,
    files: list[Path],
    submission: Submission,
    cfg: MtaConfig,
    *,
    msi_version: str | None = None,
    host_id: str = "autocad",
) -> BundleAnalysis:
    host = cfg.hosts.hosts[host_id]
    file_name = host.manifest.file if host.manifest else "PackageContents.xml"
    results = ResultSink(cfg)
    analysis = BundleAnalysis()

    bundle = _pkg004(results, payload, file_name)
    analysis.bundle = bundle
    if bundle is None:
        results.skip("MAN-001", *_MAN_AFTER_001, reason="no usable bundle (PKG-004)")
    else:
        source = manifest_path(bundle, file_name)
        try:
            analysis.manifest = parse_package_contents(source) if source else None
        except ManifestError as exc:
            results.add("MAN-001", Status.FAIL, f"{file_name} is not valid", str(exc))
            results.skip(*_MAN_AFTER_001, reason="manifest unusable (MAN-001)")
        if analysis.manifest is not None:
            m = analysis.manifest
            results.add("MAN-001", Status.PASS, f"{file_name} valid: {len(m.components)} component(s)")
            analysis.components = _components(bundle, payload, m, host)
            _man002(results, m)
            _man003(results, analysis.components, submission, host_id)
            _man004(results, analysis.components)
            _man006(results, m, host)
            _man007(results, analysis.components, m)

    _pkg005(results, payload, files, analysis.components)
    _pkg006(results, analysis.manifest, submission, msi_version)
    analysis.results = results.sorted()
    return analysis
