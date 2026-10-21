"""Step 12 live checks (marker `autocad`, run with `pytest -m autocad`): baseline, component loading, crash
containment, through the real pipeline. Only MTA's own plugins run here.
"""

import psutil
import pytest

from mta import doctor
from mta.adapters.autocad.console import installed_versions
from mta.adapters.autocad.dynamic import DynamicOutcome, run_dynamic_stage
from mta.adapters.autocad.probe import probe_dll
from mta.adapters.autocad.session import baseline
from mta.config import REPO_ROOT, MtaConfig
from mta.corpus.synthetic import built_dll, make_bundle, make_kit
from mta.intake.pipeline import intake_kit
from mta.models import Status
from mta.static.stage import StaticServices, run_static_stage
from tests.conftest import OFFLINE_SERVICES, clean_scanner

pytestmark = pytest.mark.autocad

DATA = REPO_ROOT / ".mta" / "live12"  # short root (F28)


@pytest.fixture(scope="module")
def ready(cfg: MtaConfig) -> list[int]:
    years = [y for y in installed_versions(cfg) if probe_dll(cfg, y).is_file()]
    if not years:
        pytest.skip("no installed AutoCAD with a built probe (uv run mta probe build)")
    return years


def test_baseline_is_clean_in_every_installed_version(cfg: MtaConfig, ready: list[int]) -> None:
    for year in ready:
        result = baseline(cfg, year, DATA / "runs", probe_dll(cfg, year))
        assert result.infra_error is None, (year, result.infra_error, result.excerpt())
        start = result.log.of_type("session.start")[0].data
        assert start["host_version"].startswith(str(cfg.hosts.hosts["autocad"].version(year).api_major))


def _run_plugin(cfg: MtaConfig, project: str, name: str) -> DynamicOutcome:
    dll = built_dll(project, cfg, 2026)
    if not dll.is_file():
        pytest.skip(f"{project} not built (uv run mta corpus build)")
    bundle = make_bundle([dll], DATA / "pkgs", name=name)
    kit = make_kit(bundle, DATA / "kits", f"mta.{name.lower()}", [2026])
    intake = intake_kit(kit, cfg, DATA, clean_scanner)
    services = StaticServices(
        scanner=clean_scanner,
        signatures=OFFLINE_SERVICES.signatures,
        open_url=OFFLINE_SERVICES.open_url,
        resolve=OFFLINE_SERVICES.resolve,
    )  # real mta-inspect: GUI classification needs it
    static = run_static_stage(intake, cfg, DATA, services)
    return run_dynamic_stage(intake, static, cfg, DATA)


def _lod001(outcome: DynamicOutcome) -> Status:
    return next(
        r.status for r in outcome.results if r.check_id == "LOD-001" and r.target.host_version == 2026
    )


def test_sd01_loads(cfg: MtaConfig, ready: list[int]) -> None:
    outcome = _run_plugin(cfg, "Sd01Clean", "Sd01Clean")
    assert _lod001(outcome) is Status.PASS
    assert {r.check_id: r.status for r in outcome.results if r.target.host_version == 2026}[
        "LOD-003"
    ] is Status.PASS


def test_sd17_needs_gui(cfg: MtaConfig, ready: list[int]) -> None:
    """Step 12 'done when': a GUI-only plugin is NEEDS_REVIEW (requires GUI host), never FAIL."""
    assert _lod001(_run_plugin(cfg, "Sd17GuiRibbon", "Sd17GuiRibbon")) is Status.NEEDS_REVIEW


def test_crash_is_contained(cfg: MtaConfig, ready: list[int]) -> None:
    """F29/F30: crash recorded, reporter suppressed, no dialog left, no wait for the watchdog."""
    if not built_dll("Canary", cfg, 2026).is_file():
        pytest.skip("canary not built (uv run mta corpus build)")
    result = doctor._canary(cfg, 2026, (DATA / "runs").resolve(), "canary-crash", ["CANARY_THROW"], 90)
    assert result.console is not None and result.console.crashed and not result.console.timed_out
    assert result.log.of_type("exception.first_chance")
    leftovers = [
        p
        for p in psutil.process_iter(["name", "cmdline"])
        if (p.info["name"] or "").lower() in ("senddmp.exe", "cer_dialog.exe")
        and str(result.console.pid) in " ".join(p.info["cmdline"] or [])
    ]
    assert not leftovers


def test_runs_stay_under_the_path_limit(cfg: MtaConfig) -> None:
    assert (
        len(str((DATA / "runs" / "r000000" / "profile").resolve()))
        <= cfg.thresholds.coreconsole.max_profile_path
    )


def test_smoke_and_scenario_through_the_pipeline(cfg: MtaConfig, ready: list[int]) -> None:
    """Steps 13-14 live: SD-01's commands are smoke-tested and a scenario's assertions hold in AutoCAD."""
    dll = built_dll("Sd01Clean", cfg, 2026)
    if not dll.is_file():
        pytest.skip("SD-01 not built (uv run mta corpus build)")
    bundle = make_bundle([dll], DATA / "pkgs", name="Sd01Scn")
    kit = make_kit(bundle, DATA / "kits", "mta.sd01scn", [2026])
    (kit / "scenarios" / "line.yaml").write_text(
        "scenario: mta.sd01scn/line\ntitle: Add a line\nui_mode: headless\nsteps:\n"
        "  - run: SD01_ADDLINE\n    expect_outcome: completed\n"
        "  - assert:\n      entity_count: {type: AcDbLine, op: '==', value: 1}\n",
        encoding="utf-8",
    )
    intake = intake_kit(kit, cfg, DATA, clean_scanner)
    services = StaticServices(scanner=clean_scanner, signatures=OFFLINE_SERVICES.signatures, offline=True)
    outcome = run_dynamic_stage(intake, run_static_stage(intake, cfg, DATA, services), cfg, DATA)
    smoke = {o.name: o.outcome for o in outcome.commands[2026]}
    assert smoke == {"SD01_ADDLINE": "completed", "SD01_ASK": "awaiting_input", "SD01_HELLO": "completed"}
    wfl = {
        r.check_id: r.status
        for r in outcome.results
        if r.check_id.startswith("WFL") and r.target.host_version == 2026
    }
    assert wfl == {"WFL-001": Status.PASS, "WFL-002": Status.PASS}
