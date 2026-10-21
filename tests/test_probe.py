"""Step 11: probe identity and build, event-file reader, core-console launcher (unit level, no AutoCAD)."""

import dataclasses
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil
import pytest
from typer.testing import CliRunner

from mta.adapters.autocad import console, probe
from mta.adapters.autocad.console import ConsoleError, run_core_console, write_script
from mta.adapters.autocad.events import read_events
from mta.adapters.autocad.probe import ProbeBuildError, build_probe, probe_dll, render_identity
from mta.cli.app import app
from mta.config import REPO_ROOT, ConfigError, MtaConfig, load_config

# ---- identity --------------------------------------------------------------------------------------------


def test_render_identity_uses_the_config(cfg: MtaConfig) -> None:
    text = render_identity(cfg.probe_identity.autocad)
    assert 'public const string Load = "WSA_LOAD";' in text
    assert 'public const string EventsFile = "session.log";' in text
    assert 'public const string LispFunction = "wsa-note";' in text
    assert not re.search(
        "mta|probe|test", text.split("\n", 1)[1].replace("mta probe build", ""), re.IGNORECASE
    )


@pytest.fixture
def config_copy(tmp_path: Path) -> Path:
    shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
    shutil.copytree(REPO_ROOT / "data", tmp_path / "data")
    return tmp_path / "config"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("end: WSA_END", 'end: WSA_END"; System.Diagnostics.Process.Start("x', "end"),  # C# injection
        ("load: WSA_LOAD", "load: wsa_load", "load"),
        ("events_file: session.log", "events_file: ../escape.log", "events_file"),
        ("events_file: session.log", "events_file: probe-events.ndjson", "reveal the test environment"),
        ("lisp_function: wsa-note", "lisp_function: wsa note", "lisp_function"),
    ],
)
def test_identity_names_are_validated(config_copy: Path, old: str, new: str, message: str) -> None:
    path = config_copy / "probe_identity.yaml"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(ConfigError, match=re.escape(message)):
        load_config(config_copy)


# ---- build -----------------------------------------------------------------------------------------------


def _completed(code: int, stdout: bytes = b"") -> Any:
    return lambda *a, **k: subprocess.CompletedProcess(a, code, stdout, b"")


def test_build_failures(cfg: MtaConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", _completed(1, b"x.cs(3,1): error CS0103: name 'Foo' missing\nother")
    )
    with pytest.raises(ProbeBuildError, match="CS0103"):
        build_probe(cfg)

    def missing(*_: object, **__: object) -> None:
        raise FileNotFoundError("dotnet")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(ProbeBuildError, match="could not run"):
        build_probe(cfg)
    monkeypatch.setattr(subprocess, "run", _completed(0))
    monkeypatch.setattr(probe, "probe_dll", lambda c, conf="Release": Path("nowhere.dll"))
    with pytest.raises(ProbeBuildError, match="missing"):
        build_probe(cfg)


def test_cli_probe_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mta.cli.probe_cmds.installed_versions", lambda cfg: [2025, 2026, 2027])
    built: list[int] = []

    def fake(cfg: MtaConfig, acad_version: int) -> Path:
        built.append(acad_version)
        return probe_dll(cfg, acad_version)

    monkeypatch.setattr("mta.cli.probe_cmds.build_probe", fake)
    output = CliRunner().invoke(app, ["probe", "build"]).output
    assert built == [2025, 2027]  # 2026 shares 2025's API major (R25): built once
    assert "probe built for AutoCAD 2027" in output

    def fail(*_: object, **__: object) -> Path:
        raise ProbeBuildError("no AutoCAD")

    monkeypatch.setattr("mta.cli.probe_cmds.build_probe", fail)
    result = CliRunner().invoke(app, ["probe", "build", "--acad-version", "2026"])
    assert result.exit_code == 1 and "no AutoCAD" in result.output
    monkeypatch.setattr("mta.cli.probe_cmds.installed_versions", lambda cfg: [])
    assert "no AutoCAD installed" in CliRunner().invoke(app, ["probe", "build"]).output


def test_built_probe_reveals_nothing(cfg: MtaConfig) -> None:
    """Constitution §11: no 'mta' / 'probe' / 'test' anywhere in the binary (strings, metadata, PDB path)."""
    dll = probe_dll(cfg, 2026)
    if not dll.is_file():
        pytest.skip("probe not built here (needs AutoCAD: `mta probe build`)")
    text = dll.read_bytes().replace(b"\x00", b"").decode("latin-1")
    assert not re.findall(r"mta|probe|test|marketplace", text, re.IGNORECASE)


# ---- events ----------------------------------------------------------------------------------------------


def _event(seq: int, type_: str, **data: Any) -> str:
    return json.dumps(
        {"v": 1, "seq": seq, "ts": "2026-10-19T10:00:00.000Z", "run_id": "r", "type": type_, "data": data}
    )


def _write(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_clean_event_stream(tmp_path: Path) -> None:
    log = read_events(
        _write(
            tmp_path / "e.log",
            _event(1, "session.start"),
            _event(2, "host.ready", startup_ms=5),
            "",
            _event(3, "session.shutdown", reason="end"),
        )
    )
    assert log.clean and log.started and log.shut_down
    assert [e.type for e in log.of_type("host.ready")] == ["host.ready"]


@pytest.mark.parametrize(
    ("lines", "problem"),
    [
        ([_event(1, "session.start"), _event(3, "session.shutdown")], "seq 3, expected 2"),
        ([_event(1, "session.start"), "{broken", _event(2, "session.shutdown")], "line 2: unreadable"),
        (
            [_event(1, "session.start").replace('"v": 1', '"v": 2'), _event(2, "session.shutdown")],
            "version 2",
        ),
    ],
)
def test_damaged_streams(tmp_path: Path, lines: list[str], problem: str) -> None:
    log = read_events(_write(tmp_path / "e.log", *lines))
    assert not log.clean
    assert any(problem in p for p in log.problems), log.problems


def test_crash_and_internal_error_are_not_clean(tmp_path: Path) -> None:
    crashed = read_events(
        _write(tmp_path / "a.log", _event(1, "session.start"), _event(2, "exception.first_chance"))
    )
    assert not crashed.clean and not crashed.shut_down and not crashed.problems
    errored = read_events(
        _write(
            tmp_path / "b.log",
            _event(1, "session.start"),
            _event(2, "session.error", message="x"),
            _event(3, "session.shutdown"),
        )
    )
    assert not errored.clean
    missing = read_events(tmp_path / "none.log")
    assert not missing.started and "never started" in missing.problems[0]


# ---- console launcher ------------------------------------------------------------------------------------


def test_script_is_lf_only(tmp_path: Path) -> None:
    raw = write_script(tmp_path / "s.scr", ["FILEDIA 0", "QUIT", "Y"]).read_bytes()
    assert raw == b"FILEDIA 0\nQUIT\nY\n" and b"\r" not in raw


def test_long_run_folder_is_refused(cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console, "core_console", lambda c, y: Path("accoreconsole.exe"))
    deep = tmp_path / ("x" * 90)
    deep.mkdir()
    with pytest.raises(ConsoleError, match="F28"):
        run_core_console(cfg, 2026, deep, deep / "s.scr", env={}, timeout_s=5)


def test_missing_core_console(cfg: MtaConfig) -> None:
    hosts = cfg.hosts.model_copy(deep=True)
    hosts.hosts["autocad"].versions[0].install_dir = "Z:/nowhere"
    year = hosts.hosts["autocad"].versions[0].year
    import dataclasses

    with pytest.raises(ConsoleError, match="not found"):
        console.core_console(dataclasses.replace(cfg, hosts=hosts), year)


OUTPUT = "Command: QUIT\n"


class _FakeProcess:
    """Writes console output to the stdout file and exits after `polls` polls (never, if None)."""

    def __init__(self, stdout: Any, polls: int | None, code: int = 0) -> None:
        self.pid, self._polls, self._code = 4242, polls, code
        self.returncode: int | None = None
        stdout.write(OUTPUT.encode("utf-16-le"))

    def poll(self) -> int | None:
        if self._polls is not None:
            self._polls -= 1
            if self._polls <= 0:
                self.returncode = self._code
        return self.returncode

    def wait(self) -> int:
        self.returncode = self._code if self.returncode is None else self.returncode
        return self.returncode


@pytest.fixture
def short_run_dir() -> Any:
    run_dir = REPO_ROOT / ".mta" / "unit-run"  # short path, as real runs need (F28)
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)
    yield run_dir
    shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.parametrize("hang", [False, True])
def test_run_core_console(
    cfg: MtaConfig, monkeypatch: pytest.MonkeyPatch, short_run_dir: Path, hang: bool
) -> None:
    calls: list[list[str]] = []
    killed: list[int] = []
    monkeypatch.setattr(console, "core_console", lambda c, y: Path("accoreconsole.exe"))
    monkeypatch.setattr(console, "_kill_tree", killed.append)

    def popen(cmd: list[str], **kw: Any) -> _FakeProcess:
        calls.append(cmd)
        return _FakeProcess(kw["stdout"], None if hang else 2)

    monkeypatch.setattr(subprocess, "Popen", popen)
    script = short_run_dir / "s.scr"
    result = run_core_console(
        cfg, 2026, short_run_dir, script, env={"X": "1"}, timeout_s=0.5, drawing=Path("a.dwg")
    )
    assert result.output == OUTPUT
    assert (short_run_dir / "console.stdout.log").read_text("utf-8") == OUTPUT
    command = calls[0]
    assert command[:3] == ["accoreconsole.exe", "/i", "a.dwg"]
    assert "/isolate" in command and "/product" in command
    assert (result.timed_out, result.exit_code) == ((True, None) if hang else (False, 0))
    assert killed == ([4242] if hang else [])
    assert not result.crashed  # a hang is a timeout, not a crash


def test_crash_reporter_then_stuck_console_is_ended(
    cfg: MtaConfig, monkeypatch: pytest.MonkeyPatch, short_run_dir: Path
) -> None:
    """ADR-0003 F30: after the reporter is suppressed the console may never exit; the runner ends it."""
    fast = dataclasses.replace(
        cfg,
        thresholds=cfg.thresholds.model_copy(
            update={"coreconsole": cfg.thresholds.coreconsole.model_copy(update={"crash_exit_grace_s": 0})}
        ),
    )
    monkeypatch.setattr(console, "core_console", lambda c, y: Path("accoreconsole.exe"))
    monkeypatch.setattr(console, "_kill_tree", lambda pid: None)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: _FakeProcess(kw["stdout"], None, code=15))
    monkeypatch.setattr(
        console._CrashReporterGuard, "sweep_children", lambda self: self.killed.append("senddmp.exe (pid 1)")
    )
    monkeypatch.setattr(console._CrashReporterGuard, "sweep_orphans", lambda self, settle_s: None)
    result = run_core_console(fast, 2026, short_run_dir, short_run_dir / "s.scr", env={}, timeout_s=30)
    assert result.terminated_after_crash and result.crashed and not result.timed_out
    assert result.exit_hex == "0x0000000F"


def test_orphan_reporter_is_matched_by_console_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        def __init__(self, pid: int, name: str, cmdline: list[str]) -> None:
            self.pid, self.info = pid, {"name": name, "cmdline": cmdline}
            self.killed = False

        def name(self) -> str:
            return str(self.info["name"])

        def children(self, recursive: bool = False) -> list["Proc"]:
            return []

        def kill(self) -> None:
            self.killed = True

    ours = Proc(1, "senddmp.exe", ["senddmp.exe", "4242", "123"])
    other = Proc(2, "senddmp.exe", ["senddmp.exe", "999", "123"])
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [ours, other])
    guard = console._CrashReporterGuard(["senddmp.exe"], 4242)
    guard.sweep_orphans(settle_s=0)
    assert ours.killed and not other.killed  # another AutoCAD's crash report is left alone
    assert guard.killed == ["senddmp.exe (pid 1)"]
