"""Smoke outcomes and CMD-001/002/004, RUN-001...003 (requirements.md P1-R14...P1-R16, outcome table)."""

from dataclasses import dataclass
from typing import Literal

from mta.adapters.autocad.events import ProbeEvent
from mta.adapters.autocad.session import SessionResult
from mta.config import MtaConfig
from mta.models import CheckResult, Source, Status
from mta.static.results import ResultSink, excerpt

Outcome = Literal[
    "completed", "awaiting_input", "cancelled", "exception", "crash", "timeout", "aborted_script",
    "not_defined", "not_run",
]  # fmt: skip
_HOST = "autocad"
_NATIVE_CRASH_TYPES = ("System.AccessViolationException",)


@dataclass(frozen=True)
class CommandOutcome:
    name: str
    outcome: Outcome
    note: str = ""
    evidence: str | None = None
    run_id: str = ""


def _same(a: object, b: str) -> bool:
    return str(a or "").lstrip("_").upper() == b.lstrip("_").upper()


def _window(events: list[ProbeEvent], name: str) -> tuple[int | None, int | None]:
    begin = end = None
    for i, e in enumerate(events):
        if e.type == "mark" and e.data.get("label") == name:
            if e.data.get("phase") == "begin" and begin is None:
                begin = i
            elif e.data.get("phase") == "end" and begin is not None:
                end = i
                break
    return begin, end


def _exceptions(window: list[ProbeEvent]) -> list[ProbeEvent]:
    return [e for e in window if e.type in ("exception.first_chance", "exception.unhandled")]


def _stack(found: list[ProbeEvent]) -> str:
    return excerpt(f"{e.data.get('type')}: {e.data.get('message')}\n{e.data.get('stack', '')}" for e in found)


def _closed(name: str, window: list[ProbeEvent], run_id: str) -> CommandOutcome:
    own = [e for e in window if e.type.startswith("command.") and _same(e.data.get("name"), name)]
    states = {e.type for e in own}
    errors = _exceptions(window)
    prompts = [e for e in window if e.type == "prompt"]
    if "command.unknown" in states:
        return CommandOutcome(name, "not_defined", "unknown command at runtime", run_id=run_id)
    if errors and "command.failed" in states:
        return CommandOutcome(
            name, "exception", "plugin exception; the command failed", _stack(errors), run_id
        )
    if "command.ended" in states:
        note = "exception handled by the plugin" if errors else ""
        return CommandOutcome(name, "completed", note, run_id=run_id)
    if "command.cancelled" in states and prompts:
        return CommandOutcome(name, "awaiting_input", "interactive; needs scenario coverage", run_id=run_id)
    if states & {"command.cancelled", "command.failed"}:
        return CommandOutcome(name, "cancelled", run_id=run_id)
    return CommandOutcome(
        name, "completed", "no command events (transparent or session command)", run_id=run_id
    )


def classify(session: SessionResult, commands: list[str]) -> tuple[list[CommandOutcome], list[str]]:
    """Outcomes of the commands this session decided, and the commands still to run in a fresh process."""
    events = session.log.events
    run_id = session.layout.run_id
    decided: list[CommandOutcome] = []
    for index, name in enumerate(commands):
        begin, end = _window(events, name)
        if begin is None:  # never reached: the session ended earlier (a load hung or crashed)
            return decided, commands[index:]
        if end is not None:
            decided.append(_closed(name, events[begin:end], run_id))
            continue
        window = events[begin:]
        console = session.console
        errors = _exceptions(window)
        if console is not None and console.timed_out:
            prompts = [e for e in window if e.type == "prompt"]
            note = "waiting at a prompt that could not be cancelled" if prompts else "no prompt active"
            decided.append(CommandOutcome(name, "timeout", note, session.excerpt(), run_id))
        elif console is not None and console.crashed:
            native = [e for e in errors if e.data.get("type") in _NATIVE_CRASH_TYPES]
            if errors and not native:
                decided.append(CommandOutcome(name, "exception", f"host crashed ({console.exit_hex})",
                                              _stack(errors), run_id))  # fmt: skip
            else:
                evidence = _stack(errors) if errors else session.excerpt()
                decided.append(
                    CommandOutcome(name, "crash", f"host crashed ({console.exit_hex})", evidence, run_id)
                )
        else:  # exit 0 with the mark still open: cancelling ended the script (F22)
            decided.append(CommandOutcome(name, "aborted_script",
                                          "cancelling this command ends the script: it runs native commands",
                                          run_id=run_id))  # fmt: skip
        return decided, commands[index + 1 :]
    return decided, []


def command_checks(
    cfg: MtaConfig, year: int, outcomes: list[CommandOutcome], sessions: list[SessionResult]
) -> list[CheckResult]:
    sink = ResultSink(cfg, source=Source.DYNAMIC)

    def add(check_id: str, status: Status, message: str, evidence: str | None = None, subject: str = "package"
            ) -> None:  # fmt: skip
        sink.add(check_id, status, message, evidence, subject=subject, host_id=_HOST, host_version=year)

    for o in outcomes:
        subject = f"command:{o.name}"
        note = f" ({o.note})" if o.note else ""
        match o.outcome:
            case "exception":
                add(
                    "CMD-002", Status.FAIL, f"{o.name}: unhandled plugin exception{note}", o.evidence, subject
                )
            case "completed" | "awaiting_input" | "cancelled" | "aborted_script":
                add("CMD-002", Status.PASS, f"{o.name}: {o.outcome.replace('_', ' ')}{note}", subject=subject)
            case "timeout":
                add("CMD-002", Status.SKIPPED, f"{o.name}: timed out (see CMD-004)", subject=subject)
            case "crash":
                add("CMD-002", Status.SKIPPED, f"{o.name}: host crashed (see RUN-001)", subject=subject)
            case "not_defined":
                add(
                    "CMD-002",
                    Status.SKIPPED,
                    f"{o.name}: not defined at runtime (see CMD-001)",
                    subject=subject,
                )
            case "not_run":
                add("CMD-002", Status.ERROR, f"{o.name}: could not be run{note}", o.evidence, subject)
        if o.outcome == "timeout":
            message = f"{o.name}: still running after the timeout{note}"
            add("CMD-004", Status.FAIL, message, o.evidence or o.note, subject)
        elif o.outcome not in ("not_defined", "not_run"):
            add("CMD-004", Status.PASS, f"{o.name}: did not hang", subject=subject)

    crashes = [o for o in outcomes if o.outcome == "crash"]
    dumps = [str(d) for s in sessions if s.console for d in s.console.dumps]
    if crashes or dumps:
        lines = [f"{o.name}: {o.note}" for o in crashes] + [f"dump: {d}" for d in dumps]
        add("RUN-001", Status.FAIL, "AutoCAD crashed", excerpt(lines + [o.evidence or "" for o in crashes]))
    else:
        add("RUN-001", Status.PASS, "No host crash")

    errors = [o for o in outcomes if o.outcome == "exception"]
    unhandled = [e for s in sessions for e in s.log.of_type("exception.unhandled")]
    if errors or unhandled:
        lines = [f"{o.name}: {o.evidence}" for o in errors] + [str(e.data.get("message")) for e in unhandled]
        add(
            "RUN-002",
            Status.FAIL,
            f"Unhandled plugin exception(s) in {len(errors)} command(s)",
            excerpt(lines),
        )
    else:
        add("RUN-002", Status.PASS, "No unhandled plugin exceptions")

    ended = [s for s in sessions if s.log.shut_down and s.console is not None]
    if not ended:
        add("RUN-003", Status.SKIPPED, "no session reached the end of its script")
    else:
        bad = [s for s in ended if s.console and (s.console.timed_out or s.console.exit_code != 0)]
        if bad:
            lines = [f"{s.layout.run_id}: exit {s.console.exit_hex if s.console else '-'}" for s in bad]
            add("RUN-003", Status.FAIL, "AutoCAD did not quit cleanly with the plugin loaded", excerpt(lines))
        else:
            add("RUN-003", Status.PASS, "AutoCAD quit cleanly")
    return sink.sorted()


def cmd001(
    cfg: MtaConfig, year: int, load: SessionResult, expected: list[str], skipped: list[str]
) -> list[CheckResult]:
    """Declared commands defined at runtime (getcname). `skipped`: commands of components failing LOD-001."""
    sink = ResultSink(cfg, source=Source.DYNAMIC)
    defined = {
        str(e.data.get("name")).upper(): bool(e.data.get("defined"))
        for e in load.log.of_type("command.defined")
    }
    check = [c for c in expected if c not in skipped]
    missing = [c for c in check if not defined.get(c.upper(), False)]
    if not check:
        sink.add("CMD-001", Status.SKIPPED, "no commands to check (components did not load)", host_id=_HOST,
                 host_version=year)  # fmt: skip
    elif missing:
        sink.add("CMD-001", Status.FAIL, f"{len(missing)} declared command(s) not defined at runtime",
                 excerpt(missing), host_id=_HOST, host_version=year)  # fmt: skip
    else:
        sink.add("CMD-001", Status.PASS, f"All {len(check)} declared command(s) defined at runtime",
                 host_id=_HOST, host_version=year)  # fmt: skip
    return sink.sorted()
