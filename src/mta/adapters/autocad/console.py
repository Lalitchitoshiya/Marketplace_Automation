"""Launching AcCoreConsole (design.md §5.4).

Facts from ADR-0003:
- scripts must be LF-only (F3), and output is UTF-16LE (F2);
- a waiting prompt never ends by itself (F6), so the watchdog always kills the whole process tree on timeout;
- `/isolate` fails with long run paths (F28);
- a crash starts Autodesk's crash reporter, which opens a dialog and may send data (F29). It is killed as soon
  as it appears.
"""

import contextlib
import os
import re
import shutil
import subprocess
import time
import winreg
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from mta.config import MtaConfig

_POLL_S = 0.25
_WER_KEY = r"SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\accoreconsole.exe"


class ConsoleError(Exception):
    """AcCoreConsole cannot be used for this run (an MTA problem: ERROR)."""


@dataclass(frozen=True)
class ConsoleRun:
    exit_code: int | None  # None = killed by the watchdog
    timed_out: bool
    output: str
    duration_s: float
    pid: int = 0
    crash_reporter_killed: list[str] = field(default_factory=list)
    dumps: list[Path] = field(default_factory=list)
    terminated_after_crash: bool = False  # crashed, reporter suppressed, then stuck: ended by the runner

    @property
    def crashed(self) -> bool:
        """Non-zero exit, or the crash reporter started (it only starts on a crash, F29)."""
        return (
            self.terminated_after_crash
            or (self.exit_code not in (None, 0))
            or bool(self.crash_reporter_killed)
        )

    @property
    def exit_hex(self) -> str | None:
        return None if self.exit_code is None else f"0x{self.exit_code & 0xFFFFFFFF:08X}"


def core_console(cfg: MtaConfig, year: int, host_id: str = "autocad") -> Path:
    version = cfg.hosts.hosts[host_id].version(year)
    exe = Path(version.install_dir) / (version.headless_exe or "accoreconsole.exe")
    if not exe.is_file():
        raise ConsoleError(f"AutoCAD {year} core console not found at {exe}")
    return exe


def installed_versions(cfg: MtaConfig, host_id: str = "autocad") -> list[int]:
    found = []
    for version in cfg.hosts.hosts[host_id].versions:
        with contextlib.suppress(ConsoleError):
            core_console(cfg, version.year, host_id)
            found.append(version.year)
    return found


def write_script(path: Path, lines: list[str]) -> Path:
    """LF only: with CRLF each CR and LF act as Enter and repeat the previous command (F3)."""
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def wer_dump_folder() -> Path | None:
    """Where WER LocalDumps writes accoreconsole.exe dumps, if configured (`mta doctor`)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _WER_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "DumpFolder")
    except OSError:
        return None
    return Path(os.path.expandvars(str(value)))


def _kill_tree(pid: int) -> None:
    try:
        root = psutil.Process(pid)
        processes = [*root.children(recursive=True), root]
    except psutil.Error:
        return
    for process in processes:
        with contextlib.suppress(psutil.Error):
            process.kill()
    psutil.wait_procs(processes, timeout=10)


class _CrashReporterGuard:
    """Kills Autodesk's crash reporter started by our console process (F29)."""

    def __init__(self, names: list[str], console_pid: int) -> None:
        self._names = {n.lower() for n in names}
        self._pid = console_pid
        self.killed: list[str] = []

    def _kill(self, process: psutil.Process) -> None:
        with contextlib.suppress(psutil.Error):
            description = f"{process.name()} (pid {process.pid})"
            for child in [*process.children(recursive=True), process]:
                with contextlib.suppress(psutil.Error):
                    child.kill()
            self.killed.append(description)

    def sweep_children(self) -> None:
        if not self._names:
            return
        try:
            children = psutil.Process(self._pid).children(recursive=True)
        except psutil.Error:
            return
        for child in children:
            with contextlib.suppress(psutil.Error):
                if child.name().lower() in self._names:
                    self._kill(child)

    def sweep_orphans(self, settle_s: float) -> None:
        """After exit: `senddmp.exe <console-pid> …` may still be starting or running."""
        if not self._names:
            return
        deadline = time.monotonic() + settle_s
        while True:
            for process in psutil.process_iter(["name", "cmdline"]):
                with contextlib.suppress(psutil.Error):
                    name = (process.info["name"] or "").lower()
                    args = process.info["cmdline"] or []
                    if name in self._names and str(self._pid) in args[1:3]:
                        self._kill(process)
            if time.monotonic() >= deadline:
                return
            time.sleep(0.5)


def run_core_console(
    cfg: MtaConfig,
    year: int,
    run_dir: Path,
    script: Path,
    *,
    env: dict[str, str],
    timeout_s: float,
    drawing: Path | None = None,
    stall: Callable[[], bool] | None = None,
) -> ConsoleRun:
    """Run one script. `stall` is polled while it runs; True means "hung", handled like a timeout."""
    facts = cfg.hosts.hosts["autocad"].core_console
    if facts is None:  # pragma: no cover - configuration guarantees the facts
        raise ConsoleError("hosts.yaml has no core_console facts for autocad")
    profile = (run_dir / "profile").resolve()
    limit = cfg.thresholds.coreconsole.max_profile_path
    if facts.isolate and len(str(profile)) > limit:
        raise ConsoleError(
            f"run folder path too long for /isolate ({len(str(profile))} > {limit} characters): AutoCAD "
            "copies deep roaming folders into it and fails past MAX_PATH (ADR-0003 F28). Use a shorter "
            "--data-dir."
        )
    profile.mkdir(parents=True, exist_ok=True)
    command = [str(core_console(cfg, year))]
    if drawing is not None:
        command += ["/i", str(drawing)]
    command += ["/s", str(script), "/l", facts.language]
    if facts.product_switch:
        command += ["/product", facts.product_switch]
    if facts.isolate:
        command += ["/isolate", f"u{run_dir.name}"[:30], str(profile)]

    stdout_path = run_dir / "console.stdout.raw"
    started = time.monotonic()
    with stdout_path.open("wb") as stdout:
        process = subprocess.Popen(  # noqa: S603 (configured AutoCAD executable, our own script)
            command,
            cwd=run_dir,
            env={**os.environ, **env},
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.STDOUT,
        )
        guard = _CrashReporterGuard(facts.crash_reporter, process.pid)
        timed_out = terminated_after_crash = False
        crash_seen_at: float | None = None
        grace = cfg.thresholds.coreconsole.crash_exit_grace_s
        while process.poll() is None:
            guard.sweep_children()
            now = time.monotonic()
            if guard.killed and crash_seen_at is None:
                crash_seen_at = now
            if crash_seen_at is not None and now - crash_seen_at > grace:
                # It has crashed already; about 1 run in 4 the console then waits forever (step 12).
                terminated_after_crash = True
                _kill_tree(process.pid)
                break
            if now - started > timeout_s or (stall is not None and stall()):
                timed_out = True
                _kill_tree(process.pid)
                break
            time.sleep(_POLL_S)
        process.wait()
    crashed = not timed_out and process.returncode != 0
    guard.sweep_orphans(settle_s=3.0 if crashed else 0.0)
    exit_code = None if timed_out else process.returncode

    output = stdout_path.read_bytes().decode(facts.output_encoding, errors="replace")
    (run_dir / "console.stdout.log").write_text(output, encoding="utf-8")
    stdout_path.unlink(missing_ok=True)
    return ConsoleRun(
        exit_code,
        timed_out,
        output,
        time.monotonic() - started,
        process.pid,
        guard.killed,
        _collect_dumps(process.pid, run_dir),
        terminated_after_crash,
    )


def _collect_dumps(pid: int, run_dir: Path) -> list[Path]:
    """WER LocalDumps names dumps `accoreconsole.exe.<pid>.dmp`; copy ours into the run folder."""
    folder = wer_dump_folder()
    if folder is None or not folder.is_dir():
        return []
    found = []
    pattern = re.compile(rf"^accoreconsole\.exe\.{pid}\.dmp$", re.IGNORECASE)
    for dump in folder.iterdir():
        if pattern.match(dump.name):
            (run_dir / "dumps").mkdir(exist_ok=True)
            found.append(Path(shutil.copy2(dump, run_dir / "dumps" / dump.name)))
    return found
