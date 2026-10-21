"""Running DSL scenarios in the AutoCAD core console, and WFL-001/002 (requirements.md P1-R19).

Each step becomes marked script lines (`scn<i>` windows), so the step results come from the same probe events
as the smoke runs. In-drawing assertions go through the probe's assert command. File assertions are checked
in Python after the run, against the run folder (`${RUN_DIR}`).
"""

import operator
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from mta.adapters.autocad.events import ProbeEvent
from mta.adapters.autocad.session import (
    Component,
    ScriptBuilder,
    SessionResult,
    _run,
    prepare_run,
    quit_lines,
)
from mta.config import MtaConfig
from mta.models import CheckResult, Source, Status
from mta.scenario.model import AssertStep, OpenStep, RunStep, SaveAsStep, Scenario, ScriptStep
from mta.static.results import ResultSink, excerpt

_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}
_HOST = "autocad"


@dataclass
class ScenarioRun:
    scenario: Scenario
    source: Path
    year: int
    session: SessionResult | None = None
    skipped: str | None = None
    failures: list[str] = field(default_factory=list)  # WFL-002 evidence
    step_errors: list[str] = field(default_factory=list)  # WFL-001 evidence
    assertions: int = 0


def find_sample(name: str, roots: list[Path]) -> Path | None:
    for root in roots:
        candidate = (root / name).resolve()
        if candidate.is_file():
            return candidate
    return None


def _text(value: str, run_dir: Path) -> str:
    return value.replace("${RUN_DIR}", run_dir.as_posix())


def _lisp(value: str) -> str:
    return value.replace("\\", "/").replace('"', '\\"')


def build_lines(cfg: MtaConfig, scenario: Scenario, builder: ScriptBuilder, run_dir: Path) -> list[str]:
    """Script lines for the steps; each step inside `MARK begin scn<i>` / `MARK end scn<i>`."""
    c = cfg.probe_identity.autocad.commands
    facts = cfg.hosts.hosts["autocad"].core_console
    cancel = [facts.cancel_line if facts else "(command)"] * cfg.thresholds.smoke.cancel_lines
    for index, step in enumerate(scenario.steps):
        label = f"scn{index}"
        body: list[str] = []
        if isinstance(step, RunStep):
            # "" answers a prompt with Enter: safe inside a prompt, never at Command: (F4).
            body = [step.run, *(_text(i, run_dir) for i in step.inputs), *cancel]
        elif isinstance(step, AssertStep):
            a = step.assert_
            if a.entity_count:
                e = a.entity_count
                body.append(c.assert_)
                body.append(f"entity_count {e.type} {e.op} {e.value} {e.layer or '*'}")
            for kind, value in (("layer_exists", a.layer_exists), ("block_exists", a.block_exists)):
                if value:
                    body += [c.assert_, f"{kind} {value}"]
            if a.sysvar:
                body += [c.assert_, f"sysvar {a.sysvar.name} {a.sysvar.value}"]
        elif isinstance(step, SaveAsStep):
            target = _lisp(str(run_dir / step.save_as))
            body = [f'(command "_.SAVEAS" "" "{target}")', *cancel]
        elif isinstance(step, ScriptStep):
            body = [_text(line, run_dir) for line in step.script]
        builder.raw(c.mark, f"begin {label}", *body, c.mark, f"end {label}")
    return builder.end(quit_lines(cfg))


def run_scenario(
    cfg: MtaConfig,
    year: int,
    runs_root: Path,
    probe: Path,
    payload: Path,
    components: list[Component],
    scenario: Scenario,
    source: Path,
    sample_roots: list[Path],
) -> ScenarioRun:
    result = ScenarioRun(scenario, source, year)
    if not scenario.applies_to(_HOST, year):
        result.skipped = (
            f"not for AutoCAD {year} headless ({scenario.host_versions}, ui_mode {scenario.ui_mode})"
        )
        return result
    if any(isinstance(s, OpenStep) for s in scenario.steps):
        result.skipped = (
            "a mid-scenario `open` is not supported in the single-document core console (Phase 2)"
        )
        return result
    drawing = None
    if scenario.setup.open:
        found = find_sample(scenario.setup.open, sample_roots)
        if found is None:
            result.skipped = f"sample not found: {scenario.setup.open}"  # scenario-dsl.md §4: SKIPPED
            return result
        drawing = found
    layout = prepare_run(cfg, runs_root, probe, payload, components)
    if drawing is not None:
        drawing = Path(shutil.copy2(drawing, layout.root / f"sample{drawing.suffix}"))
    builder = ScriptBuilder(cfg, layout, probe.name, components)
    for component in components:
        builder.load(component)
    lines = build_lines(cfg, scenario, builder, layout.root)
    layout.script.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    t = cfg.thresholds
    timeout = (
        t.coreconsole.startup_timeout_s
        + len(components) * t.load.per_component_timeout_s
        + scenario.timeout_s
    )
    result.session = _run(cfg, year, "scenario", layout, timeout, None, drawing)
    _evaluate(result)
    return result


def _evaluate(run: ScenarioRun) -> None:
    session = run.session
    if session is None or session.infra_error:
        return
    events = session.log.events
    labels = [f"scn{i}" for i in range(len(run.scenario.steps))]
    for index, step in enumerate(run.scenario.steps):
        label = labels[index]
        begin = next(
            (
                i
                for i, e in enumerate(events)
                if e.type == "mark" and e.data == {"phase": "begin", "label": label}
            ),
            None,
        )
        end = next(
            (
                i
                for i, e in enumerate(events)
                if e.type == "mark" and e.data == {"phase": "end", "label": label}
            ),
            None,
        )
        if begin is None or end is None:
            why = "not reached" if begin is None else "did not finish"
            console = session.console
            state = f" (exit {console.exit_hex}, timed out {console.timed_out})" if console else ""
            run.step_errors.append(f"step {index + 1} {why}{state}")
            break
        window = events[begin:end]
        errors = [e for e in window if e.type in ("exception.first_chance", "exception.unhandled")]
        if isinstance(step, RunStep):
            outcome = _run_outcome(step.run, window)
            if errors and outcome == "failed":
                run.step_errors.append(
                    f"step {index + 1} {step.run}: plugin exception: {errors[0].data.get('message')}"
                )
            elif step.expect_outcome:
                run.assertions += 1
                if outcome != step.expect_outcome:
                    run.failures.append(
                        f"step {index + 1} {step.run}: outcome {outcome}, expected {step.expect_outcome}"
                    )
        if isinstance(step, AssertStep):
            for e in (x for x in window if x.type == "assert.result"):
                run.assertions += 1
                if not e.data.get("ok"):
                    run.failures.append(
                        f"step {index + 1}: {e.data.get('assertion')} (actual {e.data.get('actual')})"
                    )
            _file_assertions(run, index, step, session.layout.root)


def _run_outcome(command: str, window: list[ProbeEvent]) -> str:
    own = {e.type for e in window if e.type.startswith("command.")
           and str(e.data.get("name", "")).lstrip("_").upper() == command.upper()}  # fmt: skip
    prompts = any(e.type == "prompt" for e in window)
    if "command.failed" in own:
        return "failed"
    if "command.cancelled" in own:
        return "awaiting_input" if prompts else "cancelled"
    return "completed"


def _file_assertions(run: ScenarioRun, index: int, step: AssertStep, run_dir: Path) -> None:
    a = step.assert_
    if not a.file_exists:
        return
    path = Path(_text(a.file_exists, run_dir))
    path = path if path.is_absolute() else run_dir / path
    run.assertions += 1
    if not path.is_file():
        run.failures.append(f"step {index + 1}: file_exists {a.file_exists}: missing")
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    if a.file_lines:
        run.assertions += 1
        lines = len(text.splitlines())
        if not _OPS[a.file_lines.op](lines, a.file_lines.value):
            run.failures.append(
                f"step {index + 1}: file_lines {lines} {a.file_lines.op} {a.file_lines.value} is false"
            )
    if a.file_contains:
        run.assertions += 1
        if a.file_contains not in text:
            run.failures.append(f"step {index + 1}: file does not contain {a.file_contains!r}")


def scenario_checks(cfg: MtaConfig, runs: list[ScenarioRun]) -> list[CheckResult]:
    sink = ResultSink(cfg, source=Source.DYNAMIC)
    for r in runs:
        subject = f"scenario:{r.scenario.scenario}"

        def add(check_id: str, status: Status, message: str, evidence: str | None = None) -> None:
            sink.add(check_id, status, message, evidence, subject=subject, host_id=_HOST, host_version=r.year)  # noqa: B023

        if r.skipped:
            add("WFL-001", Status.SKIPPED, r.skipped)
            add("WFL-002", Status.SKIPPED, r.skipped)
            continue
        session = r.session
        if session is None or session.infra_error:
            reason = session.infra_error if session else "not run"
            add("WFL-001", Status.ERROR, reason or "not run", session.excerpt() if session else None)
            add("WFL-002", Status.ERROR, reason or "not run")
            continue
        if r.step_errors:
            add(
                "WFL-001",
                Status.FAIL,
                f"{r.scenario.title}: steps did not all execute",
                excerpt([*r.step_errors, "console:", session.excerpt(10)]),
            )
            add("WFL-002", Status.SKIPPED, "steps did not all execute (see WFL-001)")
            continue
        add("WFL-001", Status.PASS, f"{r.scenario.title}: {len(r.scenario.steps)} step(s) executed")
        if r.failures:
            add(
                "WFL-002",
                Status.FAIL,
                f"{r.scenario.title}: {len(r.failures)} assertion(s) failed",
                excerpt(r.failures),
            )
        elif r.assertions:
            add("WFL-002", Status.PASS, f"{r.scenario.title}: {r.assertions} assertion(s) hold")
        else:
            add("WFL-002", Status.SKIPPED, "the scenario has no assertions")
    return sink.sorted()


def scenario_sources(kit_root: Path, app_id: str, kit_scenarios: list[str], repo_root: Path) -> list[Path]:
    """Kit scenarios (publisher input) and reviewer scenarios in the repo (`scenarios/<app_id>/`, reused for
    every update of the app: scenario-dsl.md §4)."""
    found = [kit_root / rel for rel in kit_scenarios if (kit_root / rel).suffix.lower() in (".yaml", ".yml")]
    reviewer = repo_root / "scenarios" / app_id
    if reviewer.is_dir():
        found += sorted(p for p in reviewer.iterdir() if p.suffix.lower() in (".yaml", ".yml"))
    return found
