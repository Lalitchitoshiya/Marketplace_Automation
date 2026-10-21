"""LOD-001...003 from one load session's probe events (requirements.md P1-R13, P1-R18)."""

from datetime import datetime

from mta.adapters.autocad.events import ProbeEvent
from mta.adapters.autocad.session import Component, SessionResult
from mta.config import MtaConfig
from mta.models import CheckResult, Source, Status
from mta.static.results import ResultSink, excerpt

GUI_NOTE = "requires GUI host — covered in Phase 2"
_HOST = "autocad"


def _first_chance(events: list[ProbeEvent], after: int, before: int) -> list[str]:
    return [
        f"{e.data.get('type')}: {e.data.get('message')}\n{e.data.get('stack', '')}"
        for e in events
        if e.type == "exception.first_chance" and after < e.seq < before
    ]


def _lisp_window(events: list[ProbeEvent], name: str) -> tuple[ProbeEvent | None, ProbeEvent | None]:
    label = f"load:{name}"
    begin = next(
        (e for e in events if e.type == "mark" and e.data == {"phase": "begin", "label": label}), None
    )
    end = next((e for e in events if e.type == "mark" and e.data == {"phase": "end", "label": label}), None)
    return begin, end


def _ms(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() * 1000)


def load_checks(cfg: MtaConfig, components: list[Component], session: SessionResult) -> list[CheckResult]:
    sink = ResultSink(cfg, source=Source.DYNAMIC)
    year = session.year

    def add(
        check_id: str, status: Status, message: str, evidence: str | None = None, subject: str = "package"
    ) -> None:
        sink.add(check_id, status, message, evidence, subject=subject, host_id=_HOST, host_version=year)

    if session.infra_error:
        for c in components:
            add("LOD-001", Status.ERROR, session.infra_error, session.excerpt(), f"component:{c.name}")
            add("LOD-002", Status.ERROR, session.infra_error, None, f"component:{c.name}")
        add("LOD-003", Status.ERROR, session.infra_error, session.excerpt())
        return sink.sorted()

    events = session.log.events
    warn_ms = cfg.thresholds.load.per_component_warn_s * 1000
    finished = True
    for c in components:
        subject = f"component:{c.name}"
        if c.loader == "none":
            add(
                "LOD-001",
                Status.SKIPPED,
                f"{c.path}: not loaded headless (menu/customization file)",
                subject=subject,
            )
            add("LOD-002", Status.SKIPPED, "not loaded headless", subject=subject)
            continue
        status, message, evidence, duration = _component(events, c)
        if status in (Status.FAIL, Status.ERROR) and not evidence:  # Constitution §2: evidence always
            evidence = session.excerpt() or message
        if status is Status.FAIL and c.gui_required:
            status, message = Status.NEEDS_REVIEW, f"{message}: {GUI_NOTE}"
        if duration is None:
            finished = False
        add("LOD-001", status, message, evidence if status is not Status.PASS else None, subject)
        if duration is None:
            add("LOD-002", Status.SKIPPED, "no load time: the load did not finish", subject=subject)
        elif duration > warn_ms:
            add(
                "LOD-002",
                Status.FAIL,
                f"Load took {duration} ms (limit {warn_ms} ms)",
                f"{c.path}: {duration} ms",
                subject,
            )
        else:
            add("LOD-002", Status.PASS, f"Loaded in {duration} ms", subject=subject)

    console = session.console
    ready = bool(session.log.of_type("host.ready"))
    if ready and finished and console is not None and not console.timed_out:
        add("LOD-003", Status.PASS, "Host started and finished loading the plugin")
    else:
        why = (
            "timed out"
            if console and console.timed_out
            else f"exit {console.exit_hex}"
            if console
            else "not run"
        )
        add(
            "LOD-003", Status.FAIL, f"Host did not finish starting with the plugin ({why})", session.excerpt()
        )
    return sink.sorted()


def _component(events: list[ProbeEvent], c: Component) -> tuple[Status, str, str | None, int | None]:
    """(status, message, evidence, duration_ms) for one component."""
    if c.loader == "lisp":
        begin, end = _lisp_window(events, c.name)
        note = next(
            (
                e
                for e in events
                if e.type == "note"
                and e.data.get("kind") == "lisp-load"
                and e.data.get("name") == c.name
                and e.data.get("value") == "ok"
            ),
            None,
        )
        duration = _ms(begin.ts, end.ts) if begin and end else None
        if note is None:
            return (
                Status.FAIL,
                f"LISP file {c.path} did not load",
                "the (load) expression did not complete",
                duration,
            )
        return Status.PASS, f"{c.path} loaded", None, duration

    begin = next(
        (e for e in events if e.type == "component.load.begin" and e.data.get("component") == c.name), None
    )
    end = next(
        (e for e in events if e.type == "component.load.end" and e.data.get("component") == c.name), None
    )
    if end is None:
        return Status.FAIL, f"Load of {c.path} did not finish (crash or hang)", None, None
    duration = int(end.data.get("duration_ms") or 0)
    if not end.data.get("ok"):
        return Status.FAIL, f"{c.path} failed to load", str(end.data.get("error")), duration
    loaded = end.data.get("loaded")  # the probe checks the process directly (step 12)
    if loaded is None:  # older probe: fall back to the load event
        module = str(end.data.get("module_path") or "").lower()
        loaded = any(
            e.type == "assembly.load" and str(e.data.get("path") or "").lower() == module
            for e in events
            if (begin.seq if begin else 0) < e.seq < end.seq
        )
    if c.loader == "netload" and not loaded:
        # The loader returned, but nothing loaded: a trust/SECURELOAD problem of the run, not of the plugin.
        return (
            Status.ERROR,
            f"{c.path}: loader returned but the assembly was not loaded (check TRUSTEDPATHS)",
            None,
            duration,
        )
    if int(end.data.get("plugin_exceptions") or 0) > 0:
        found = _first_chance(events, begin.seq if begin else 0, end.seq) or [
            f"{end.data.get('plugin_exceptions')} plugin exception(s) during the load (details not captured)"
        ]
        return (
            Status.FAIL,
            f"{c.path} threw during load (e.g. in IExtensionApplication.Initialize)",
            excerpt(found),
            duration,
        )
    return Status.PASS, f"{c.path} loaded", None, duration
