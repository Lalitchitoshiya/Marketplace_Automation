"""Step 13: smoke outcome classification, CMD-001/002/004, RUN-001...003, smoke loop, corpus measure."""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mta.adapters.autocad import dynamic, session
from mta.adapters.autocad.console import ConsoleRun
from mta.adapters.autocad.events import ProbeEvent, ProbeLog
from mta.adapters.autocad.session import (
    Component,
    EventSilence,
    SessionResult,
    prepare_run,
    smoke_session,
)
from mta.config import MtaConfig
from mta.corpus import runner, sd
from mta.engine.smoke_rules import CommandOutcome, classify, cmd001, command_checks
from mta.models import CheckResult, Severity, Status

T0 = datetime(2026, 10, 20, tzinfo=UTC)


def _ev(seq: int, type_: str, **data: Any) -> ProbeEvent:
    return ProbeEvent(v=1, seq=seq, ts=T0 + timedelta(milliseconds=seq), run_id="r", type=type_, data=data)


def _session(
    cfg: MtaConfig,
    tmp_path: Path,
    events: list[ProbeEvent],
    *,
    code: int | None = 0,
    timed_out: bool = False,
    killed: list[str] | None = None,
    kind: str = "smoke",
) -> SessionResult:  # fmt: skip
    probe = tmp_path / "p.dll"
    probe.write_bytes(b"MZ")
    layout = prepare_run(cfg, tmp_path / "runs", probe, None, [])
    console = ConsoleRun(None if timed_out else code, timed_out, "console tail", 1.0, 1, killed or [])
    return SessionResult(kind, 2026, layout, console, ProbeLog(events))


def _window(
    name: str, start: int, *inner: tuple[str, dict[str, Any]], close: bool = True
) -> list[ProbeEvent]:
    events = [_ev(start, "mark", phase="begin", label=name)]
    events += [_ev(start + i + 1, t, **d) for i, (t, d) in enumerate(inner)]
    if close:
        events.append(_ev(start + len(inner) + 1, "mark", phase="end", label=name))
    return events


FC = (
    "exception.first_chance",
    {"type": "System.NullReferenceException", "message": "x", "stack": "A.B [Plug]"},
)


@pytest.mark.parametrize(
    ("inner", "outcome", "note"),
    [
        ([("command.start", {"name": "A"}), ("command.ended", {"name": "A"})], "completed", ""),
        ([("command.start", {"name": "A"}), ("prompt", {"kind": "string"}),
          ("command.cancelled", {"name": "A"})], "awaiting_input", "interactive; needs scenario coverage"),
        ([("command.start", {"name": "A"}), ("command.cancelled", {"name": "A"})], "cancelled", ""),
        ([("command.start", {"name": "A"}), FC, ("command.failed", {"name": "A"})], "exception",
         "plugin exception; the command failed"),
        ([("command.start", {"name": "A"}), FC, ("command.ended", {"name": "A"})], "completed",
         "exception handled by the plugin"),
        ([("command.unknown", {"name": "A"})], "not_defined", "unknown command at runtime"),
        ([], "completed", "no command events (transparent or session command)"),
        ([("command.start", {"name": "LINE"}), ("command.ended", {"name": "_LINE"})], "completed", ""),
    ],
)  # fmt: skip
def test_closed_windows(cfg: MtaConfig, tmp_path: Path, inner: list[Any], outcome: str, note: str) -> None:
    name = "LINE" if any(d.get("name") in ("LINE", "_LINE") for _, d in inner) else "A"
    decided, rest = classify(_session(cfg, tmp_path, _window(name, 1, *inner)), [name])
    assert (decided[0].outcome, decided[0].note, rest) == (outcome, note, [])


@pytest.mark.parametrize(
    ("inner", "console", "outcome"),
    [
        ([("command.start", {"name": "B"})], {"timed_out": True}, "timeout"),
        ([("command.start", {"name": "B"}), FC], {"code": 0xC0000005}, "exception"),
        ([("command.start", {"name": "B"}),
          ("exception.first_chance", {"type": "System.AccessViolationException"})],
         {"code": 0xC0000005}, "crash"),
        ([("command.start", {"name": "B"})], {"code": 0xC0000005}, "crash"),
        ([("command.start", {"name": "B"})], {"code": 0}, "aborted_script"),
    ],
)  # fmt: skip
def test_open_window_after_anomaly(
    cfg: MtaConfig, tmp_path: Path, inner: list[Any], console: dict[str, Any], outcome: str
) -> None:
    events = _window("A", 1, ("command.ended", {"name": "A"})) + _window("B", 10, *inner, close=False)
    decided, rest = classify(_session(cfg, tmp_path, events, **console), ["A", "B", "C", "D"])
    assert [d.outcome for d in decided] == ["completed", outcome]
    assert rest == ["C", "D"]  # continue in a fresh process (P1-R15)
    if outcome == "exception":
        assert "A.B [Plug]" in (decided[1].evidence or "")


def test_commands_not_reached(cfg: MtaConfig, tmp_path: Path) -> None:
    decided, rest = classify(_session(cfg, tmp_path, [_ev(1, "session.start")], code=1), ["A", "B"])
    assert decided == [] and rest == ["A", "B"]


def _statuses(results: list[CheckResult]) -> dict[tuple[str, str], Status]:
    return {(r.check_id, r.target.subject): r.status for r in results}


def test_command_checks(cfg: MtaConfig, tmp_path: Path) -> None:
    outcomes = [
        CommandOutcome("OK", "completed"),
        CommandOutcome("ASK", "awaiting_input", "interactive; needs scenario coverage"),
        CommandOutcome("BOOM", "exception", "", "NRE stack"),
        CommandOutcome("HANG", "timeout", "no prompt active", "tail"),
        CommandOutcome("CRASH", "crash", "host crashed (0xC0000005)", "tail"),
        CommandOutcome("GONE", "not_defined"),
        CommandOutcome("LATE", "not_run", "the session ended before the commands ran", "tail"),
    ]
    ended = _session(cfg, tmp_path, [_ev(1, "session.start"), _ev(2, "session.shutdown")])
    s = _statuses(command_checks(cfg, 2026, outcomes, [ended]))
    assert s[("CMD-002", "command:OK")] is Status.PASS and s[("CMD-002", "command:ASK")] is Status.PASS
    assert s[("CMD-002", "command:BOOM")] is Status.FAIL
    assert s[("CMD-002", "command:HANG")] is Status.SKIPPED and s[("CMD-004", "command:HANG")] is Status.FAIL
    assert (
        s[("CMD-002", "command:CRASH")] is Status.SKIPPED and s[("CMD-002", "command:LATE")] is Status.ERROR
    )
    assert ("CMD-004", "command:GONE") not in s
    assert s[("RUN-001", "package")] is Status.FAIL and s[("RUN-002", "package")] is Status.FAIL
    assert s[("RUN-003", "package")] is Status.PASS


def test_run_checks_clean_and_unclean_quit(cfg: MtaConfig, tmp_path: Path) -> None:
    clean = _statuses(command_checks(cfg, 2026, [CommandOutcome("OK", "completed")], []))
    assert clean[("RUN-001", "package")] is Status.PASS and clean[("RUN-002", "package")] is Status.PASS
    assert clean[("RUN-003", "package")] is Status.SKIPPED
    bad_quit = _session(cfg, tmp_path, [_ev(1, "session.start"), _ev(2, "session.shutdown")], timed_out=True)
    assert _statuses(command_checks(cfg, 2026, [], [bad_quit]))[("RUN-003", "package")] is Status.FAIL


def test_cmd001(cfg: MtaConfig, tmp_path: Path) -> None:
    load = _session(cfg, tmp_path, [
        _ev(1, "command.defined", name="A", defined=True),
        _ev(2, "command.defined", name="B", defined=False),
    ], kind="load")  # fmt: skip
    assert cmd001(cfg, 2026, load, ["A"], [])[0].status is Status.PASS
    missing = cmd001(cfg, 2026, load, ["A", "B"], [])[0]
    assert missing.status is Status.FAIL and missing.evidence[0].excerpt == "B"
    assert cmd001(cfg, 2026, load, ["B"], ["B"])[0].status is Status.SKIPPED  # component failed: LOD-001


# ---- watchdog and smoke session --------------------------------------------------------------------------


def test_event_silence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events = tmp_path / "e.log"
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    silence = EventSilence(events, command_s=20, load_s=60)
    assert not silence()  # no file yet: the startup budget applies
    events.write_text(json.dumps({"type": "mark", "data": {"phase": "begin", "label": "X"}}) + "\n", "utf-8")
    assert not silence()
    clock[0] += 21
    assert silence()  # command window open and silent for 21 s
    with events.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "component.load.begin", "data": {}}) + "\n")
    assert not silence()
    clock[0] += 30
    assert not silence()  # loads get 60 s
    clock[0] += 31
    assert silence()
    with events.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "component.load.end", "data": {}}) + "\n")
    assert not silence()
    clock[0] += 500
    assert not silence()  # nothing open: only the overall budget applies


def test_smoke_session_script(cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(
        c: MtaConfig, year: int, kind: str, layout: Any, timeout: float, stall: Any
    ) -> SessionResult:
        seen.update(script=layout.script.read_text("utf-8").splitlines(), timeout=timeout, stall=stall)
        return SessionResult(kind, year, layout, None, ProbeLog())

    monkeypatch.setattr(session, "_run", fake_run)
    probe = tmp_path / "p.dll"
    probe.write_bytes(b"MZ")
    payload = tmp_path / "payload"
    payload.mkdir()
    smoke_session(
        cfg, 2026, tmp_path / "runs", probe, payload, [Component("A", "a.dll", "netload")], ["X", "Y"]
    )
    m = cfg.probe_identity.autocad.commands.mark
    script = seen["script"]
    i = script.index("begin X")
    assert script[i - 1 : i + 6] == [m, "begin X", "X", "(command)", "(command)", m, "end X"]
    assert isinstance(seen["stall"], EventSilence)
    assert seen["timeout"] > 2 * cfg.thresholds.smoke.per_command_timeout_s


def test_smoke_loop_continues_after_anomaly(
    cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs: list[list[str]] = []

    def fake_smoke(c: MtaConfig, year: int, root: Path, probe: Path, payload: Path, comps: Any,
                   commands: list[str]) -> SessionResult:  # fmt: skip
        runs.append(list(commands))
        sub = tmp_path / f"s{len(runs)}"
        sub.mkdir()
        if commands[0] == "A":  # A completes, B crashes the host
            events = _window("A", 1, ("command.ended", {"name": "A"})) + _window(
                "B", 10, ("command.start", {"name": "B"}), close=False)  # fmt: skip
            return _session(cfg, sub, events, code=0xC0000005)
        return _session(cfg, sub, _window("C", 1, ("command.ended", {"name": "C"})))

    monkeypatch.setattr(dynamic, "smoke_session", fake_smoke)
    outcome = dynamic.DynamicOutcome()
    decided = dynamic._smoke(cfg, 2026, tmp_path, tmp_path, tmp_path, [], ["A", "B", "C"], outcome)
    assert runs == [["A", "B", "C"], ["C"]]
    assert [(d.name, d.outcome) for d in decided] == [("A", "completed"), ("B", "crash"), ("C", "completed")]
    assert len(outcome.sessions) == 2


def test_smoke_loop_without_progress_stops(
    cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dynamic, "smoke_session", lambda *a: _session(cfg, tmp_path, [], code=1))
    decided = dynamic._smoke(
        cfg, 2026, tmp_path, tmp_path, tmp_path, [], ["A", "B"], dynamic.DynamicOutcome()
    )
    assert [d.outcome for d in decided] == ["not_run", "not_run"]


# ---- corpus measure --------------------------------------------------------------------------------------


def test_corpus_measure_is_relative_to_sd01(
    cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = {"SD-01": {"SIG-002"}, "SD-03": {"SIG-002", "CMD-002", "RUN-002"}, "SD-10": {"SIG-001"}}

    def fake(case: sd.SdCase, c: MtaConfig, data: Path) -> runner.KitOutcome:
        if case.id == "SD-04":
            raise RuntimeError("build missing")
        return runner.KitOutcome(raw.get(case.id, {"SIG-002"}), None, "job", 60.0, 1)

    monkeypatch.setattr(runner, "run_case", fake)
    results = {
        r.case.id: r for r in runner.run_corpus(cfg, tmp_path, only=["SD-03", "SD-04", "SD-10", "SD-11"])
    }
    assert set(results) == {"SD-01", "SD-03", "SD-04", "SD-10", "SD-11"}
    assert results["SD-03"].ok and results["SD-03"].triggered == {"CMD-002", "RUN-002"}
    assert results["SD-10"].ok  # SIG-001 new; SD-01's untrusted SIG-002 is the baseline
    assert not results["SD-04"].ok and "build missing" in (results["SD-04"].error or "")
    assert (results["SD-11"].error or "").startswith("skipped")  # EICAR only with --with-eicar
    assert results["SD-01"].raw == {"SIG-002"}


def test_not_green() -> None:
    from mta.models import Source
    from mta.models.results import CheckTarget, Evidence

    def r(check_id: str, status: Status) -> CheckResult:
        evidence = [Evidence(kind="excerpt", excerpt="x")] if status in (Status.FAIL, Status.WARN) else []
        return CheckResult(
            check_id=check_id,
            target=CheckTarget(subject="package"),
            status=status,
            severity=Severity.MAJOR,
            source=Source.STATIC,
            message="m",
            evidence=evidence,
        )

    assert sd.not_green([r("AA-001", Status.PASS), r("BB-001", Status.FAIL), r("CC-001", Status.WARN),
                         r("DD-001", Status.SKIPPED)]) == {"BB-001", "CC-001"}  # fmt: skip


def test_sign_untrusted_no_files_is_a_noop() -> None:
    sd.sign_untrusted([])
