"""Step 11 live checks in the real AcCoreConsole (marker `autocad`: run with `pytest -m autocad`).

Only MTA's own plugins run here (SD-01, the spike plugin), never third-party code.
"""

import json
import shutil
from pathlib import Path

import pytest

from mta.adapters.autocad.console import (
    ConsoleError,
    ConsoleRun,
    core_console,
    run_core_console,
    write_script,
)
from mta.adapters.autocad.events import ProbeLog, read_events
from mta.adapters.autocad.probe import build_probe
from mta.config import REPO_ROOT, MtaConfig
from mta.corpus.synthetic import built_dll

pytestmark = pytest.mark.autocad

RUNS = REPO_ROOT / ".mta" / "live"  # short root: /isolate fails past MAX_PATH (ADR-0003 F28)
SPIKE = REPO_ROOT / "spikes/p1-t03-accoreconsole/out/SpikePlugin/SpikePlugin.dll"


@pytest.fixture(scope="module")
def probe(cfg: MtaConfig) -> Path:
    try:
        core_console(cfg, 2026)
    except ConsoleError as exc:
        pytest.skip(str(exc))
    return build_probe(cfg)


def _session(
    cfg: MtaConfig, probe: Path, name: str, plugin: Path | None, body: list[str]
) -> tuple[ConsoleRun, ProbeLog]:
    identity = cfg.probe_identity.autocad
    run = RUNS / name
    shutil.rmtree(run, ignore_errors=True)
    (run / "probe").mkdir(parents=True)
    (run / "plugin").mkdir()
    shutil.copy2(probe, run / "probe")
    components = []
    if plugin is not None:
        shutil.copy2(plugin, run / "plugin")
        components = [{"name": plugin.stem, "module": str(run / "plugin" / plugin.name), "loader": "netload"}]
    plan = {"v": 1, "run_id": f"r-{name}", "plugin_dir": str(run / "plugin"), "components": components}
    (run / identity.plan_file).write_text(json.dumps(plan), encoding="utf-8")
    trusted = f"{(run / 'probe').as_posix()};{(run / 'plugin').as_posix()}"
    load = [identity.commands.load, plugin.stem] if plugin else []
    script = write_script(
        run / "s.scr",
        [
            "FILEDIA 0",
            f'(setvar "TRUSTEDPATHS" "{trusted}")',
            "NETLOAD",
            str(run / "probe" / probe.name),
            *load,
            *body,
        ],
    )
    result = run_core_console(cfg, 2026, run, script, env={identity.run_dir_env: str(run)}, timeout_s=180)
    return result, read_events(run / identity.events_file)


def test_probe_alone_is_clean(cfg: MtaConfig, probe: Path) -> None:
    """Step 11 'done when': session.start ... session.shutdown, nothing lost."""
    result, log = _session(cfg, probe, "alone", None, [cfg.probe_identity.autocad.commands.end, "QUIT", "Y"])
    assert (result.exit_code, result.timed_out) == (0, False), result.output[-2000:]
    assert log.clean, log.problems
    assert [e.type for e in log.events][:1] == ["session.start"]
    assert log.of_type("host.ready")[0].data["has_document"] is True


def test_probe_features_with_sd01(cfg: MtaConfig, probe: Path) -> None:
    sd01 = built_dll("Sd01Clean", cfg, 2026)
    if not sd01.is_file():
        pytest.skip("SD-01 not built (uv run mta corpus build)")
    identity = cfg.probe_identity.autocad
    c, note = identity.commands, identity.lisp_function
    body = [
        c.enumerate,
        f'({note} "defined" "SD01_HELLO" (getcname "SD01_HELLO"))',
        f'({note} "defined" "SD01_NOPE" (getcname "SD01_NOPE"))',
        c.mark,
        "begin SD01_ASK",
        "SD01_ASK",
        "(command)",
        "(command)",
        c.mark,
        "end SD01_ASK",
        c.mark,
        "begin SD01_ADDLINE",
        "SD01_ADDLINE",
        "(command)",
        c.mark,
        "end SD01_ADDLINE",
        c.assert_,
        "count == 1",
        c.end,
        "QUIT",
        "Y",
    ]
    result, log = _session(cfg, probe, "sd01", sd01, body)
    assert result.exit_code == 0 and log.clean, (log.problems, result.output[-2000:])
    load = log.of_type("component.load.end")[0].data
    assert load["ok"] is True and load["plugin_exceptions"] == 0
    assert sorted(e.data["name"] for e in log.of_type("command.registered")) == [
        "SD01_ADDLINE",
        "SD01_ASK",
        "SD01_HELLO",
    ]
    assert {e.data["name"]: e.data["defined"] for e in log.of_type("command.defined")} == {
        "SD01_HELLO": True,
        "SD01_NOPE": False,
    }
    ask = [e for e in log.events if e.data.get("mark") == "SD01_ASK"]
    assert [e.type for e in ask] == ["command.start", "prompt", "command.cancelled"]  # awaiting_input
    assert log.of_type("assert.result")[0].data == {
        "assertion": "count == 1",
        "actual": "1",
        "ok": True,
        "mark": None,
    }


def test_exception_in_command_is_recorded_before_the_crash(cfg: MtaConfig, probe: Path) -> None:
    """ADR-0003 F8: the core console dies with 0xC0000005; the first-chance event is the evidence."""
    if not SPIKE.is_file():
        pytest.skip("spike plugin not built (spikes/*/out is local only)")
    c = cfg.probe_identity.autocad.commands
    result, log = _session(
        cfg, probe, "crash", SPIKE, [c.mark, "begin SPK_THROW", "SPK_THROW", c.end, "QUIT", "Y"]
    )
    # Exits 0xC0000005 itself, or the runner ends it after the crash reporter (ADR-0003 F30).
    assert result.crashed and (result.exit_hex == "0xC0000005" or result.terminated_after_crash)
    assert not log.shut_down and not log.clean
    exception = log.of_type("exception.first_chance")[0].data
    assert (exception["type"], exception["source_assembly"], exception["mark"]) == (
        "System.InvalidOperationException",
        "SpikePlugin",
        "SPK_THROW",
    )
    assert exception["stack"].startswith("Spike.SpikeCommands.Throw")
