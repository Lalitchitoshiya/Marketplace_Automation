"""Step 12: run folder, script, sessions, LOD rules, dynamic stage, doctor, builds (no AutoCAD needed)."""

import dataclasses
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from mta.adapters.autocad import build, dynamic, session
from mta.adapters.autocad.console import ConsoleError, ConsoleRun
from mta.adapters.autocad.events import ProbeEvent, ProbeLog
from mta.adapters.autocad.session import (
    Component,
    ScriptBuilder,
    SessionResult,
    baseline,
    loader_for,
    prepare_run,
    run_session,
)
from mta.cli.app import app
from mta.config import REPO_ROOT, MtaConfig
from mta.corpus.synthetic import make_bundle, make_kit
from mta.doctor import check_basic, fix_wer
from mta.engine.load_rules import GUI_NOTE, load_checks
from mta.intake.kit import validate_kit
from mta.intake.pipeline import intake_kit
from mta.models import CheckResult, Status
from mta.static.bundle import find_bundles, manifest_path, parse_package_contents
from mta.static.stage import run_static_stage
from tests.conftest import OFFLINE_SERVICES, KitFactory, clean_scanner

T0 = datetime(2026, 10, 20, tzinfo=UTC)


def _probe(tmp_path: Path) -> Path:
    probe = tmp_path / "WorkspaceAssist.dll"
    probe.write_bytes(b"MZ")
    return probe


def _payload(tmp_path: Path) -> Path:
    payload = tmp_path / "payload"
    (payload / "Acme.bundle" / "Contents").mkdir(parents=True)
    for name in ("Acme.dll", "Acme.arx", "acme.lsp"):
        (payload / "Acme.bundle" / "Contents" / name).write_bytes(b"x")
    return payload


COMPONENTS = [
    Component("AcmeNet", "Acme.bundle/Contents/Acme.dll", "netload"),
    Component("AcmeArx", "Acme.bundle/Contents/Acme.arx", "arx"),
    Component("AcmeLisp", "Acme.bundle/Contents/acme.lsp", "lisp"),
    Component("AcmeMenu", "Acme.bundle/Contents/Acme.cuix", "none"),
]


# ---- run folder and script -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "loader"),
    [("a/X.DLL", "netload"), ("x.crx", "arx"), ("x.dbx", "arx"), ("x.fas", "lisp"), ("x.cuix", "none")],
)
def test_loader_for(path: str, loader: str) -> None:
    assert loader_for(path) == loader


def test_prepare_run_copies_and_plans(cfg: MtaConfig, tmp_path: Path) -> None:
    layout = prepare_run(cfg, tmp_path / "runs", _probe(tmp_path), _payload(tmp_path), COMPONENTS)
    assert (layout.probe_dir / "WorkspaceAssist.dll").is_file()
    assert (layout.plugin_dir / "Acme.bundle" / "Contents" / "Acme.dll").is_file()
    assert layout.plan.name == cfg.probe_identity.autocad.plan_file  # neutral names (Constitution §11)
    plan = json.loads(layout.plan.read_text("utf-8"))
    assert plan["plugin_dir"] == str(layout.plugin_dir)
    assert [c["name"] for c in plan["components"]] == ["AcmeNet", "AcmeArx"]  # LISP is loaded by script
    assert plan["components"][0]["module"] == str(layout.plugin_dir / "Acme.bundle/Contents/Acme.dll")
    assert layout.run_id.startswith("r") and len(layout.run_id) == 7  # short paths (F28)


def test_script_builder(cfg: MtaConfig, tmp_path: Path) -> None:
    c = cfg.probe_identity.autocad.commands
    layout = prepare_run(cfg, tmp_path / "runs", _probe(tmp_path), _payload(tmp_path), COMPONENTS)
    builder = ScriptBuilder(cfg, layout, "WorkspaceAssist.dll", COMPONENTS)
    for component in COMPONENTS:
        builder.load(component)
    lines = builder.defined(['AC"ME']).end(["QUIT", "Y"])
    trusted = lines[1]
    assert lines[0] == "FILEDIA 0"
    assert "/..." not in trusted  # explicit folders: the recursive form left plugins unloaded (step 12)
    assert f"{layout.probe_dir.as_posix()};" in trusted and "Acme.bundle/Contents" in trusted
    assert lines[2:4] == ["NETLOAD", str(layout.probe_dir / "WorkspaceAssist.dll")]  # probe first (F11)
    assert lines[4:8] == [c.load, "AcmeNet", c.load, "AcmeArx"]
    assert lines[8:10] == [c.mark, "begin load:AcmeLisp"]
    assert '"lisp-load" "AcmeLisp" (progn (load "' in lines[10]
    assert '(getcname "AC\\"ME")' in lines[13]
    assert lines[-3:] == [c.end, "QUIT", "Y"]
    assert "" not in lines  # a bare blank line repeats the last command (F4)
    assert not any("AcmeMenu" in line for line in lines)


# ---- sessions --------------------------------------------------------------------------------------------


def _event(seq: int, type_: str, **data: Any) -> str:
    ts = (T0 + timedelta(milliseconds=seq * 10)).isoformat().replace("+00:00", "Z")
    return json.dumps({"v": 1, "seq": seq, "ts": ts, "run_id": "r", "type": type_, "data": data})


def _fake_console(events: list[str], output: str = "Command: QUIT", code: int | None = 0, **kw: Any) -> Any:
    def run(cfg: MtaConfig, year: int, root: Path, script: Path, **_: Any) -> ConsoleRun:
        (root / cfg.probe_identity.autocad.events_file).write_text("\n".join(events) + "\n", encoding="utf-8")
        return ConsoleRun(code, code is None, output, 1.0, 4242, **kw)

    return run


CLEAN = [_event(1, "session.start"), _event(2, "host.ready", startup_ms=1), _event(3, "session.shutdown")]


def test_run_session_detects_infrastructure_text(
    cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = prepare_run(cfg, tmp_path / "runs", _probe(tmp_path), None, [])
    output = "Error: Unable to obtain a license for this product"
    monkeypatch.setattr(
        session, "run_core_console", _fake_console(CLEAN, output, crash_reporter_killed=["x"])
    )
    result = run_session(cfg, 2026, "load", layout, ["QUIT"], 10)
    assert result.infra_error and "licensing" in result.infra_error
    assert result.notes == ["crash reporter suppressed: x"]
    assert layout.script.read_bytes().endswith(b"QUIT\n")


def test_run_session_console_unavailable(
    cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: Any, **__: Any) -> ConsoleRun:
        raise ConsoleError("AutoCAD 2026 core console not found")

    monkeypatch.setattr(session, "run_core_console", broken)
    layout = prepare_run(cfg, tmp_path / "runs", _probe(tmp_path), None, [])
    result = run_session(cfg, 2026, "load", layout, ["QUIT"], 10)
    assert result.console is None and "not found" in (result.infra_error or "")


@pytest.mark.parametrize(
    ("events", "code", "ok"),
    [(CLEAN, 0, True), (CLEAN[:2], 0, False), (CLEAN, 1, False)],
)
def test_baseline(
    cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[str], code: int, ok: bool
) -> None:
    monkeypatch.setattr(session, "run_core_console", _fake_console(events, code=code))
    result = baseline(cfg, 2026, tmp_path / "runs", _probe(tmp_path))
    assert (result.infra_error is None) is ok
    if not ok:
        assert (result.infra_error or "").startswith("baseline failed")


# ---- LOD rules -------------------------------------------------------------------------------------------


def _session(
    cfg: MtaConfig, tmp_path: Path, events: list[str], *, timed_out: bool = False, infra: str | None = None
) -> SessionResult:
    layout = prepare_run(cfg, tmp_path / "runs", _probe(tmp_path), None, [])
    log = ProbeLog([ProbeEvent.model_validate(json.loads(e)) for e in events])
    console = ConsoleRun(None if timed_out else 0, timed_out, "Command: x", 1.0)
    return SessionResult("load", 2026, layout, console, log, infra_error=infra)


def _load(
    seq: int,
    name: str,
    *,
    ok: bool = True,
    loaded: bool | None = True,
    exceptions: int = 0,
    ms: int = 100,
    error: str | None = None,
) -> list[str]:
    module = f"C:/runs/plugin/{name}.dll"
    return [
        _event(seq, "component.load.begin", component=name, module_path=module, loader="netload"),
        _event(
            seq + 1,
            "component.load.end",
            component=name,
            module_path=module,
            ok=ok,
            loaded=loaded,
            plugin_exceptions=exceptions,
            duration_ms=ms,
            error=error,
        ),
    ]


def _by(results: list[CheckResult]) -> dict[tuple[str, str], Status]:
    return {(r.check_id, r.target.subject): r.status for r in results}


def test_load_rules_all_pass(cfg: MtaConfig, tmp_path: Path) -> None:
    events = [
        _event(1, "session.start"),
        _event(2, "host.ready"),
        *_load(3, "A"),
        _event(9, "session.shutdown"),
    ]
    results = load_checks(cfg, [Component("A", "A.dll", "netload")], _session(cfg, tmp_path, events))
    assert _by(results) == {
        ("LOD-001", "component:A"): Status.PASS,
        ("LOD-002", "component:A"): Status.PASS,
        ("LOD-003", "package"): Status.PASS,
    }
    assert all(r.target.host_version == 2026 and r.source.value == "dynamic" for r in results)


def test_load_rules_failures(cfg: MtaConfig, tmp_path: Path) -> None:
    exception = _event(
        5,
        "exception.first_chance",
        type="System.NullReferenceException",
        message="boom",
        stack="Acme.App.Initialize [B]",
    )
    events = [
        _event(1, "host.ready"),
        *_load(3, "A", ok=False, error="FileLoadException: bad image"),
        _event(4, "component.load.begin", component="B", module_path="b", loader="netload"),
        exception,
        _event(
            6,
            "component.load.end",
            component="B",
            module_path="b",
            ok=True,
            loaded=True,
            plugin_exceptions=1,
            duration_ms=9000,
        ),
        *_load(7, "C", loaded=False),
        *_load(10, "G", exceptions=1),
        _event(12, "component.load.begin", component="H", module_path="h", loader="netload"),
    ]
    components = [
        Component("A", "A.dll", "netload"),
        Component("B", "B.dll", "netload"),
        Component("C", "C.dll", "netload"),
        Component("G", "G.dll", "netload", gui_required=True),
        Component("H", "H.dll", "netload"),
    ]
    results = load_checks(cfg, components, _session(cfg, tmp_path, events))
    status = _by(results)
    assert status[("LOD-001", "component:A")] is Status.FAIL
    assert status[("LOD-001", "component:B")] is Status.FAIL  # Initialize threw (F11)
    b = next(r for r in results if r.target.subject == "component:B" and r.check_id == "LOD-001")
    assert "Acme.App.Initialize" in (b.evidence[0].excerpt or "")
    assert status[("LOD-002", "component:B")] is Status.FAIL  # 9 s > 5 s
    assert status[("LOD-001", "component:C")] is Status.ERROR  # not loaded: trust problem, not the plugin
    g = next(r for r in results if r.target.subject == "component:G" and r.check_id == "LOD-001")
    assert g.status is Status.NEEDS_REVIEW and GUI_NOTE in g.message
    assert status[("LOD-001", "component:H")] is Status.FAIL  # never finished
    assert status[("LOD-002", "component:H")] is Status.SKIPPED
    assert status[("LOD-003", "package")] is Status.FAIL


def test_load_rules_lisp_none_and_timeout(cfg: MtaConfig, tmp_path: Path) -> None:
    events = [
        _event(1, "host.ready"),
        _event(2, "mark", phase="begin", label="load:L"),
        _event(3, "note", kind="lisp-load", name="L", value="ok"),
        _event(4, "mark", phase="end", label="load:L"),
        _event(5, "mark", phase="begin", label="load:Bad"),
        _event(6, "mark", phase="end", label="load:Bad"),
    ]
    components = [
        Component("L", "l.lsp", "lisp"),
        Component("Bad", "b.lsp", "lisp"),
        Component("M", "m.cuix", "none"),
    ]
    status = _by(load_checks(cfg, components, _session(cfg, tmp_path, events, timed_out=True)))
    assert status[("LOD-001", "component:L")] is Status.PASS
    assert status[("LOD-002", "component:L")] is Status.PASS
    assert status[("LOD-001", "component:Bad")] is Status.FAIL
    assert status[("LOD-001", "component:M")] is Status.SKIPPED
    assert status[("LOD-003", "package")] is Status.FAIL  # timed out


def test_load_rules_infrastructure_error(cfg: MtaConfig, tmp_path: Path) -> None:
    results = load_checks(
        cfg, [Component("A", "A.dll", "netload")], _session(cfg, tmp_path, [], infra="licence problem")
    )
    assert {r.status for r in results} == {Status.ERROR}  # never FAIL for an environment problem (P1-R18)


# ---- dynamic stage ---------------------------------------------------------------------------------------


@pytest.fixture
def static_job(make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path) -> Any:
    data = tmp_path / "data"
    intake = intake_kit(make_kit("bundle"), cfg, data, clean_scanner)
    return intake, run_static_stage(intake, cfg, data, OFFLINE_SERVICES), data


def _stage(
    cfg: MtaConfig,
    static_job: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    installed: list[int],
    probe: bool = True,
    base_error: str | None = None,
) -> dynamic.DynamicOutcome:
    intake, static, data = static_job
    probe_file = data / "probe.dll"
    if probe:
        probe_file.write_bytes(b"MZ")
    else:
        probe_file.unlink(missing_ok=True)
    monkeypatch.setattr(dynamic, "installed_versions", lambda c: installed)
    monkeypatch.setattr(dynamic, "probe_dll", lambda c, y: probe_file)
    calls: list[str] = []

    def fake_baseline(c: MtaConfig, year: int, root: Path, p: Path) -> SessionResult:
        calls.append(f"baseline {year}")
        layout = prepare_run(c, root, p, None, [])
        return SessionResult("baseline", year, layout, ConsoleRun(0, False, "", 1.0), ProbeLog(), base_error)

    def fake_load(
        c: MtaConfig,
        year: int,
        root: Path,
        p: Path,
        payload: Path,
        comps: list[Component],
        commands: list[str],
    ) -> SessionResult:
        calls.append(f"load {year} {[x.name for x in comps]} {commands}")
        events = [_event(1, "host.ready"), *_load(2, comps[0].name)]
        log = ProbeLog([ProbeEvent.model_validate(json.loads(e)) for e in events])
        return SessionResult(
            "load", year, prepare_run(c, root, p, None, []), ConsoleRun(0, False, "", 1.0), log
        )

    monkeypatch.setattr(dynamic, "baseline", fake_baseline)
    monkeypatch.setattr(dynamic, "load_session", fake_load)
    outcome = dynamic.run_dynamic_stage(intake, static, cfg, data)
    outcome.calls = calls  # type: ignore[attr-defined]
    return outcome


def _status_by_year(outcome: dynamic.DynamicOutcome, check_id: str) -> dict[int | None, Status]:
    return {r.target.host_version: r.status for r in outcome.results if r.check_id == check_id}


def test_dynamic_stage_runs_installed_versions(
    cfg: MtaConfig, static_job: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _stage(cfg, static_job, monkeypatch, installed=[2026])
    assert _status_by_year(outcome, "LOD-001") == {2025: Status.SKIPPED, 2026: Status.PASS}
    assert outcome.calls == ["baseline 2026", "load 2026 ['Acme'] ['ACME_DIMALL', 'ACME_EXPORTCSV']"]  # type: ignore[attr-defined]
    intake = static_job[0]
    summary = json.loads((intake.job_dir / "dynamic.json").read_text("utf-8"))
    assert [s["kind"] for s in summary["sessions"]] == ["baseline", "load"]
    assert (intake.job_dir / "checks" / "dynamic.json").is_file()


def test_dynamic_stage_errors_and_skips(
    cfg: MtaConfig, static_job: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert set(_status_by_year(_stage(cfg, static_job, monkeypatch, installed=[]), "LOD-003").values()) == {
        Status.SKIPPED
    }
    no_probe = _stage(cfg, static_job, monkeypatch, installed=[2025, 2026], probe=False)
    assert set(_status_by_year(no_probe, "LOD-001").values()) == {Status.ERROR}
    failed = _stage(cfg, static_job, monkeypatch, installed=[2026], base_error="baseline failed (exit 0x1)")
    assert _status_by_year(failed, "LOD-003")[2026] is Status.ERROR
    assert failed.calls == ["baseline 2026"]  # type: ignore[attr-defined]  # no plugin run after a bad baseline


def test_dynamic_stage_respects_the_gate(
    cfg: MtaConfig, static_job: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    intake, static, data = static_job
    static.gate = dataclasses.replace(static.gate, dynamic_allowed=False, reasons=["SIG-003 FAIL"])
    outcome = _stage(cfg, (intake, static, data), monkeypatch, installed=[2026])
    lod = [r for r in outcome.results if r.check_id == "LOD-001"]
    assert {r.status for r in lod} == {Status.SKIPPED} and "SIG-003 FAIL" in lod[0].message
    assert outcome.calls == []  # type: ignore[attr-defined]  # nothing runs (P1-R08)


# ---- doctor, builds, synthetic packaging -----------------------------------------------------------------


def test_doctor_basic(cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import mta.doctor as doctor

    monkeypatch.setattr(doctor, "installed_versions", lambda c: [2026])
    monkeypatch.setattr(doctor, "core_console", lambda c, y: Path("accoreconsole.exe"))
    monkeypatch.setattr(doctor, "probe_dll", lambda c, y: tmp_path / "missing.dll")
    monkeypatch.setattr(doctor, "wer_dump_folder", lambda: None)
    diagnosis = check_basic(cfg, tmp_path / "d")
    levels = {i.name: i.level for i in diagnosis.items}
    assert levels["AutoCAD 2025"] == "warn" and levels["AutoCAD 2026"] == "ok"
    assert levels["probe for 2026"] == "fail" and not diagnosis.healthy
    assert levels["WER LocalDumps"] == "warn"  # optional evidence: never blocks
    monkeypatch.setattr(doctor, "is_admin", lambda: False)
    assert "not administrator" in fix_wer(tmp_path / "dumps")


def test_cli_doctor_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    from mta.doctor import Diagnosis, Item

    monkeypatch.setattr("mta.cli.doctor_cmds.check_basic", lambda c, d: Diagnosis([Item("x", "ok", "fine")]))
    assert CliRunner().invoke(app, ["doctor"]).exit_code == 0
    monkeypatch.setattr(
        "mta.cli.doctor_cmds.check_basic", lambda c, d: Diagnosis([Item("x", "fail", "no", "do")])
    )
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 1 and "fix: do" in result.output and "UNHEALTHY" in result.output


def test_build_for_command_and_failure(
    cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, b"x.cs(1,1): error CS1002: ; expected", b"")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(build.BuildError, match="CS1002"):
        build.build_for(tmp_path / "Proj", cfg, 2027, assembly_name="Neutral")
    command = seen[0]
    assert "-p:AcadVersion=2027" in command and "-p:AcadTfm=net10.0-windows" in command  # R26 = .NET 10 (F31)
    assert str(tmp_path / "Proj" / "bin" / "acad26") in command
    assert "-p:AssemblyName=Neutral" in command
    assert build.output_dir(tmp_path, cfg, 2025) == build.output_dir(tmp_path, cfg, 2026)  # one R25 build


def test_synthetic_bundle_and_kit(cfg: MtaConfig, tmp_path: Path) -> None:
    dll = tmp_path / "Sd99.dll"
    dll.write_bytes(b"MZ")
    bundle = make_bundle(
        [dll],
        tmp_path / "pkgs",
        name="Sd99",
        commands=["SD99_GO"],
        load_on_command=True,
        extra_files={"Contents/setup.ps1": b""},
    )
    manifest = parse_package_contents(manifest_path(bundle, "PackageContents.xml"))  # type: ignore[arg-type]
    assert manifest.components[0].commands[0].global_name == "SD99_GO"
    assert manifest.components[0].load_reasons == ["LoadOnCommandInvocation"]
    assert find_bundles(bundle.parent) == [bundle]
    kit = make_kit(bundle, tmp_path / "kits", "mta.sd99", [2026])
    check = validate_kit(kit, cfg.thresholds.kit, cfg.thresholds.extract)
    assert check.ok, check.problems
    assert yaml.safe_load((kit / "submission.yaml").read_text("utf-8"))["products"][0]["versions"] == [2026]


def test_repo_root_runs_are_short(cfg: MtaConfig) -> None:
    """The default data dir keeps run paths under the /isolate limit (F28)."""
    longest = len(str((REPO_ROOT / ".mta" / "runs" / "r000000" / "profile").resolve()))
    assert longest <= cfg.thresholds.coreconsole.max_profile_path
