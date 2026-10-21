"""`mta doctor`: is this machine able to run MTA? (requirements.md P1-R03)

The standard check looks at installs and tools. `--deep` runs the canary plugin in each installed core console
and verifies the ADR-0003 behaviours MTA relies on, so a host update that changes them is noticed before
results are trusted.
"""

import ctypes
import json
import shutil
import tempfile
import time
import winreg
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from mta.adapters.autocad.console import core_console, installed_versions, wer_dump_folder
from mta.adapters.autocad.events import ProbeLog
from mta.adapters.autocad.probe import probe_dll
from mta.adapters.autocad.session import (
    Component,
    ScriptBuilder,
    SessionResult,
    prepare_run,
    quit_lines,
    run_session,
)
from mta.config import MtaConfig
from mta.corpus.synthetic import built_dll
from mta.static.dotnet import find_inspect
from mta.static.malware import scanner_path

Level = Literal["ok", "warn", "fail"]
WER_KEY = r"SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\accoreconsole.exe"
CHANGED = "Host behaviour changed: re-run the spike and update ADR-0003 before trusting dynamic results"


@dataclass(frozen=True)
class Item:
    name: str
    level: Level
    detail: str
    hint: str | None = None


@dataclass
class Diagnosis:
    items: list[Item] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return all(i.level != "fail" for i in self.items)

    def check(self, name: str, ok: bool, detail: str, hint: str, *, warn_only: bool = False) -> None:
        level: Level = "ok" if ok else ("warn" if warn_only else "fail")
        self.items.append(Item(name, level, detail, None if ok else hint))


def check_basic(cfg: MtaConfig, data_dir: Path) -> Diagnosis:
    d = Diagnosis()
    d.items.append(Item("config", "ok", f"{cfg.directory} (sha256 {cfg.sha256[:12]})"))
    installed = installed_versions(cfg)
    for version in cfg.hosts.hosts["autocad"].versions:
        year = version.year
        if year not in installed:
            d.items.append(Item(f"AutoCAD {year}", "warn", "not installed: its runs are SKIPPED"))
            continue
        d.items.append(Item(f"AutoCAD {year}", "ok", str(core_console(cfg, year))))
        probe = probe_dll(cfg, year)
        d.check(f"probe for {year}", probe.is_file(), str(probe), "uv run mta probe build")
    d.check(
        "installed AutoCAD", bool(installed), f"{len(installed)} version(s)", "Install AutoCAD 2025 or later"
    )
    scanner = scanner_path()
    d.check("Defender CLI", scanner.is_file(), str(scanner), "Microsoft Defender is required")
    inspect = find_inspect()
    d.check("mta-inspect", inspect is not None, str(inspect), "dotnet build dotnet/src/MtaInspect -c Release")

    runs = (data_dir / "runs").resolve()
    limit = cfg.thresholds.coreconsole.max_profile_path
    longest = len(str(runs / "r000000" / "profile"))
    try:
        runs.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=runs):
            writable = True
    except OSError:
        writable = False
    d.check("run folder writable", writable, str(runs), "Choose a writable --data-dir")
    d.check(
        "run folder path length",
        longest <= limit,
        f"{longest} of {limit} characters",
        "Use a short --data-dir such as C:\\mta (ADR-0003 F28)",
    )
    folder = wer_dump_folder()
    d.check(
        "WER LocalDumps",
        folder is not None,
        f"dumps go to {folder}" if folder else "not configured",
        "Optional extra crash evidence: run `mta doctor --fix` as administrator",
        warn_only=True,
    )
    return d


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def fix_wer(dump_folder: Path) -> str:
    """Configure WER LocalDumps for accoreconsole.exe (needs administrator rights)."""
    if not is_admin():
        return "not administrator: run `uv run mta doctor --fix` in an elevated prompt (docs/workstation.md)"
    dump_folder.mkdir(parents=True, exist_ok=True)
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, WER_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "DumpFolder", 0, winreg.REG_EXPAND_SZ, str(dump_folder))
        winreg.SetValueEx(key, "DumpType", 0, winreg.REG_DWORD, 1)  # mini dump
        winreg.SetValueEx(key, "DumpCount", 0, winreg.REG_DWORD, 20)
    return f"WER LocalDumps configured: {dump_folder}"


# ---- deep check: the canary plugin replays ADR-0003 findings -----------------------------------------------


def _marked(log: ProbeLog, label: str) -> list[str]:
    return [e.type for e in log.events if e.data.get("mark") == label]


def _canary(
    cfg: MtaConfig, year: int, runs_root: Path, kind: str, body: list[str], timeout_s: float
) -> SessionResult:
    probe = probe_dll(cfg, year)
    canary = built_dll("Canary", cfg, year)
    staging = runs_root / "canary-src"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copy2(canary, staging / canary.name)
    component = Component("Canary", canary.name, "netload")
    layout = prepare_run(cfg, runs_root, probe, staging, [component])
    builder = ScriptBuilder(cfg, layout, probe.name, [component]).load(component).raw(*body)
    return run_session(cfg, year, kind, layout, builder.end(quit_lines(cfg)), timeout_s)


def _deep_version(d: Diagnosis, cfg: MtaConfig, year: int, runs_root: Path) -> None:
    c, note = cfg.probe_identity.autocad.commands, cfg.probe_identity.autocad.lisp_function
    limit = cfg.thresholds.doctor.deep_max_start_quit_s
    started = time.monotonic()
    s = _canary(cfg, year, runs_root, "canary", [
        f'({note} "defined" "CANARY_HELLO" (getcname "CANARY_HELLO"))',
        c.mark, "begin CANARY_HELLO", "CANARY_HELLO", "(command)", c.mark, "end CANARY_HELLO",
        c.mark, "begin CANARY_PROMPT", "CANARY_PROMPT", "(command)", "(command)", c.mark, "end CANARY_PROMPT",
    ], 120)  # fmt: skip
    elapsed = time.monotonic() - started
    where = f" ({s.infra_error or s.layout.root})"
    loads = s.log.of_type("component.load.end")
    loaded = bool(loads) and loads[0].data.get("ok") is True and loads[0].data.get("loaded") is True
    defined = any(e.data.get("defined") is True for e in s.log.of_type("command.defined"))
    observed = {
        "F13 plugin loads with TRUSTEDPATHS (SECURELOAD on)": loaded,
        "F19 command events fire": _marked(s.log, "CANARY_HELLO") == ["command.start", "command.ended"],
        "F5 (command) cancels an active prompt": _marked(s.log, "CANARY_PROMPT")
        == ["command.start", "prompt", "command.cancelled"],
        "F18 getcname finds a plugin command": defined,
        "F21 no licence or startup problem": s.infra_error is None,
        f"F20 start to quit within {limit} s ({elapsed:.0f} s)": elapsed <= limit and s.log.clean,
    }
    for text, ok in observed.items():
        d.check(
            f"AutoCAD {year} {text.split()[0]}", ok, text if ok else f"{text}: NOT observed{where}", CHANGED
        )

    crash = _canary(cfg, year, runs_root, "canary-crash", ["CANARY_THROW"], 120)
    exit_hex = crash.console.exit_hex if crash.console else None
    ended = exit_hex == "0xC0000005" or bool(crash.console and crash.console.terminated_after_crash)
    caught = ended and bool(crash.log.of_type("exception.first_chance"))
    how = (
        "ended by the runner after the crash"
        if crash.console and crash.console.terminated_after_crash
        else (f"exit {exit_hex}")
    )
    d.check(f"AutoCAD {year} F8", caught, f"exception captured, then {how}", CHANGED)
    killed = crash.console.crash_reporter_killed if crash.console else []
    d.items.append(
        Item(f"AutoCAD {year} F29", "ok", "crash reporter suppressed" if killed else "no reporter started")
    )

    hang = _canary(cfg, year, runs_root, "canary-hang", ["CANARY_HANG"], 45)
    d.check(
        f"AutoCAD {year} F10", bool(hang.console and hang.console.timed_out), "watchdog ends a hang", CHANGED
    )


def check_deep(cfg: MtaConfig, data_dir: Path) -> Diagnosis:
    d = Diagnosis()
    runs_root = (data_dir / "runs").resolve()
    installed = installed_versions(cfg)
    if not installed:
        d.items.append(Item("deep check", "fail", "no AutoCAD installed"))
    for year in installed:
        if not probe_dll(cfg, year).is_file() or not built_dll("Canary", cfg, year).is_file():
            d.check(f"AutoCAD {year} deep check", False, "probe or canary not built for this version",
                    "uv run mta probe build; uv run mta corpus build")  # fmt: skip
            continue
        _deep_version(d, cfg, year, runs_root)
    summary = {i.name: i.level for i in d.items}
    (runs_root / "doctor-deep.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return d
