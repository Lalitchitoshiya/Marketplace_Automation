"""One AcCoreConsole session: run folder, generated script, launch, events (design.md §5.1, §5.3, §5.6).

Run folder (kept short, ADR-0003 F28):

    runs/<run_id>/
      probe/            the probe DLL (loaded first, F11)
      plugin/           copy of the deployed payload; frames from here are "plugin" frames
      profile/          isolated AutoCAD user profile (/isolate)
      <plan_file>       plan for the probe; <events_file>: its NDJSON events (names from probe_identity.yaml)
      session.scr       generated script (LF only, F3)
      console.stdout.log
      dumps/            WER dumps of this process, if LocalDumps is configured
"""

import json
import re
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from mta.adapters.autocad.console import ConsoleError, ConsoleRun, run_core_console, write_script
from mta.adapters.autocad.events import ProbeLog, read_events
from mta.config import MtaConfig

Loader = Literal["netload", "arx", "lisp", "none"]
LOADERS: dict[str, Loader] = {
    ".dll": "netload",
    ".arx": "arx",
    ".crx": "arx",
    ".dbx": "arx",
    ".lsp": "lisp",
    ".fas": "lisp",
    ".vlx": "lisp",
}


def loader_for(path: str) -> Loader:
    return LOADERS.get(Path(path).suffix.lower(), "none")


@dataclass(frozen=True)
class Component:
    name: str
    path: str  # relative to the payload root
    loader: Loader
    gui_required: bool = False


@dataclass(frozen=True)
class RunLayout:
    root: Path
    probe_dir: Path
    plugin_dir: Path
    plan: Path
    events: Path
    script: Path

    @property
    def run_id(self) -> str:
        return self.root.name


def new_run_id() -> str:
    return f"r{secrets.token_hex(3)}"


def prepare_run(
    cfg: MtaConfig, runs_root: Path, probe: Path, payload: Path | None, components: list[Component]
) -> RunLayout:
    identity = cfg.probe_identity.autocad
    root = (runs_root / new_run_id()).resolve()
    layout = RunLayout(
        root,
        root / "probe",
        root / "plugin",
        root / identity.plan_file,
        root / identity.events_file,
        root / "session.scr",
    )
    layout.probe_dir.mkdir(parents=True)
    shutil.copy2(probe, layout.probe_dir / probe.name)
    if payload is not None:
        shutil.copytree(payload, layout.plugin_dir, symlinks=True)
    else:
        layout.plugin_dir.mkdir()
    plan = {
        "v": 1,
        "run_id": layout.run_id,
        "plugin_dir": str(layout.plugin_dir),
        "components": [
            {"name": c.name, "module": str(layout.plugin_dir / c.path), "loader": c.loader}
            for c in components
            if c.loader in ("netload", "arx")
        ],
    }
    layout.plan.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    return layout


def _lisp_text(value: str) -> str:
    return value.replace("\\", "/").replace('"', '\\"')


class ScriptBuilder:
    """Lines for one session. Never a bare blank line (it repeats the last command, F4)."""

    def __init__(
        self, cfg: MtaConfig, layout: RunLayout, probe_name: str, components: list[Component] | None = None
    ) -> None:
        identity = cfg.probe_identity.autocad
        self._commands = identity.commands
        self._note = identity.lisp_function
        self._layout = layout
        # Every folder explicitly: the recursive "<dir>/..." form left plugins silently unloaded (step 12).
        folders = [layout.probe_dir, *sorted({(layout.plugin_dir / c.path).parent for c in components or []})]
        trusted = ";".join(f.as_posix() for f in folders)
        # F13: TRUSTEDPATHS instead of SECURELOAD 0, so security behaves as customers see it.
        self.lines: list[str] = [
            "FILEDIA 0",
            f'(setvar "TRUSTEDPATHS" "{_lisp_text(trusted)}")',
            "NETLOAD",
            str(layout.probe_dir / probe_name),  # probe first (F11)
        ]

    def load(self, component: Component) -> "ScriptBuilder":
        if component.loader in ("netload", "arx"):
            self.lines += [self._commands.load, component.name]
        elif component.loader == "lisp":
            path = _lisp_text(str(self._layout.plugin_dir / component.path))
            # If (load) fails, AutoLISP aborts the expression, so the note is never sent: missing = failed.
            self.lines += [
                self._commands.mark,
                f"begin load:{component.name}",
                f'({self._note} "lisp-load" "{_lisp_text(component.name)}" (progn (load "{path}") "ok"))',
                self._commands.mark,
                f"end load:{component.name}",
            ]
        return self

    def defined(self, names: list[str]) -> "ScriptBuilder":
        """(getcname) per command (ADR-0003 F18): CMD-001 and the runtime half of CMD-003."""
        for name in names:
            quoted = _lisp_text(name)
            self.lines.append(f'({self._note} "defined" "{quoted}" (getcname "{quoted}"))')
        return self

    def raw(self, *lines: str) -> "ScriptBuilder":
        self.lines += lines
        return self

    def end(self, quit_lines: list[str]) -> list[str]:
        return [*self.lines, self._commands.end, *quit_lines]


@dataclass(frozen=True)
class InfraPattern:
    id: str
    pattern: str
    hint: str


def infra_patterns(cfg: MtaConfig) -> list[InfraPattern]:
    facts = cfg.hosts.hosts["autocad"].core_console
    if facts is None or facts.errors_file is None:
        return []
    data = yaml.safe_load((cfg.data_root / facts.errors_file).read_text(encoding="utf-8")) or []
    return [InfraPattern(**item) for item in data]


@dataclass
class SessionResult:
    kind: str  # "baseline", "load", "smoke", ...
    year: int
    layout: RunLayout
    console: ConsoleRun | None
    log: ProbeLog
    infra_error: str | None = None  # set => the run says nothing about the plugin (ERROR, never FAIL)
    notes: list[str] = field(default_factory=list)

    def excerpt(self, lines: int = 25) -> str:
        text = self.console.output if self.console else ""
        return "\n".join(text.strip().splitlines()[-lines:])


def run_session(
    cfg: MtaConfig, year: int, kind: str, layout: RunLayout, lines: list[str], timeout_s: float
) -> SessionResult:
    write_script(layout.script, lines)
    return _run(cfg, year, kind, layout, timeout_s, None)


def _run(
    cfg: MtaConfig,
    year: int,
    kind: str,
    layout: RunLayout,
    timeout_s: float,
    stall: "EventSilence | None",
    drawing: Path | None = None,
) -> SessionResult:
    identity = cfg.probe_identity.autocad
    try:
        console = run_core_console(
            cfg,
            year,
            layout.root,
            layout.script,
            env={identity.run_dir_env: str(layout.root)},
            timeout_s=timeout_s,
            stall=stall,
            drawing=drawing,
        )
    except ConsoleError as exc:
        return SessionResult(kind, year, layout, None, read_events(layout.events), infra_error=str(exc))
    result = SessionResult(kind, year, layout, console, read_events(layout.events))
    for item in infra_patterns(cfg):
        if re.search(item.pattern, console.output, re.IGNORECASE):
            result.infra_error = f"{item.hint} (console: /{item.id}/)"
            break
    if console.crash_reporter_killed:
        result.notes.append(f"crash reporter suppressed: {', '.join(console.crash_reporter_killed)}")
    return result


def session_timeout(cfg: MtaConfig, components: int, extra_s: float = 0) -> float:
    t = cfg.thresholds
    return (
        t.coreconsole.startup_timeout_s
        + components * t.load.per_component_timeout_s
        + t.coreconsole.quit_timeout_s
        + extra_s
    )


def quit_lines(cfg: MtaConfig) -> list[str]:
    facts = cfg.hosts.hosts["autocad"].core_console
    return list(facts.quit_lines) if facts else ["QUIT", "Y"]


def baseline(cfg: MtaConfig, year: int, runs_root: Path, probe: Path) -> SessionResult:
    """Probe only, no plugin (P1-R18): proves the environment works before any plugin is judged."""
    layout = prepare_run(cfg, runs_root, probe, None, [])
    lines = ScriptBuilder(cfg, layout, probe.name).end(quit_lines(cfg))
    result = run_session(cfg, year, "baseline", layout, lines, session_timeout(cfg, 0))
    if result.infra_error is None and (
        result.console is None or result.console.exit_code != 0 or not result.log.clean
    ):
        problems = "; ".join(result.log.problems) or "event stream incomplete"
        console = result.console
        state = f"exit {console.exit_hex}, timed out {console.timed_out}" if console else "not started"
        result.infra_error = f"baseline failed ({state}): {problems}"
    return result


def load_session(
    cfg: MtaConfig,
    year: int,
    runs_root: Path,
    probe: Path,
    payload: Path,
    components: list[Component],
    expected_commands: list[str],
) -> SessionResult:
    layout = prepare_run(cfg, runs_root, probe, payload, components)
    builder = ScriptBuilder(cfg, layout, probe.name, components)
    for component in components:
        builder.load(component)
    builder.raw(cfg.probe_identity.autocad.commands.enumerate).defined(expected_commands)
    loadable = [c for c in components if c.loader != "none"]
    return run_session(
        cfg, year, "load", layout, builder.end(quit_lines(cfg)), session_timeout(cfg, len(loadable))
    )


class EventSilence:
    """Per-step watchdog (P1-R15): the event file is silent too long while a load or smoke mark is open."""

    def __init__(self, events: Path, command_s: float, load_s: float) -> None:
        self._events, self._command_s, self._load_s = events, command_s, load_s
        self._size = -1
        self._changed = time.monotonic()

    def _open_step(self) -> str | None:
        try:
            lines = self._events.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind, data = event.get("type"), event.get("data") or {}
            if kind == "component.load.begin":
                return "load"
            if (
                kind == "mark"
                and data.get("phase") == "begin"
                and not str(data.get("label", "")).startswith("load:")
            ):
                return "command"
            if kind in ("component.load.end", "mark"):
                return None
        return None

    def __call__(self) -> bool:
        try:
            size = self._events.stat().st_size
        except OSError:
            return False  # not started yet: the overall startup budget applies
        now = time.monotonic()
        if size != self._size:
            self._size, self._changed = size, now
            return False
        step = self._open_step()
        limit = self._load_s if step == "load" else self._command_s if step == "command" else None
        return limit is not None and now - self._changed > limit


def smoke_session(
    cfg: MtaConfig,
    year: int,
    runs_root: Path,
    probe: Path,
    payload: Path,
    components: list[Component],
    commands: list[str],
) -> SessionResult:
    """Loads, then each command in marks, followed by the cancel lines (F5; never bare Enter, F4)."""
    layout = prepare_run(cfg, runs_root, probe, payload, components)
    builder = ScriptBuilder(cfg, layout, probe.name, components)
    for component in components:
        builder.load(component)
    mark = cfg.probe_identity.autocad.commands.mark
    facts = cfg.hosts.hosts["autocad"].core_console
    cancel = facts.cancel_line if facts else "(command)"
    smoke = cfg.thresholds.smoke
    for name in commands:
        builder.raw(mark, f"begin {name}", name, *([cancel] * smoke.cancel_lines), mark, f"end {name}")
    loadable = [c for c in components if c.loader != "none"]
    timeout = session_timeout(cfg, len(loadable), extra_s=len(commands) * smoke.per_command_timeout_s)
    write_script(layout.script, builder.end(quit_lines(cfg)))
    silence = EventSilence(
        layout.events, smoke.per_command_timeout_s, cfg.thresholds.load.per_component_timeout_s
    )
    return _run(cfg, year, "smoke", layout, timeout, silence)
