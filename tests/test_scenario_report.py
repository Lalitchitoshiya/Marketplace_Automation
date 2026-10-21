"""Step 14: scenario DSL, AutoCAD translation and WFL rules, authoring aids, report.html, exit codes."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from mta.adapters.autocad.console import ConsoleRun
from mta.adapters.autocad.events import ProbeEvent, ProbeLog
from mta.adapters.autocad.session import ScriptBuilder, SessionResult, prepare_run
from mta.cli.app import app
from mta.config import MtaConfig
from mta.intake.pipeline import intake_kit
from mta.models import Feature, Recommendation, Status
from mta.report.builder import write_job_report
from mta.report.html import render_html, screenshot_uris
from mta.scenario import autocad as scenario_autocad
from mta.scenario.autocad import (
    ScenarioRun,
    _evaluate,
    build_lines,
    find_sample,
    scenario_checks,
    scenario_sources,
)
from mta.scenario.generate import from_feature, skeleton, write_from_features
from mta.scenario.model import Scenario, ScenarioError, load_scenario
from mta.static.stage import run_static_stage
from tests.conftest import OFFLINE_SERVICES, KitFactory, clean_scanner

T0 = datetime(2026, 10, 20, tzinfo=UTC)

BASIC = """
scenario: acme/basic
title: Basic
host_versions: ">=2026"
ui_mode: headless
setup: {open: samples/site-plan.dwg}
steps:
  - run: ACME_DIMALL
    inputs: ["ALL", ""]
    expect_outcome: completed
  - assert:
      entity_count: {type: AcDbLine, layer: WALLS, op: ">=", value: 2}
      layer_exists: "ACME DIMS"
      block_exists: TITLE
      sysvar: {name: LUNITS, value: 2}
  - save_as: out.dwg
  - assert: {file_exists: "${RUN_DIR}/out.csv", file_lines: {op: "==", value: 2}, file_contains: "id"}
  - script: ["(princ \\"${RUN_DIR}\\")"]
"""


def _scenario(text: str = BASIC) -> Scenario:
    return Scenario.model_validate(yaml.safe_load(text))


# ---- DSL -------------------------------------------------------------------------------------------------


def test_scenario_parses_and_targets_versions() -> None:
    s = _scenario()
    assert len(s.steps) == 5
    assert s.applies_to("autocad", 2026) and not s.applies_to("autocad", 2025)
    assert not s.applies_to("revit", 2026)
    assert not _scenario(BASIC.replace("ui_mode: headless", "ui_mode: gui")).applies_to("autocad", 2026)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (('host_versions: ">=2026"', "host_versions: soon"), "host_versions"),
        (("- save_as: out.dwg", "- click: {tab: X}"), "steps"),
        (("    expect_outcome: completed", "    expect_outcome: maybe"), "expect_outcome"),
        (('file_lines: {op: "==", value: 2}, ', 'file_lines: {op: "~", value: 2}, '), "op"),
    ],
)
def test_invalid_scenarios_are_reported(tmp_path: Path, change: tuple[str, str], message: str) -> None:
    path = tmp_path / "s.yaml"
    assert change[0] in BASIC
    path.write_text(BASIC.replace(*change), encoding="utf-8")
    with pytest.raises(ScenarioError, match=message):
        load_scenario(path)


def test_assertions_need_content_and_a_file(tmp_path: Path) -> None:
    for bad in ("  - assert: {}", "  - assert: {file_lines: {op: '==', value: 1}}"):
        path = tmp_path / "s.yaml"
        path.write_text("scenario: a/b\ntitle: t\nsteps:\n" + bad + "\n", encoding="utf-8")
        with pytest.raises(ScenarioError):
            load_scenario(path)
    with pytest.raises(ScenarioError, match="cannot read"):
        load_scenario(tmp_path / "missing.yaml")


# ---- translation and evaluation --------------------------------------------------------------------------


def _layout(cfg: MtaConfig, tmp_path: Path) -> Any:
    tmp_path.mkdir(parents=True, exist_ok=True)
    probe = tmp_path / "p.dll"
    probe.write_bytes(b"MZ")
    return prepare_run(cfg, tmp_path / "runs", probe, None, [])


def test_build_lines(cfg: MtaConfig, tmp_path: Path) -> None:
    layout = _layout(cfg, tmp_path)
    c = cfg.probe_identity.autocad.commands
    lines = build_lines(cfg, _scenario(), ScriptBuilder(cfg, layout, "p.dll"), layout.root)
    i = lines.index("begin scn0")
    assert lines[i + 1 : i + 6] == [
        "ACME_DIMALL",
        "ALL",
        "",
        "(command)",
        "(command)",
    ]  # "" = Enter in a prompt
    assert f"{c.assert_}" in lines and "entity_count AcDbLine >= 2 WALLS" in lines
    assert "layer_exists ACME DIMS" in lines and "block_exists TITLE" in lines and "sysvar LUNITS 2" in lines
    save = next(line for line in lines if "_.SAVEAS" in line)
    assert (layout.root / "out.dwg").as_posix() in save
    assert f'(princ "{layout.root.as_posix()}")' in lines  # ${RUN_DIR} expanded
    assert lines[-3:] == [c.end, "QUIT", "Y"]


def _ev(seq: int, type_: str, **data: Any) -> ProbeEvent:
    return ProbeEvent(v=1, seq=seq, ts=T0 + timedelta(milliseconds=seq), run_id="r", type=type_, data=data)


def _mark(seq: int, phase: str, i: int) -> ProbeEvent:
    return _ev(seq, "mark", phase=phase, label=f"scn{i}")


def _run_with(
    cfg: MtaConfig, tmp_path: Path, events: list[ProbeEvent], scenario: Scenario, **console: Any
) -> ScenarioRun:
    layout = _layout(cfg, tmp_path)
    (layout.root / "out.csv").write_text("id\n1\n", encoding="utf-8")
    con = ConsoleRun(console.get("code", 0), console.get("timed_out", False), "tail", 1.0)
    run = ScenarioRun(
        scenario, Path("s.yaml"), 2026, SessionResult("scenario", 2026, layout, con, ProbeLog(events))
    )
    _evaluate(run)
    return run


def test_evaluate_passing_scenario(cfg: MtaConfig, tmp_path: Path) -> None:
    events = [
        _mark(1, "begin", 0),
        _ev(2, "command.start", name="ACME_DIMALL"),
        _ev(3, "command.ended", name="ACME_DIMALL"),
        _mark(4, "end", 0),
        _mark(5, "begin", 1),
        *[_ev(6 + i, "assert.result", assertion=a, ok=True, actual="x") for i, a in enumerate("abcd")],
        _mark(10, "end", 1),
        _mark(11, "begin", 2),
        _mark(12, "end", 2),
        _mark(13, "begin", 3),
        _mark(14, "end", 3),
        _mark(15, "begin", 4),
        _mark(16, "end", 4),
    ]
    run = _run_with(cfg, tmp_path, events, _scenario())
    assert run.step_errors == [] and run.failures == []
    assert run.assertions == 1 + 4 + 3  # expect_outcome + 4 in-drawing + 3 file assertions
    checks = {r.check_id: r.status for r in scenario_checks(cfg, [run])}
    assert checks == {"WFL-001": Status.PASS, "WFL-002": Status.PASS}


def test_evaluate_failures(cfg: MtaConfig, tmp_path: Path) -> None:
    events = [
        _mark(1, "begin", 0),
        _ev(2, "command.start", name="ACME_DIMALL"),
        _ev(3, "prompt", kind="string"),
        _ev(4, "command.cancelled", name="ACME_DIMALL"),
        _mark(5, "end", 0),
        _mark(6, "begin", 1),
        _ev(7, "assert.result", assertion="layer_exists ACME DIMS", ok=False, actual="False"),
        _mark(8, "end", 1),
        _mark(9, "begin", 2),
        _mark(10, "end", 2),
        _mark(11, "begin", 3),
        _mark(12, "end", 3),
        _mark(13, "begin", 4),
        _mark(14, "end", 4),
    ]
    scenario = _scenario(BASIC.replace('file_contains: "id"', 'file_contains: "nope"'))
    run = _run_with(cfg, tmp_path, events, scenario)
    text = "\n".join(run.failures)
    assert "outcome awaiting_input, expected completed" in text
    assert "layer_exists ACME DIMS (actual False)" in text and "does not contain 'nope'" in text
    statuses = {r.check_id: r for r in scenario_checks(cfg, [run])}
    assert statuses["WFL-001"].status is Status.PASS and statuses["WFL-002"].status is Status.FAIL


def test_evaluate_crash_stops_the_scenario(cfg: MtaConfig, tmp_path: Path) -> None:
    events = [
        _mark(1, "begin", 0),
        _ev(2, "command.start", name="ACME_DIMALL"),
        _ev(3, "exception.first_chance", type="X", message="boom"),
    ]
    run = _run_with(cfg, tmp_path, events, _scenario(), code=0xC0000005)
    assert run.step_errors and "did not finish" in run.step_errors[0]
    statuses = {r.check_id: r.status for r in scenario_checks(cfg, [run])}
    assert statuses == {"WFL-001": Status.FAIL, "WFL-002": Status.SKIPPED}


def test_skips_and_errors(cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = tmp_path / "p.dll"
    probe.write_bytes(b"MZ")
    missing = scenario_autocad.run_scenario(
        cfg, 2026, tmp_path / "runs", probe, tmp_path, [], _scenario(), Path("s.yaml"), [tmp_path]
    )
    assert missing.skipped == "sample not found: samples/site-plan.dwg"  # scenario-dsl.md §4: SKIPPED
    old = scenario_autocad.run_scenario(
        cfg, 2025, tmp_path / "runs", probe, tmp_path, [], _scenario(), Path("s.yaml"), [tmp_path]
    )
    assert "not for AutoCAD 2025" in (old.skipped or "")
    open_step = _scenario(BASIC.replace("- save_as: out.dwg", "- open: other.dwg"))
    unsupported = scenario_autocad.run_scenario(
        cfg, 2026, tmp_path / "runs", probe, tmp_path, [], open_step, Path("s.yaml"), [tmp_path]
    )
    assert "single-document" in (unsupported.skipped or "")
    layout = _layout(cfg, tmp_path / "e")
    infra = ScenarioRun(
        _scenario(),
        Path("s.yaml"),
        2026,
        SessionResult("scenario", 2026, layout, None, ProbeLog(), infra_error="licence"),
    )
    results = scenario_checks(cfg, [missing, infra])
    assert [r.status for r in results if r.target.subject == "scenario:acme/basic"].count(Status.ERROR) == 2


def test_samples_and_sources(tmp_path: Path) -> None:
    (tmp_path / "kit" / "samples").mkdir(parents=True)
    (tmp_path / "kit" / "samples" / "a.dwg").write_bytes(b"x")
    assert find_sample("a.dwg", [tmp_path / "kit" / "samples"]) == (tmp_path / "kit/samples/a.dwg").resolve()
    assert find_sample("b.dwg", [tmp_path]) is None
    (tmp_path / "repo" / "scenarios" / "acme.x").mkdir(parents=True)
    (tmp_path / "repo" / "scenarios" / "acme.x" / "r.yaml").write_text("x", encoding="utf-8")
    found = scenario_sources(
        tmp_path / "kit", "acme.x", ["scenarios/k.yaml", "scenarios/notes.txt"], tmp_path / "repo"
    )
    assert [p.name for p in found] == ["k.yaml", "r.yaml"]


# ---- authoring aids --------------------------------------------------------------------------------------


def test_skeleton_and_feature_drafts_are_valid(tmp_path: Path) -> None:
    (tmp_path / "skel.yaml").write_text(skeleton("acme.x", ["ACME_A", "ACME_B"]), encoding="utf-8")
    assert load_scenario(tmp_path / "skel.yaml").scenario == "acme.x/basic"
    assert "#  - run: ACME_B" in (tmp_path / "skel.yaml").read_text("utf-8")
    feature = Feature(
        id="F1",
        name="Dimension all",
        commands=["ACME_DIMALL"],
        sample="samples/a.dwg",
        expected="Every line dimensioned",
        how_to="Type it",
    )
    text = from_feature("acme.x", feature)
    assert "# Expected (publisher): Every line dimensioned" in text
    written = write_from_features("acme.x", [feature], tmp_path / "out")
    scenario = load_scenario(written[0])
    assert scenario.setup.open == "samples/a.dwg" and scenario.steps[0].run == "ACME_DIMALL"  # type: ignore[union-attr]
    assert write_from_features("acme.x", [feature], tmp_path / "out") == []  # never overwrites by default


def test_scenario_cli(make_kit: KitFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kit = make_kit("bundle")
    monkeypatch.setattr(
        "mta.cli.scenario_cmds.prefill_from_package", lambda p, c: type("P", (), {"commands": ["X1"]})
    )
    out = CliRunner().invoke(app, ["scenario", "new", "acme.mytools", "--kit", str(kit)]).output
    assert "#  - run: X1" in out
    result = CliRunner().invoke(app, ["scenario", "from-features", "--kit", str(kit)])
    assert result.exit_code == 0 and "f1-dimension-all-lines.yaml" in result.output
    good = kit / "scenarios" / "f1-dimension-all-lines.yaml"
    (tmp_path / "bad.yaml").write_text("scenario: a\n", encoding="utf-8")
    checked = CliRunner().invoke(app, ["scenario", "check", str(good), str(tmp_path / "bad.yaml")])
    assert checked.exit_code == 1 and "OK " in checked.output and "FAIL" in checked.output


# ---- report.html and exit codes --------------------------------------------------------------------------


def test_report_html(make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path) -> None:
    kit = make_kit("bundle")
    data = tmp_path / "data"
    intake = intake_kit(kit, cfg, data, clean_scanner)
    static = run_static_stage(intake, cfg, data, OFFLINE_SERVICES)
    write_job_report(intake, static, cfg, duration_ms=2500)
    html = (intake.job_dir / "report.html").read_text("utf-8")
    assert "NEEDS HUMAN" in html and "SIG-001" in html and "MyTools for AutoCAD" in html
    assert "<script src" not in html and "https://cdn" not in html  # offline (P1-R22)
    document = json.loads((intake.job_dir / "report.json").read_text("utf-8"))
    rerendered = render_html(document)
    assert "Findings" in rerendered and "Package inventory" in rerendered


def test_screenshot_embedding(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(b"\x89PNG small")
    (tmp_path / "big.png").write_bytes(b"0" * (3 * 1024 * 1024 + 1))
    shots = screenshot_uris(tmp_path, ["a.png", "big.png", "missing.png", "../outside.png"])
    assert [name for name, _ in shots] == ["a.png"] and shots[0][1].startswith("data:image/png;base64,")


def test_exit_codes() -> None:
    from mta.cli.kit_cmds import EXIT_CODES

    assert EXIT_CODES == {
        Recommendation.APPROVE: 0,
        Recommendation.NEEDS_HUMAN: 10,
        Recommendation.REJECT: 20,
    }
