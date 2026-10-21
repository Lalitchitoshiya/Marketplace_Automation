"""Dynamic stage for AutoCAD (steps 12-13): baseline, component loading, command checks and smoke runs.

Writes `dynamic.json` (sessions and command outcomes per version) and `checks/dynamic.json` into the job
folder. Runs live under `<data_dir>/runs/` so their paths stay short (ADR-0003 F28).
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mta.adapters.autocad.console import installed_versions
from mta.adapters.autocad.probe import probe_dll
from mta.adapters.autocad.session import (
    Component,
    SessionResult,
    baseline,
    load_session,
    loader_for,
    smoke_session,
)
from mta.config import REPO_ROOT, MtaConfig
from mta.engine.load_rules import load_checks
from mta.engine.smoke_rules import CommandOutcome, classify, cmd001, command_checks
from mta.intake.pipeline import IntakeResult
from mta.models import CheckResult, Source, Status
from mta.scenario.autocad import ScenarioRun, run_scenario, scenario_checks, scenario_sources
from mta.scenario.model import ScenarioError, load_scenario
from mta.static.results import ResultSink
from mta.static.stage import StaticOutcome

DYNAMIC_CHECKS = (
    "LOD-001",
    "LOD-002",
    "LOD-003",
    "CMD-001",
    "CMD-002",
    "CMD-004",
    "RUN-001",
    "RUN-002",
    "RUN-003",
)
_PER_COMPONENT = ("LOD-001", "LOD-002")
_HOST = "autocad"


@dataclass
class DynamicOutcome:
    results: list[CheckResult] = field(default_factory=list)
    sessions: list[SessionResult] = field(default_factory=list)
    commands: dict[int, list[CommandOutcome]] = field(default_factory=dict)  # per version
    scenarios: list[ScenarioRun] = field(default_factory=list)


def components_for(static: StaticOutcome, year: int) -> list[Component]:
    gui = {c.path: c.gui_required for c in static.binary.components} if static.binary else {}
    if static.bundle and static.bundle.components:
        return [
            Component(c.app_name, c.path, loader_for(c.path), gui.get(c.path, False))
            for c in static.bundle.components
            if c.path and c.exists and year in c.host_versions and c.loads_in_plain_host
        ]
    loose = static.binary.components if static.binary else []
    return [Component(c.app_name, c.path, loader_for(c.path), c.gui_required) for c in loose if c.path]


def commands_by_component(static: StaticOutcome) -> dict[str, list[str]]:
    """Component name -> registered binary commands plus manifest commands."""
    found: dict[str, list[str]] = {}
    paths = {c.path: c.app_name for c in static.bundle.components} if static.bundle else {}
    for b in static.binary.components if static.binary else []:
        found.setdefault(paths.get(b.path, b.app_name), []).extend(b.commands)
    for c in static.bundle.components if static.bundle else []:
        found.setdefault(c.app_name, []).extend(c.commands)
    return {name: sorted(set(cmds), key=str.upper) for name, cmds in found.items()}


def expected_commands(static: StaticOutcome) -> list[str]:
    return sorted({c for cmds in commands_by_component(static).values() for c in cmds}, key=str.upper)


def _blocked_by_binary(static: StaticOutcome, year: int) -> str | None:
    fails = [
        f"{r.check_id} {r.target.subject}"
        for r in (static.binary.results if static.binary else [])
        if r.check_id in ("BIN-001", "BIN-002") and r.status is Status.FAIL and r.target.host_version == year
    ]
    return f"the binary cannot load in AutoCAD {year} ({'; '.join(fails)})" if fails else None


def _skip_all(sink: ResultSink, year: int, components: list[Component], status: Status, reason: str) -> None:
    for c in components:
        for check_id in _PER_COMPONENT:
            sink.add(
                check_id, status, reason, subject=f"component:{c.name}", host_id=_HOST, host_version=year
            )
    for check_id in DYNAMIC_CHECKS:
        if check_id not in _PER_COMPONENT:
            sink.add(check_id, status, reason, host_id=_HOST, host_version=year)


def _smoke(
    cfg: MtaConfig,
    year: int,
    runs_root: Path,
    probe: Path,
    payload: Path,
    components: list[Component],
    commands: list[str],
    outcome: DynamicOutcome,
) -> list[CommandOutcome]:
    """Batch first; after an anomaly, the remaining commands continue in a fresh process (P1-R15)."""
    decided: list[CommandOutcome] = []
    remaining = list(commands)
    while remaining:
        session = smoke_session(cfg, year, runs_root, probe, payload, components, remaining)
        outcome.sessions.append(session)
        if session.infra_error:
            decided += [
                CommandOutcome(c, "not_run", session.infra_error, session.excerpt()) for c in remaining
            ]
            break
        done, rest = classify(session, remaining)
        if not done:  # no progress: the session never reached the commands
            reason = "the session ended before the commands ran"
            run_id = session.layout.run_id
            decided += [CommandOutcome(c, "not_run", reason, session.excerpt(), run_id) for c in rest]
            break
        decided += done
        remaining = rest
    return decided


def _scenarios(
    intake: IntakeResult,
    cfg: MtaConfig,
    year: int,
    runs_root: Path,
    probe: Path,
    payload: Path,
    components: list[Component],
    outcome: DynamicOutcome,
) -> list[CheckResult]:
    """WFL-001/002 for the kit's and the reviewers' scenarios (P1-R19)."""
    kit_root = intake.package.parent.parent
    sources = scenario_sources(
        kit_root, intake.submission.app_id, intake.submission.reviewer_inputs.scenarios, REPO_ROOT
    )
    runs: list[ScenarioRun] = []
    invalid = ResultSink(cfg, source=Source.DYNAMIC)
    for source in sources:
        try:
            scenario = load_scenario(source)
        except ScenarioError as exc:
            for check_id in ("WFL-001", "WFL-002"):
                subject = f"scenario:{source.name}"
                invalid.add(check_id, Status.NEEDS_REVIEW, "scenario file is invalid", str(exc),
                            subject=subject, host_id=_HOST, host_version=year)  # fmt: skip
            continue
        roots = [kit_root / "samples", kit_root, source.parent, REPO_ROOT / "samples"]
        run = run_scenario(cfg, year, runs_root, probe, payload, components, scenario, source, roots)
        runs.append(run)
        if run.session:
            outcome.sessions.append(run.session)
    outcome.scenarios += runs
    return invalid.sorted() + scenario_checks(cfg, runs)


def run_dynamic_stage(
    intake: IntakeResult, static: StaticOutcome, cfg: MtaConfig, data_dir: Path
) -> DynamicOutcome:
    outcome = DynamicOutcome()
    sink = ResultSink(cfg, source=Source.DYNAMIC)
    payload = static.extraction.payload_dir
    installed = installed_versions(cfg)
    runs_root = (data_dir / "runs").resolve()
    runs_root.mkdir(parents=True, exist_ok=True)
    by_component = commands_by_component(static)

    for year in static.versions(intake):
        components = components_for(static, year)
        probe = probe_dll(cfg, year)
        blocked = _blocked_by_binary(static, year)
        reason = None
        status = Status.SKIPPED
        if not static.gate.dynamic_allowed or payload is None:
            reason = "dynamic phase blocked: " + "; ".join(static.gate.reasons)
        elif year not in installed:
            reason = f"AutoCAD {year} is not installed on this machine"
        elif not components:
            reason = f"no component targets AutoCAD {year}"
        elif blocked:
            reason = blocked
        elif not probe.is_file():
            reason, status = f"probe not built for AutoCAD {year}: run `mta probe build`", Status.ERROR
        if reason is not None or payload is None:
            _skip_all(sink, year, components, status, reason or "no payload")
            continue

        base = baseline(cfg, year, runs_root, probe)
        outcome.sessions.append(base)
        if base.infra_error:
            _skip_all(sink, year, components, Status.ERROR, base.infra_error)
            continue

        expected = expected_commands(static)
        load = load_session(cfg, year, runs_root, probe, payload, components, expected)
        outcome.sessions.append(load)
        lod = load_checks(cfg, components, load)
        sink.items += lod
        if load.infra_error:
            _skip_all(sink, year, [], Status.ERROR, load.infra_error)
            continue
        failed = {
            r.target.subject.removeprefix("component:")
            for r in lod
            if r.check_id == "LOD-001" and r.status is not Status.PASS
        }
        skipped = [c for name in failed for c in by_component.get(name, [])]
        sink.items += cmd001(cfg, year, load, expected, skipped)

        defined_events = load.log.of_type("command.defined")
        defined = {str(e.data.get("name")).upper() for e in defined_events if e.data.get("defined")}
        to_run = [c for c in expected if c.upper() in defined and c not in skipped]
        commands = _smoke(cfg, year, runs_root, probe, payload, components, to_run, outcome) if to_run else []
        outcome.commands[year] = commands
        smoke_sessions = [s for s in outcome.sessions if s.year == year and s.kind in ("load", "smoke")]
        sink.items += command_checks(cfg, year, commands, smoke_sessions)
        sink.items += _scenarios(intake, cfg, year, runs_root, probe, payload, components, outcome)

    outcome.results = sink.sorted()
    _write(intake.job_dir, outcome)
    return outcome


def _write(job_dir: Path, outcome: DynamicOutcome) -> None:
    sessions = [
        {
            "kind": s.kind,
            "year": s.year,
            "run_id": s.layout.run_id,
            "run_dir": str(s.layout.root),
            "exit": s.console.exit_hex if s.console else None,
            "timed_out": s.console.timed_out if s.console else None,
            "crashed": s.console.crashed if s.console else None,
            "duration_s": round(s.console.duration_s, 1) if s.console else None,
            "clean": s.log.clean,
            "events": len(s.log.events),
            "infra_error": s.infra_error,
            "notes": s.notes,
            "dumps": [str(d) for d in s.console.dumps] if s.console else [],
        }
        for s in outcome.sessions
    ]
    commands = {str(year): [asdict(o) for o in outs] for year, outs in outcome.commands.items()}
    scenarios = [
        {
            "scenario": r.scenario.scenario,
            "source": str(r.source),
            "year": r.year,
            "run_id": r.session.layout.run_id if r.session else None,
            "skipped": r.skipped,
            "step_errors": r.step_errors,
            "failures": r.failures,
            "assertions": r.assertions,
        }
        for r in outcome.scenarios
    ]
    data = {"sessions": sessions, "commands": commands, "scenarios": scenarios}
    summary = json.dumps(data, indent=2) + "\n"
    (job_dir / "dynamic.json").write_text(summary, encoding="utf-8")
    (job_dir / "checks").mkdir(exist_ok=True)
    results = [r.model_dump(mode="json", exclude_none=True) for r in outcome.results]
    (job_dir / "checks" / "dynamic.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
