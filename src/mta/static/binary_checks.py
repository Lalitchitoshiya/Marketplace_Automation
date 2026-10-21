"""Binary rules BIN-001...009, CMD-003 and MAN-005 (P1-R06, P1-R07, P1-R10; check-catalog.md).

Inputs are `mta-inspect` reports for .NET files and pefile reports for ARX/DBX/CRX. Version-specific results
(BIN-001, BIN-002, CMD-003) carry the host version they apply to.
"""

import fnmatch
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mta.config import MtaConfig
from mta.config.models import HostConfig
from mta.models import CheckResult, Status, Submission
from mta.static.bundle_checks import BundleAnalysis, ComponentInfo
from mta.static.dotnet import AssemblyReport, InspectError, inspect_files
from mta.static.native import NativeReport, read_native
from mta.static.results import ResultSink, excerpt

MANAGED_SUFFIXES = frozenset({".dll", ".exe"})
ARX_SUFFIXES = frozenset({".arx", ".crx", ".dbx"})
OBFUSCATED_CONFIDENCE = 0.6
Inspect = Callable[[list[Path]], list[AssemblyReport]]
_INSPECTION_CHECKS = ("BIN-001", "BIN-002", "BIN-003", "BIN-004", "BIN-006", "BIN-007", "BIN-008", "BIN-009")
_TFM = re.compile(r"^\.(NETCoreApp|NETFramework|NETStandard),Version=v(\d+)\.(\d+)", re.IGNORECASE)
_RUNTIME_FRAMEWORK = re.compile(r"^net(\d)(\d)$")
_RUNTIME_CORE = re.compile(r"^net(\d+)\.(\d+)")
_URL_HOST = re.compile(r"^[a-z]+://([^/:?#]+)", re.IGNORECASE)


@dataclass
class ComponentBinary:
    app_name: str
    path: str | None
    managed: bool
    gui_required: bool
    gui_reasons: list[str]
    commands: list[str]  # registered command global names


@dataclass
class BinaryAnalysis:
    assemblies: dict[str, AssemblyReport] = field(default_factory=dict)  # payload-relative path -> report
    native: dict[str, NativeReport] = field(default_factory=dict)
    components: list[ComponentBinary] = field(default_factory=list)
    results: list[CheckResult] = field(default_factory=list)

    def to_json(self, flags: dict[str, int]) -> dict[str, object]:
        assemblies = {}
        for rel, report in self.assemblies.items():
            data = report.model_dump(mode="json")
            data["path"] = rel
            for command in data["commands"]:
                command["flag_names"] = decode_flags(command["flags"], flags)
            assemblies[rel] = data
        native = {rel: {**asdict(r), "path": rel} for rel, r in self.native.items()}
        return {
            "assemblies": assemblies,
            "native": native,
            "components": [asdict(c) for c in self.components],
        }


# ---- helpers ---------------------------------------------------------------------------------------------


def decode_flags(value: int, table: dict[str, int]) -> list[str]:
    """CommandFlags value -> names. 0 is Modal. Compared as unsigned 32-bit (one flag is 1 << 31)."""
    if value == 0:
        return ["Modal"] if "Modal" in table else []
    bits = value & 0xFFFFFFFF
    return sorted(n for n, v in table.items() if v and (bits & (v & 0xFFFFFFFF)) == (v & 0xFFFFFFFF))


def parse_tfm(tfm: str | None) -> tuple[str, tuple[int, int]] | None:
    match = _TFM.match(tfm or "")
    if not match:
        return None
    return match.group(1).lower(), (int(match.group(2)), int(match.group(3)))


def parse_runtime(runtime: str) -> tuple[str, tuple[int, int]]:
    framework = _RUNTIME_FRAMEWORK.match(runtime)
    if framework:
        return "netframework", (int(framework.group(1)), int(framework.group(2)))
    core = _RUNTIME_CORE.match(runtime)
    if core:
        return "netcoreapp", (int(core.group(1)), int(core.group(2)))
    raise ValueError(f"unknown host runtime {runtime!r}")


def _matches(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(name.lower(), p.lower()) for p in patterns)


def _stem(name: str) -> str:
    return name[:-4] if name.lower().endswith(".dll") else name


def _host_api_refs(report: AssemblyReport, host: HostConfig) -> list[tuple[str, int]]:
    api = {_stem(a).lower() for a in host.api_assemblies}
    found = []
    for ref in report.references:
        if ref.name.lower() in api:
            major = ref.version.split(".")[0]
            found.append((ref.name, int(major) if major.isdigit() else -1))
    return found


# ---- rules -----------------------------------------------------------------------------------------------


class _Rules:
    def __init__(
        self, cfg: MtaConfig, host_id: str, analysis: BinaryAnalysis, versions: dict[str, list[int]]
    ):
        self.cfg = cfg
        self.host_id = host_id
        self.host = cfg.hosts.hosts[host_id]
        self.a = analysis
        self.versions = versions  # payload-relative file -> host versions it must work in
        self.sink = ResultSink(cfg)

    def _add(
        self, check_id: str, status: Status, message: str, evidence: str | None = None, **kw: object
    ) -> None:
        self.sink.add(check_id, status, message, evidence, **kw)  # type: ignore[arg-type]

    def bin001(self) -> None:
        emitted = False
        for rel, report in self.a.assemblies.items():
            if not report.is_managed or report.error:
                continue
            tfm = parse_tfm(report.target_framework)
            for year in self.versions.get(rel, []):
                emitted = True
                kind, host_version = parse_runtime(self.host.version(year).runtime)
                status, why = self._tfm_verdict(tfm, kind, host_version, report)
                evidence = (
                    f"{rel}: {report.target_framework or 'no TargetFramework attribute'}; host runtime "
                )
                evidence += self.host.version(year).runtime
                self._add(
                    "BIN-001",
                    status,
                    why,
                    evidence if status is not Status.PASS else None,
                    subject=f"file:{rel}",
                    host_id=self.host_id,
                    host_version=year,
                )
        if not emitted:
            self.sink.skip("BIN-001", reason="no managed assemblies with target host versions")

    def _tfm_verdict(
        self,
        tfm: tuple[str, tuple[int, int]] | None,
        kind: str,
        host_version: tuple[int, int],
        report: AssemblyReport,
    ) -> tuple[Status, str]:
        if tfm is None:
            return Status.NEEDS_REVIEW, "Target framework unknown (no TargetFramework attribute)"
        family, version = tfm
        if family == "netstandard":
            ok = version <= (2, 0) or kind == "netcoreapp"
            return (
                (Status.PASS, ".NET Standard library")
                if ok
                else (Status.FAIL, f".NET Standard {version[0]}.{version[1]} does not run on .NET Framework")
            )
        if family == kind:
            if version <= host_version:
                return Status.PASS, "Target framework compatible"
            return Status.FAIL, "Built for a newer .NET than the host runs"
        if family == "netcoreapp":
            return Status.FAIL, "Built for .NET (Core); this host runs .NET Framework"
        if _host_api_refs(report, self.host):
            return Status.FAIL, ".NET Framework plugin on a .NET host: AutoCAD 2025+ needs a .NET 8 rebuild"
        return (
            Status.WARN,
            ".NET Framework library on a .NET host: may load through compatibility, verify at runtime",
        )

    def bin002(self) -> None:
        emitted = False
        for rel, report in self.a.assemblies.items():
            refs = _host_api_refs(report, self.host) if report.is_managed else []
            for year in self.versions.get(rel, []) if refs else []:
                emitted = True
                major = self.host.version(year).api_major
                wrong = [f"{name} {m}" for name, m in refs if m != major]
                status = Status.FAIL if wrong else Status.PASS
                message = (
                    f"References API major {', '.join(wrong)}; AutoCAD {year} is {major}"
                    if wrong
                    else f"Host API references match major {major}"
                )
                self._add(
                    "BIN-002",
                    status,
                    message,
                    f"{rel}: {refs}" if wrong else None,
                    subject=f"file:{rel}",
                    host_id=self.host_id,
                    host_version=year,
                )
        for rel, native in self.a.native.items():
            for year in self.versions.get(rel, []):
                emitted = True
                expected = self.host.version(year).arx_import
                imports = {i.lower() for i in native.imports}
                if native.error or native.acdb_major is None:
                    self._add(
                        "BIN-002",
                        Status.NEEDS_REVIEW,
                        "No acdbNN.dll import found in the ARX",
                        f"{rel}: {native.error or native.imports}",
                        subject=f"file:{rel}",
                        host_id=self.host_id,
                        host_version=year,
                    )
                elif expected and expected.lower() in imports:
                    self._add(
                        "BIN-002",
                        Status.PASS,
                        f"ARX imports {expected}",
                        subject=f"file:{rel}",
                        host_id=self.host_id,
                        host_version=year,
                    )
                else:
                    self._add(
                        "BIN-002",
                        Status.FAIL,
                        f"ARX built for acdb{native.acdb_major}; AutoCAD {year} needs {expected}",
                        f"{rel}: imports {native.imports}",
                        subject=f"file:{rel}",
                        host_id=self.host_id,
                        host_version=year,
                    )
        if not emitted:
            self.sink.skip("BIN-002", reason="no host API references and no ARX files")

    def bin003(self) -> None:
        bad = [
            f"{rel}: {r.architecture}"
            for rel, r in self.a.assemblies.items()
            if not r.error and r.architecture not in ("x64", "anycpu")
        ]
        bad += [
            f"{rel}: {n.machine}" for rel, n in self.a.native.items() if not n.error and n.machine != "AMD64"
        ]
        count = len(self.a.assemblies) + len(self.a.native)
        if bad:
            self._add("BIN-003", Status.FAIL, "Binaries that cannot load in 64-bit AutoCAD", excerpt(bad))
        elif count:
            self._add("BIN-003", Status.PASS, f"All {count} binaries are x64 or AnyCPU")
        else:
            self.sink.skip("BIN-003", reason="no binaries")

    def bin004(self, installed_dirs: list[Path]) -> None:
        shipped = {Path(rel).stem.lower() for rel in self.a.assemblies}
        shipped |= {r.assembly_name.lower() for r in self.a.assemblies.values() if r.assembly_name}
        framework = self.cfg.static_rules.framework_assemblies
        missing = []
        for rel, report in self.a.assemblies.items():
            for ref in report.references:
                name = ref.name
                if (
                    name.lower() in shipped
                    or _matches(name, framework)
                    or _matches(name, self.host.provided_assemblies)
                    or any((d / f"{name}.dll").is_file() for d in installed_dirs)
                ):
                    continue
                missing.append(f"{rel}: {name} {ref.version}")
        if missing:
            self._add(
                "BIN-004",
                Status.FAIL,
                "Referenced assemblies are neither shipped, host- nor framework-provided",
                excerpt(missing),
                fix="Ship the missing dependency DLLs next to the plugin assembly.",
            )
        elif self.a.assemblies:
            self._add("BIN-004", Status.PASS, "All assembly references resolvable")
        else:
            self.sink.skip("BIN-004", reason="no managed assemblies")

    def bin005(self, files: list[str]) -> None:
        never = {n.lower() for n in self.host.never_ship_assemblies}
        shipped = [f for f in files if Path(f).name.lower() in never]
        if shipped:
            self._add(
                "BIN-005",
                Status.FAIL,
                "Host API assemblies are shipped in the package",
                excerpt(shipped),
                fix="Reference AutoCAD assemblies with Copy Local = false; never ship them.",
            )
        else:
            self._add("BIN-005", Status.PASS, "No host API assemblies shipped")

    def bin006(self) -> None:
        ignored = {h.lower() for h in self.cfg.static_rules.ignored_url_hosts}
        urls = sorted(
            {
                u
                for r in self.a.assemblies.values()
                for u in r.urls
                if (m := _URL_HOST.match(u)) and m.group(1).lower() not in ignored
            }
        )
        hosts = sorted({m.group(1).lower() for u in urls if (m := _URL_HOST.match(u))})
        if urls:
            self._add(
                "BIN-006",
                Status.PASS,
                f"{len(urls)} hard-coded URL(s), domains: {', '.join(hosts)}",
                excerpt(urls),
            )
        else:
            self._add("BIN-006", Status.PASS, "No hard-coded URLs")

    def bin007(self) -> None:
        rules = self.cfg.static_rules
        found = []
        for rel, report in self.a.assemblies.items():
            for api in rules.risky_apis:
                hits = [m for m in report.member_refs if m.startswith(api.pattern)]
                found += [f"{rel}: {hit} ({api.why})" for hit in hits[:3]]
            for pinvoke in report.pinvokes:
                for rule in rules.risky_pinvokes:
                    if _stem(pinvoke.dll).lower() == _stem(rule.dll).lower() and (
                        rule.entry == "*"
                        or pinvoke.entry.rstrip("AW").lower() == rule.entry.lower()
                        or pinvoke.entry.lower() == rule.entry.lower()
                    ):
                        found.append(f"{rel}: P/Invoke {pinvoke.dll}!{pinvoke.entry} ({rule.why})")
        if found:
            self._add("BIN-007", Status.WARN, f"{len(found)} risky API use(s) to review", excerpt(found))
        else:
            self._add("BIN-007", Status.PASS, "No risky API use found")

    def gui_reasons(self, report: AssemblyReport) -> list[str]:
        gui_assemblies = {_stem(a).lower() for a in self.host.gui_only_assemblies}
        reasons = [f"references {r.name}" for r in report.references if r.name.lower() in gui_assemblies]
        prefixes = tuple(self.host.gui_type_prefixes)
        reasons += [f"uses {t}" for t in report.type_refs if prefixes and t.startswith(prefixes)][:10]
        return reasons

    def bin008(self) -> None:
        if not self.a.components:
            self.sink.skip("BIN-008", reason="no managed components")
        for c in self.a.components:
            if not c.managed:
                continue
            if c.gui_required:
                self._add(
                    "BIN-008",
                    Status.PASS,
                    f"GUI required: {c.app_name} needs the full AutoCAD UI",
                    excerpt(c.gui_reasons),
                    subject=f"component:{c.app_name}",
                )
            else:
                self._add(
                    "BIN-008",
                    Status.PASS,
                    f"Core-console compatible: {c.app_name}",
                    subject=f"component:{c.app_name}",
                )

    def bin009(self) -> set[str]:
        suspected = {rel for rel, r in self.a.assemblies.items() if r.obfuscation.suspected}
        for rel in sorted(suspected):
            signals = self.a.assemblies[rel].obfuscation.signals
            self._add(
                "BIN-009",
                Status.WARN,
                "Obfuscation suspected: static results for this file are less certain",
                excerpt(signals),
                subject=f"file:{rel}",
            )
        if not suspected:
            self._add("BIN-009", Status.PASS, "No obfuscation detected")
        return suspected

    def cmd003(self, commands: dict[str, list[str]], target_years: list[int]) -> None:
        """commands: upper-case name -> where it is defined."""
        duplicates = [
            f"{name}: {', '.join(where)}" for name, where in sorted(commands.items()) if len(where) > 1
        ]
        if duplicates:
            self._add("CMD-003", Status.FAIL, "Command name defined more than once", excerpt(duplicates))
        with_lists = [v.year for v in self.host.versions if v.builtin_commands_file]
        years = [y for y in target_years if y in with_lists] or with_lists
        if not commands or not years:
            if not duplicates:
                self.sink.skip(
                    "CMD-003", reason="no commands" if not commands else "no built-in command list"
                )
            return
        for year in years:
            builtin = self.cfg.builtin_commands(self.host_id, year)
            clashes = sorted(set(commands) & builtin)
            note = "" if year in target_years else f" (closest list available: AutoCAD {year})"
            if clashes:
                self._add(
                    "CMD-003",
                    Status.FAIL,
                    f"Command(s) collide with built-in AutoCAD commands{note}; the "
                    "built-in wins and the plugin command never runs (ADR-0003 F24)",
                    excerpt(f"{c}: {', '.join(commands[c])}" for c in clashes),
                    host_id=self.host_id,
                    host_version=year,
                )
            elif not duplicates:
                self._add(
                    "CMD-003",
                    Status.PASS,
                    f"No collision with {len(builtin)} built-in commands{note}",
                    host_id=self.host_id,
                    host_version=year,
                )

    def man005(self, bundle: BundleAnalysis | None) -> None:
        if bundle is None or bundle.manifest is None:
            self.sink.skip("MAN-005", reason="no valid manifest")
            return
        problems, compared = [], 0
        for info in bundle.components:
            report = self.a.assemblies.get(info.path or "")
            if report is None or not report.is_managed:
                continue
            compared += 1
            manifest = {c.upper() for c in info.commands}
            binary = {c.global_name.upper() for c in report.commands if c.registered}
            hidden = sorted(c.global_name for c in report.commands if not c.registered)
            if hidden:
                problems.append(
                    f"{info.app_name}: not registered (class missing from CommandClass): {hidden}"
                )
            if not manifest:
                if binary and "loadoncommandinvocation" in {r.lower() for r in info.load_reasons}:
                    problems.append(
                        f"{info.app_name}: loads on command invocation but the manifest lists no "
                        f"commands: {sorted(binary)}"
                    )
                continue
            if manifest - binary:
                problems.append(f"{info.app_name}: in manifest, not in binary: {sorted(manifest - binary)}")
            if binary - manifest:
                problems.append(f"{info.app_name}: in binary, not in manifest: {sorted(binary - manifest)}")
        if problems:
            self._add(
                "MAN-005",
                Status.FAIL,
                "Manifest and binary commands differ",
                excerpt(problems),
                fix="Keep <Commands> in PackageContents.xml in sync with the [CommandMethod] commands.",
            )
        elif compared:
            self._add("MAN-005", Status.PASS, f"Manifest and binary commands agree ({compared} component(s))")
        else:
            self.sink.skip("MAN-005", reason="no managed components to compare")


def _target_versions(
    payload: Path, files: list[Path], bundle: BundleAnalysis | None, submission: Submission, host_id: str
) -> dict[str, list[int]]:
    declared = sorted({v for p in submission.products if p.host_id == host_id for v in p.versions})
    by_component = {c.path: c.host_versions for c in bundle.components if c.path} if bundle else {}
    union = sorted({y for years in by_component.values() for y in years}) or declared
    return {rel: by_component.get(rel, union) for f in files if (rel := f.relative_to(payload).as_posix())}


def _components(
    rules: _Rules, bundle: BundleAnalysis | None, analysis: BinaryAnalysis
) -> list[ComponentBinary]:
    infos: list[ComponentInfo] = bundle.components if bundle else []
    if not infos:  # loose binaries: every managed DLL is its own component
        return [
            ComponentBinary(
                Path(rel).stem,
                rel,
                True,
                bool(r := rules.gui_reasons(rep)),
                r,
                [c.global_name for c in rep.commands if c.registered],
            )
            for rel, rep in analysis.assemblies.items()
            if rep.is_managed and rep.commands
        ]
    result = []
    for info in infos:
        report = analysis.assemblies.get(info.path or "")
        managed = bool(report and report.is_managed)
        reasons = rules.gui_reasons(report) if report and managed else []
        commands = [c.global_name for c in report.commands if c.registered] if report else []
        result.append(ComponentBinary(info.app_name, info.path, managed, bool(reasons), reasons, commands))
    return result


def analyze_binaries(
    payload: Path,
    files: list[Path],
    bundle: BundleAnalysis | None,
    submission: Submission,
    cfg: MtaConfig,
    *,
    host_id: str = "autocad",
    inspect: Inspect = inspect_files,
) -> BinaryAnalysis:
    analysis = BinaryAnalysis()
    rels = {f: f.relative_to(payload).as_posix() for f in files}
    # Shipped copies of host assemblies (BIN-005) are Autodesk's code: analysing them would blame the
    # publisher for Autodesk's references and API use (found by corpus case SD-08).
    never_ship = {n.lower() for n in cfg.hosts.hosts[host_id].never_ship_assemblies}
    managed = [f for f in files if f.suffix.lower() in MANAGED_SUFFIXES and f.name.lower() not in never_ship]
    versions = _target_versions(payload, files, bundle, submission, host_id)
    rules = _Rules(cfg, host_id, analysis, versions)
    rules.bin005(sorted(rels.values()))
    try:
        reports = inspect(managed) if managed else []
    except InspectError as exc:
        for check_id in (*_INSPECTION_CHECKS, "CMD-003", "MAN-005"):
            rules.sink.add(check_id, Status.ERROR, f"Binary inspection unavailable: {exc}")
        analysis.results = rules.sink.sorted()
        return analysis
    analysis.assemblies = {rels[f]: r for f, r in zip(managed, reports, strict=True)}
    analysis.native = {rels[f]: read_native(f) for f in files if f.suffix.lower() in ARX_SUFFIXES}
    analysis.components = _components(rules, bundle, analysis)

    host = cfg.hosts.hosts[host_id]
    installed = [Path(v.install_dir) for v in host.versions if Path(v.install_dir).is_dir()]
    rules.bin001()
    rules.bin002()
    rules.bin003()
    rules.bin004(installed)
    rules.bin006()
    rules.bin007()
    rules.bin008()
    obfuscated = rules.bin009()

    commands: dict[str, list[str]] = {}
    for rel, report in analysis.assemblies.items():
        for c in report.commands:
            if c.registered:
                commands.setdefault(c.global_name.upper(), []).append(f"{rel} {c.type}.{c.method}")
    target_years = sorted({y for ys in versions.values() for y in ys})
    rules.cmd003(commands, target_years)
    rules.man005(bundle)

    # BIN-009: static conclusions about an obfuscated file are less certain.
    analysis.results = [
        r.model_copy(update={"confidence": OBFUSCATED_CONFIDENCE})
        if r.target.subject.removeprefix("file:") in obfuscated and r.check_id != "BIN-009"
        else r
        for r in rules.sink.sorted()
    ]
    return analysis
