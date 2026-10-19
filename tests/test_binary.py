"""mta-inspect wrapper, native PE reading and rules BIN-001...009, CMD-003, MAN-005 (step 9)."""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mta.config import REPO_ROOT, MtaConfig
from mta.intake.pipeline import intake_kit
from mta.intake.prefill import prefill_from_package
from mta.models import CheckResult, PackageKind, ProductDecl, Status, Submission
from mta.models.submission import PackageRef
from mta.static import binary_checks, dotnet
from mta.static.binary_checks import BinaryAnalysis, analyze_binaries, decode_flags, parse_runtime, parse_tfm
from mta.static.bundle_checks import analyze_bundle
from mta.static.dotnet import AssemblyReport, InspectError, find_inspect, inspect_files
from mta.static.native import NativeReport, read_native
from mta.static.stage import run_static_stage
from tests.conftest import PACKAGE_CONTENTS, KitFactory, clean_scanner, make_bundle

DLL = "Acme.bundle/Contents/Acme.dll"


def _report(path: str = DLL, **fields: Any) -> AssemblyReport:
    base: dict[str, Any] = {
        "path": path,
        "is_managed": True,
        "machine": "I386",
        "architecture": "anycpu",
        "mixed_mode": False,
        "assembly_name": Path(path).stem,
        "assembly_version": "1.0.0.0",
        "target_framework": ".NETCoreApp,Version=v8.0",
        "references": [
            {"name": "System.Runtime", "version": "8.0.0.0"},
            {"name": "AcDbMgd", "version": "25.1.0.0"},
        ],
        "commands": [_command("ACME_DIMALL"), _command("ACME_EXPORTCSV")],
        "obfuscation": {"suspected": False, "signals": []},
        "error": None,
    }
    base.update(fields)
    return AssemblyReport.model_validate(base)


def _command(name: str, registered: bool = True, type_: str = "Acme.Commands") -> dict[str, Any]:
    return {
        "global_name": name,
        "local_name": None,
        "group": "ACME",
        "flags": 0,
        "type": type_,
        "method": name.title(),
        "registered": registered,
    }


def _submission(years: list[int] | None = None) -> Submission:
    return Submission(
        submission_id="sub-1",
        app_id="acme.tools",
        app_version="2.3.0",
        package=PackageRef(filename="Acme.zip", sha256="0" * 64, size_bytes=1, kind=PackageKind.ZIP),
        products=[ProductDecl(host_id="autocad", versions=years)] if years else [],
        received_at=datetime.now(UTC),
    )


def _analyze(
    tmp_path: Path,
    cfg: MtaConfig,
    reports: dict[str, AssemblyReport] | None = None,
    *,
    manifest: str | None = PACKAGE_CONTENTS,
    extra: dict[str, bytes] | None = None,
    years: list[int] | None = None,
) -> BinaryAnalysis:
    """Payload = the conftest bundle (Acme.dll, AutoCAD 2025-2026) + extra files; reports by payload path."""
    payload = tmp_path / "payload"
    make_bundle(payload)
    if manifest is None:
        (payload / "Acme.bundle" / "PackageContents.xml").unlink()
    else:
        (payload / "Acme.bundle" / "PackageContents.xml").write_text(manifest, encoding="utf-8")
    for rel, data in (extra or {}).items():
        (payload / rel).parent.mkdir(parents=True, exist_ok=True)
        (payload / rel).write_bytes(data)
    files = sorted(p for p in payload.rglob("*") if p.is_file())
    known = {DLL: _report(), **(reports or {})}

    def fake_inspect(paths: list[Path]) -> list[AssemblyReport]:
        rels = [p.relative_to(payload).as_posix() for p in paths]
        return [known.get(rel) or _report(rel, references=[], commands=[]) for rel in rels]

    submission = _submission(years)
    bundle = analyze_bundle(payload, files, submission, cfg)
    return analyze_binaries(payload, files, bundle, submission, cfg, inspect=fake_inspect)


def _results(analysis: BinaryAnalysis, check_id: str, year: int | None = None) -> list[CheckResult]:
    return [
        r
        for r in analysis.results
        if r.check_id == check_id and (year is None or r.target.host_version == year)
    ]


def _one(analysis: BinaryAnalysis, check_id: str, year: int | None = None) -> CheckResult:
    found = _results(analysis, check_id, year)
    assert len(found) == 1, found
    return found[0]


def _text(result: CheckResult) -> str:
    return result.message + "\n" + "\n".join(e.excerpt or "" for e in result.evidence)


# ---- helpers ---------------------------------------------------------------------------------------------


def test_decode_flags_with_the_verified_table(cfg: MtaConfig) -> None:
    table = cfg.command_flags("autocad")
    assert decode_flags(0, table) == ["Modal"]
    assert decode_flags(6, table) == ["Redraw", "UsePickSet"]
    assert decode_flags(2097152 | 1, table) == ["Session", "Transparent"]
    assert decode_flags(-2147483648, table) == ["TempShowDynDimension"]  # the sign bit is a real flag


def test_parse_tfm_and_runtime() -> None:
    assert parse_tfm(".NETCoreApp,Version=v8.0") == ("netcoreapp", (8, 0))
    assert parse_tfm(".NETFramework,Version=v4.7.2") == ("netframework", (4, 7))
    assert parse_tfm(None) is None
    assert parse_runtime("net48") == ("netframework", (4, 8))
    assert parse_runtime("net10.0-windows") == ("netcoreapp", (10, 0))
    with pytest.raises(ValueError, match="unknown host runtime"):
        parse_runtime("python3.12")


# ---- BIN-001 / BIN-002 -----------------------------------------------------------------------------------

NET48_MANIFEST = PACKAGE_CONTENTS.replace('SeriesMin="R25.0"', 'SeriesMin="R24.0"')  # 2024-2026


@pytest.mark.parametrize(
    ("tfm", "refs", "expected"),
    [
        (".NETCoreApp,Version=v8.0", "25", {2024: Status.FAIL, 2025: Status.PASS, 2026: Status.PASS}),
        (".NETFramework,Version=v4.8", "24", {2024: Status.PASS, 2025: Status.FAIL, 2026: Status.FAIL}),
        (".NETFramework,Version=v4.8", None, {2024: Status.PASS, 2025: Status.WARN, 2026: Status.WARN}),
        (".NETStandard,Version=v2.0", None, {2024: Status.PASS, 2025: Status.PASS, 2026: Status.PASS}),
        (".NETStandard,Version=v2.1", None, {2024: Status.FAIL, 2025: Status.PASS, 2026: Status.PASS}),
        (".NETCoreApp,Version=v10.0", None, {2024: Status.FAIL, 2025: Status.FAIL, 2026: Status.FAIL}),
        (None, None, {2024: Status.NEEDS_REVIEW, 2025: Status.NEEDS_REVIEW, 2026: Status.NEEDS_REVIEW}),
    ],
)
def test_bin001_per_version(
    tmp_path: Path, cfg: MtaConfig, tfm: str | None, refs: str | None, expected: dict[int, Status]
) -> None:
    references = [{"name": "AcDbMgd", "version": f"{refs}.0.0.0"}] if refs else []
    report = _report(target_framework=tfm, references=references)
    analysis = _analyze(tmp_path, cfg, {DLL: report}, manifest=NET48_MANIFEST)
    assert {r.target.host_version: r.status for r in _results(analysis, "BIN-001")} == expected
    assert all(r.target.subject == f"file:{DLL}" for r in _results(analysis, "BIN-001"))


def test_bin002_api_major(tmp_path: Path, cfg: MtaConfig) -> None:
    report = _report(references=[{"name": "acdbmgd", "version": "24.3.0.0"}])
    analysis = _analyze(tmp_path, cfg, {DLL: report}, manifest=NET48_MANIFEST)
    assert {r.target.host_version: r.status for r in _results(analysis, "BIN-002")} == {
        2024: Status.PASS,
        2025: Status.FAIL,
        2026: Status.FAIL,
    }
    assert "acdbmgd 24; AutoCAD 2025 is 25" in _one(analysis, "BIN-002", 2025).message


def test_arx_import_and_machine(tmp_path: Path, cfg: MtaConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    natives = {
        "Acme.arx": NativeReport("x", "AMD64", ["acdb25.dll", "KERNEL32.dll"]),
        "Old.arx": NativeReport("x", "I386", ["acdb24.dll"]),
        "Odd.dbx": NativeReport("x", "AMD64", ["KERNEL32.dll"]),
    }
    monkeypatch.setattr(binary_checks, "read_native", lambda path: natives[path.name])
    extra = {f"Acme.bundle/Contents/{name}": b"MZ" for name in natives}
    analysis = _analyze(tmp_path, cfg, extra=extra)
    by_file = {(r.target.subject, r.target.host_version): r.status for r in _results(analysis, "BIN-002")}
    assert by_file[("file:Acme.bundle/Contents/Acme.arx", 2025)] is Status.PASS
    assert by_file[("file:Acme.bundle/Contents/Old.arx", 2026)] is Status.FAIL
    assert by_file[("file:Acme.bundle/Contents/Odd.dbx", 2025)] is Status.NEEDS_REVIEW
    bin003 = _one(analysis, "BIN-003")
    assert bin003.status is Status.FAIL and "Old.arx: I386" in _text(bin003)


# ---- BIN-003...007 ---------------------------------------------------------------------------------------


def test_bin003_x86_assembly(tmp_path: Path, cfg: MtaConfig) -> None:
    analysis = _analyze(tmp_path, cfg, {DLL: _report(architecture="x86")})
    assert _one(analysis, "BIN-003").status is Status.FAIL


def test_bin004_unresolved_and_shipped_references(tmp_path: Path, cfg: MtaConfig) -> None:
    refs = [
        {"name": "System.Text.Json", "version": "8.0.0.0"},  # framework
        {"name": "Acdbmgd", "version": "25.1.0.0"},  # host-provided (case-insensitive)
        {"name": "Newtonsoft.Json", "version": "13.0.0.0"},  # shipped below
        {"name": "Acme.Core", "version": "1.0.0.0"},  # missing
    ]
    newtonsoft = "Acme.bundle/Contents/Newtonsoft.Json.dll"
    analysis = _analyze(tmp_path, cfg, {DLL: _report(references=refs)}, extra={newtonsoft: b"MZ"})
    result = _one(analysis, "BIN-004")
    assert result.status is Status.FAIL
    assert _text(result).count(":") >= 1 and "Acme.Core 1.0.0.0" in _text(result)
    assert "Newtonsoft" not in _text(result) and "Acdbmgd" not in _text(result)


def test_bin005_shipped_host_assemblies(tmp_path: Path, cfg: MtaConfig) -> None:
    analysis = _analyze(tmp_path, cfg, extra={"Acme.bundle/Contents/acdbmgd.dll": b"MZ"})
    result = _one(analysis, "BIN-005")
    assert result.status is Status.FAIL and "acdbmgd.dll" in _text(result)


def test_bin006_and_bin007_inventories(tmp_path: Path, cfg: MtaConfig) -> None:
    report = _report(
        urls=["https://api.acme.example/v1", "http://schemas.microsoft.com/x", "ftp://files.acme.example/a"],
        member_refs=["System.Diagnostics.Process::Start", "System.String::Concat"],
        pinvokes=[
            {"dll": "KERNEL32", "entry": "VirtualProtect"},
            {"dll": "amsi.dll", "entry": "AmsiScanBuffer"},
            {"dll": "user32.dll", "entry": "FindWindowW"},
        ],
    )
    analysis = _analyze(tmp_path, cfg, {DLL: report})
    urls = _one(analysis, "BIN-006")
    assert urls.status is Status.PASS and "domains: api.acme.example, files.acme.example" in urls.message
    assert "schemas.microsoft.com" not in _text(urls)
    risky = _one(analysis, "BIN-007")
    assert risky.status is Status.WARN
    assert "Process::Start (starts other programs)" in _text(risky)
    assert "KERNEL32!VirtualProtect" in _text(risky) and "amsi.dll!AmsiScanBuffer" in _text(risky)
    assert "FindWindow" not in _text(risky)


# ---- BIN-008 / BIN-009 -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "gui"),
    [
        ({"references": [{"name": "AcMgd", "version": "25.1.0.0"}]}, False),  # ADR-0003 F14
        ({"type_refs": ["Autodesk.AutoCAD.Windows.PaletteSet"]}, True),
        ({"references": [{"name": "PresentationFramework", "version": "8.0.0.0"}]}, True),
        ({"type_refs": ["Autodesk.Windows.RibbonControl"]}, True),
    ],
)
def test_bin008_gui_classification(tmp_path: Path, cfg: MtaConfig, fields: dict[str, Any], gui: bool) -> None:
    analysis = _analyze(tmp_path, cfg, {DLL: _report(**fields)})
    result = _one(analysis, "BIN-008")
    assert result.status is Status.PASS and result.target.subject == "component:Acme"
    assert result.message.startswith("GUI required" if gui else "Core-console compatible")
    assert analysis.components[0].gui_required is gui


def test_bin009_obfuscation_lowers_confidence(tmp_path: Path, cfg: MtaConfig) -> None:
    report = _report(
        obfuscation={"suspected": True, "signals": ["obfuscator marker type ConfusedByAttribute"]}
    )
    analysis = _analyze(tmp_path, cfg, {DLL: report})
    assert _one(analysis, "BIN-009").status is Status.WARN
    assert all(r.confidence == 0.6 for r in _results(analysis, "BIN-001"))
    assert _one(analysis, "BIN-009").confidence == 1.0


# ---- CMD-003 / MAN-005 -----------------------------------------------------------------------------------


def test_cmd003_builtin_collision_and_duplicates(tmp_path: Path, cfg: MtaConfig) -> None:
    other = "Acme.bundle/Contents/Other.dll"
    reports = {
        DLL: _report(commands=[_command("ACME_DIMALL"), _command("ACME_EXPORTCSV"), _command("line")]),
        other: _report(other, commands=[_command("ACME_DIMALL", type_="Other.Commands")]),
    }
    analysis = _analyze(tmp_path, cfg, reports, extra={other: b"MZ"})
    results = _results(analysis, "CMD-003")
    duplicate = next(r for r in results if "more than once" in r.message)
    assert "ACME_DIMALL" in _text(duplicate)
    collision = next(r for r in results if r.target.host_version == 2026)
    assert collision.status is Status.FAIL and "LINE:" in _text(collision)


def test_cmd003_uses_closest_list_and_skips_without_commands(tmp_path: Path, cfg: MtaConfig) -> None:
    manifest = PACKAGE_CONTENTS.replace(
        'SeriesMin="R25.0" SeriesMax="R25.1"', 'SeriesMin="R25.0" SeriesMax="R25.0"'
    )
    analysis = _analyze(tmp_path, cfg, manifest=manifest)  # 2025 only: no built-in list for 2025 yet
    result = _one(analysis, "CMD-003")
    assert result.status is Status.PASS and "closest list available: AutoCAD 2026" in result.message
    empty = _analyze(tmp_path / "b", cfg, {DLL: _report(commands=[])})
    assert _one(empty, "CMD-003").status is Status.SKIPPED


def test_man005_agreement(tmp_path: Path, cfg: MtaConfig) -> None:
    assert _one(_analyze(tmp_path, cfg), "MAN-005").status is Status.PASS


def test_man005_drift_both_ways_and_unregistered(tmp_path: Path, cfg: MtaConfig) -> None:
    commands = [_command("ACME_DIMALL"), _command("ACME_NEW"), _command("ACME_HIDDEN", registered=False)]
    analysis = _analyze(tmp_path, cfg, {DLL: _report(commands=commands)})
    text = _text(_one(analysis, "MAN-005"))
    assert "in manifest, not in binary: ['ACME_EXPORTCSV']" in text
    assert "in binary, not in manifest: ['ACME_NEW']" in text
    assert "not registered (class missing from CommandClass): ['ACME_HIDDEN']" in text


def test_man005_demand_loading_needs_commands(tmp_path: Path, cfg: MtaConfig) -> None:
    start = (
        PACKAGE_CONTENTS.split("<Commands")[0]
        + "</ComponentEntry>"
        + PACKAGE_CONTENTS.split("</Commands>")[1]
    )
    on_command = start.replace("</ComponentEntry>\n    </ComponentEntry>", "</ComponentEntry>")
    analysis = _analyze(tmp_path, cfg, manifest=on_command)
    assert _one(analysis, "MAN-005").status is Status.FAIL
    assert "loads on command invocation" in _text(_one(analysis, "MAN-005"))
    at_startup = on_command.replace('LoadOnCommandInvocation="True"', 'LoadOnAutoCADStartup="True"')
    assert _one(_analyze(tmp_path / "b", cfg, manifest=at_startup), "MAN-005").status is Status.PASS


def test_without_bundle_each_dll_is_a_component(tmp_path: Path, cfg: MtaConfig) -> None:
    analysis = _analyze(tmp_path, cfg, manifest=None, years=[2026])
    assert [c.app_name for c in analysis.components] == ["Acme"]
    assert _one(analysis, "MAN-005").status is Status.SKIPPED
    assert {r.target.host_version for r in _results(analysis, "BIN-001")} == {2026}  # declared versions


def test_inspection_unavailable_is_error_not_fail(tmp_path: Path, cfg: MtaConfig) -> None:
    payload = tmp_path / "payload"
    make_bundle(payload)
    files = sorted(p for p in payload.rglob("*") if p.is_file())

    def broken(_: list[Path]) -> list[AssemblyReport]:
        raise InspectError("mta-inspect not found")

    analysis = analyze_binaries(payload, files, None, _submission(), cfg, inspect=broken)
    statuses = {r.check_id: r.status for r in analysis.results}
    assert statuses.pop("BIN-005") is Status.PASS  # file names only, still evaluated
    assert set(statuses.values()) == {Status.ERROR}


# ---- mta-inspect wrapper and the real tool ---------------------------------------------------------------


def test_find_inspect_respects_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dotnet.INSPECT_ENV, str(tmp_path / "missing.exe"))
    assert find_inspect() is None
    with pytest.raises(InspectError, match="not found"):
        inspect_files([tmp_path / "a.dll"])
    assert inspect_files([]) == []


def test_contract_drift_and_failures_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = tmp_path / "tool.exe"
    tool.write_bytes(b"")

    def fake_run(stdout: bytes, code: int = 0) -> Any:
        return lambda *a, **k: subprocess.CompletedProcess(a, code, stdout, b"boom")

    monkeypatch.setattr(subprocess, "run", fake_run(b'[{"path": "x", "surprise": 1}]'))
    with pytest.raises(InspectError, match="does not match the contract"):
        inspect_files([tmp_path / "a.dll"], tool)
    monkeypatch.setattr(subprocess, "run", fake_run(b"", 2))
    with pytest.raises(InspectError, match="exit 2: boom"):
        inspect_files([tmp_path / "a.dll"], tool)


def test_real_tool_on_fixtures(net_fixtures: dict[str, Path]) -> None:
    plugin, net48 = inspect_files([net_fixtures["plugin"], net_fixtures["net48"]], net_fixtures["inspect"])
    assert plugin.target_framework == ".NETCoreApp,Version=v8.0"
    assert {c.global_name for c in plugin.commands if c.registered} >= {"FIX_ONE", "LINE", "FIX_FIVE"}
    assert [c.global_name for c in plugin.commands if not c.registered] == ["FIX_HIDDEN"]
    assert (net48.target_framework, net48.architecture) == (".NETFramework,Version=v4.8", "x86")


def test_fixture_plugin_end_to_end(tmp_path: Path, cfg: MtaConfig, net_fixtures: dict[str, Path]) -> None:
    """A bundle around the real fixture DLL, analysed with the real mta-inspect."""
    payload = tmp_path / "payload"
    bundle = make_bundle(payload, "Fixture.bundle")
    (bundle / "Contents" / "Acme.dll").unlink()
    (bundle / "Contents" / "FixturePlugin.dll").write_bytes(net_fixtures["plugin"].read_bytes())
    manifest = PACKAGE_CONTENTS.replace("./Contents/Acme.dll", "./Contents/FixturePlugin.dll")
    (bundle / "PackageContents.xml").write_text(manifest, encoding="utf-8")
    files = sorted(p for p in payload.rglob("*") if p.is_file())
    submission = _submission([2026])
    report = analyze_bundle(payload, files, submission, cfg)

    def real(paths: list[Path]) -> list[AssemblyReport]:
        return inspect_files(paths, net_fixtures["inspect"])

    analysis = analyze_binaries(payload, files, report, submission, cfg, inspect=real)
    assert analysis.components[0].gui_required  # PaletteSet
    assert _one(analysis, "BIN-001", 2026).status is Status.PASS
    assert _one(analysis, "BIN-002", 2026).status is Status.PASS  # fake AcCoreMgd 25.0
    assert _one(analysis, "BIN-004").status is Status.PASS
    assert "Process::Start" in _text(_one(analysis, "BIN-007"))
    assert "LINE" in _text(_one(analysis, "CMD-003", 2026))
    assert "FIX_HIDDEN" in _text(_one(analysis, "MAN-005"))
    flags: Any = analysis.to_json(cfg.command_flags("autocad"))["assemblies"]
    commands = {
        c["global_name"]: c["flag_names"]
        for c in flags["Fixture.bundle/Contents/FixturePlugin.dll"]["commands"]
    }
    assert commands["FIX_TWO"] == ["Redraw", "UsePickSet"] and commands["FIX_THREE"] == ["Session"]


SPIKES = {
    "SpikePlugin": REPO_ROOT / "spikes/p1-t03-accoreconsole/out/SpikePlugin/SpikePlugin.dll",
    "SpikeUiPlugin": REPO_ROOT / "spikes/p1-t03-accoreconsole/out/SpikeUiPlugin/SpikeUiPlugin.dll",
    "CollisionPlugin": REPO_ROOT / "spikes/p1-t04-commands/out/CollisionPlugin/CollisionPlugin.dll",
}


def test_spike_plugins_are_described(cfg: MtaConfig, net_fixtures: dict[str, Path], tmp_path: Path) -> None:
    """Step 9 'done when'; the spike builds need AutoCAD, so this runs where they exist."""
    if not all(p.is_file() for p in SPIKES.values()):
        pytest.skip("spike plugins not built (spikes/*/out is local only)")
    reports = dict(zip(SPIKES, inspect_files(list(SPIKES.values()), net_fixtures["inspect"]), strict=True))
    assert all(
        r.target_framework == ".NETCoreApp,Version=v8.0" and r.architecture == "x64" for r in reports.values()
    )
    assert {c.global_name for c in reports["SpikePlugin"].commands} >= {
        "SPK_HELLO",
        "SPK_THROW",
        "SPK_PROMPT",
    }
    first = reports["CollisionPlugin"].commands[0]
    assert (first.group, first.global_name) == ("SPKGRP", "LINE")

    # SpikeUiPlugin is core-console compatible (ADR-0003 F14, F27).
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "SpikeUiPlugin.dll").write_bytes(SPIKES["SpikeUiPlugin"].read_bytes())
    analysis = analyze_binaries(
        payload,
        [payload / "SpikeUiPlugin.dll"],
        None,
        _submission([2026]),
        cfg,
        inspect=lambda paths: inspect_files(paths, net_fixtures["inspect"]),
    )
    assert not analysis.components[0].gui_required
    assert _one(analysis, "BIN-002", 2026).status is Status.PASS


def test_native_reader_on_a_system_dll(tmp_path: Path) -> None:
    report = read_native(Path(os.environ["SYSTEMROOT"]) / "System32" / "version.dll")
    assert report.machine == "AMD64" and report.error is None and report.imports
    assert report.acdb_major is None
    (tmp_path / "bad.arx").write_bytes(b"not a PE")
    assert read_native(tmp_path / "bad.arx").error is not None
    assert NativeReport("x", "AMD64", ["ACDB25.DLL"]).acdb_major == 25


# ---- stage and pre-fill ----------------------------------------------------------------------------------


def test_stage_writes_inspection(
    make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path, net_fixtures: dict[str, Path]
) -> None:
    kit = make_kit("bundle")
    (kit / "package" / "Acme.bundle" / "Contents" / "Acme.dll").write_bytes(
        net_fixtures["plugin"].read_bytes()
    )
    data = tmp_path / "data"
    intake = intake_kit(kit, cfg, data, clean_scanner)
    outcome = run_static_stage(intake, cfg, data)
    assert outcome.binary is not None
    inspection = json.loads((intake.job_dir / "inspection.json").read_text("utf-8"))
    assert inspection["components"][0]["gui_required"] is True
    binary = json.loads((intake.job_dir / "checks" / "static-binary.json").read_text("utf-8"))
    assert {r["check_id"] for r in binary} >= {"BIN-001", "BIN-008", "CMD-003", "MAN-005"}


def test_prefill_adds_binary_commands(
    tmp_path: Path, cfg: MtaConfig, net_fixtures: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(dotnet.INSPECT_ENV, str(net_fixtures["inspect"]))
    bundle = make_bundle(tmp_path)
    (bundle / "Contents" / "Acme.dll").write_bytes(net_fixtures["plugin"].read_bytes())
    found = prefill_from_package(bundle, cfg)
    assert {"ACME_DIMALL", "FIX_ONE", "LINE"} <= set(found.commands)  # manifest + binary
    assert "FIX_HIDDEN" not in found.commands  # not registered
    monkeypatch.setenv(dotnet.INSPECT_ENV, str(tmp_path / "missing.exe"))
    assert "binary commands not read" in prefill_from_package(bundle, cfg).notes[0]
