"""`mta kit ...`, `mta inspect` (static-only) and `mta run` (static + AutoCAD core-console runs)."""

import os
import time
from pathlib import Path
from typing import Annotated

import typer

from mta.adapters.autocad.dynamic import run_dynamic_stage
from mta.config import ConfigError, MtaConfig, load_config
from mta.intake.kit import Scanner, init_kit, validate_kit
from mta.intake.package import PackageError
from mta.intake.pipeline import IntakeError, IntakeResult, intake_kit, intake_package
from mta.intake.prefill import prefill_from_package
from mta.models import Recommendation
from mta.report.builder import write_job_report
from mta.static.malware import scan
from mta.static.stage import StaticOutcome, StaticServices, run_static_stage

# requirements.md P1-R24: 0 approve, 10 needs human, 20 reject; 2 usage error, 3 MTA internal error.
EXIT_CODES = {Recommendation.APPROVE: 0, Recommendation.NEEDS_HUMAN: 10, Recommendation.REJECT: 20}
EXIT_INTERNAL = 3

kit_app = typer.Typer(help="Create and validate Input Kits.", no_args_is_help=True)

NoScanOption = Annotated[
    bool, typer.Option("--no-scan", help="Skip the malware scan. Only for trusted MTA fixtures.")
]
ConfigDirOption = Annotated[Path | None, typer.Option("--config-dir", help="Config directory.")]
DataDirOption = Annotated[
    Path | None,
    typer.Option("--data-dir", help="Where jobs and artifacts are stored (default: MTA_DATA_DIR or ./.mta)."),
]


def _config(config_dir: Path | None) -> MtaConfig:
    try:
        return load_config(config_dir)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


def _scanner(no_scan: bool, quiet: bool = False) -> Scanner | None:
    if no_scan:
        if not quiet:
            typer.echo("WARNING: malware scan skipped (--no-scan)", err=True)
        return None
    return scan


def _data_dir(data_dir: Path | None) -> Path:
    return data_dir or Path(os.environ.get("MTA_DATA_DIR", ".mta"))


@kit_app.command("init")
def kit_init(
    folder: Annotated[Path, typer.Argument(help="New kit folder (must be empty or not exist).")],
    package: Annotated[Path, typer.Option("--package", exists=True, help="MSI, ZIP or .bundle folder.")],
    app_id: Annotated[
        str | None, typer.Option("--app-id", help="Stable app id (default: from file name).")
    ] = None,
    version: Annotated[
        str | None, typer.Option("--version", help="App version (default: from the package).")
    ] = None,
    config_dir: ConfigDirOption = None,
) -> None:
    """Create a kit folder with the package and a submission.yaml pre-filled from the package."""
    try:
        prefill = prefill_from_package(package, _config(config_dir))
        init_kit(folder, package, app_id, version, prefill)
    except (PackageError, FileExistsError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"kit created: {folder}")
    detected = {"version": prefill.version, "title": prefill.title, "publisher": prefill.publisher}
    for key, value in detected.items():
        if value:
            typer.echo(f"  detected {key}: {value}")
    for product in prefill.products:
        typer.echo(f"  detected {product.host_id} versions: {product.versions}")
    if prefill.commands:
        typer.echo(f"  detected commands: {', '.join(prefill.commands)}")
    for note in prefill.notes:
        typer.echo(f"  note: {note}")
    typer.echo("next: fill in submission.yaml, add docs/, media/, samples/, then `mta kit validate`")


@kit_app.command("validate")
def kit_validate(
    folder: Annotated[Path, typer.Argument(help="Kit folder.")],
    no_scan: NoScanOption = False,
    config_dir: ConfigDirOption = None,
) -> None:
    """Check a kit without running any tests. Exit code 1 if it has errors."""
    cfg = _config(config_dir)
    check = validate_kit(folder, cfg.thresholds.kit, cfg.thresholds.extract, _scanner(no_scan))
    for problem in check.problems:
        typer.echo(str(problem))
    errors = sum(p.level == "error" for p in check.problems)
    warnings = len(check.problems) - errors
    if check.scan is not None:
        typer.echo(f"malware scan: {check.scan.outcome}")
    typer.echo(f"{'VALID' if check.ok else 'INVALID'}: {errors} error(s), {warnings} warning(s)")
    if not check.ok:
        raise typer.Exit(1)


def _print_intake(result: IntakeResult) -> None:
    sub = result.submission
    typer.echo(f"job {result.job.job_id}: {result.job.state}")
    typer.echo(f"  app        {sub.app_id} {sub.app_version}")
    typer.echo(f"  package    {sub.package.filename} ({sub.package.kind}, {sub.package.size_bytes} bytes)")
    typer.echo(f"  sha256     {sub.package.sha256}")
    typer.echo(
        f"  documents  {len(sub.documents)}, features {len(sub.features)}, artifacts {len(result.artifacts)}"
    )
    if result.mentions:
        typer.echo(f"  commands mentioned in docs: {', '.join(result.mentions)}")
    for warning in result.warnings:
        typer.echo(f"  {warning}")
    typer.echo(f"  job folder {result.job_dir}")


def _print_static(outcome: StaticOutcome) -> None:
    extraction = outcome.extraction
    typer.echo("static checks:")
    for r in sorted(outcome.results, key=lambda r: r.check_id):
        where = f"[{r.target.host_version}] " if r.target.host_version else ""
        typer.echo(f"  {r.check_id} {r.status:<12} {where}{r.message}")
    if extraction.payload_dir is not None:
        typer.echo(f"  payload    {len(extraction.files)} file(s) in {extraction.payload_dir}")
    if extraction.msi is not None:
        actions = extraction.msi.custom_actions
        code = sum(a.executes_code for a in actions)
        typer.echo(f"  msi        {len(actions)} custom action(s), {code} run code")
    for name in extraction.nested_archives:
        typer.echo(f"  nested archive (not extracted): {name}")
    if outcome.bundle is not None:
        for c in outcome.bundle.components:
            versions = ", ".join(map(str, c.host_versions)) or "none"
            typer.echo(f"  component  {c.app_name}: {c.module} -> AutoCAD {versions}")
    if outcome.binary is not None:
        for b in outcome.binary.components:
            ui = "GUI required" if b.gui_required else "core-console OK"
            typer.echo(f"  binary     {b.app_name}: {ui}; commands {', '.join(b.commands) or '-'}")


OfflineOption = Annotated[
    bool, typer.Option("--offline", help="Skip network checks (LST-001/002). Also set by MTA_OFFLINE=1.")
]


def _analyze(
    package: Path | None,
    kit: Path | None,
    no_scan: bool,
    offline: bool,
    config_dir: Path | None,
    data_dir: Path | None,
    *,
    dynamic: bool,
) -> None:
    if (package is None) == (kit is None):
        typer.echo("error: give either a PACKAGE or --kit (not both)", err=True)
        raise typer.Exit(2)
    started = time.monotonic()
    cfg = _config(config_dir)
    data = _data_dir(data_dir)
    try:
        if kit is not None:
            result = intake_kit(kit, cfg, data, _scanner(no_scan))
        elif package is not None:
            result = intake_package(package, cfg, data, _scanner(no_scan))
    except IntakeError as exc:
        for problem in exc.check.problems:
            typer.echo(str(problem), err=True)
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    except PackageError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    _print_intake(result)
    services = StaticServices(
        scanner=_scanner(no_scan, quiet=True), offline=offline or os.environ.get("MTA_OFFLINE") == "1"
    )
    outcome = run_static_stage(result, cfg, data, services)
    _print_static(outcome)
    gate = "allowed" if outcome.gate.dynamic_allowed else "BLOCKED: " + "; ".join(outcome.gate.reasons)
    typer.echo(f"dynamic phase: {gate}")
    dynamic_outcome = None
    if dynamic:
        typer.echo("dynamic checks (AutoCAD core console):")
        dynamic_outcome = run_dynamic_stage(result, outcome, cfg, data)
        for s in dynamic_outcome.sessions:
            state = s.infra_error or ("clean" if s.log.clean else "events incomplete")
            exit_text = s.console.exit_hex if s.console else "-"
            typer.echo(f"  session    {s.kind} AutoCAD {s.year}: exit {exit_text}, {state} ({s.layout.root})")
        for r in dynamic_outcome.results:
            subject = "" if r.target.subject == "package" else f" {r.target.subject}"
            typer.echo(f"  {r.check_id} {r.status:<12} [{r.target.host_version}]{subject} {r.message}")
    elapsed = int((time.monotonic() - started) * 1000)
    report = write_job_report(result, outcome, cfg, elapsed, dynamic_outcome)
    typer.echo(f"RECOMMENDATION: {report.recommendation}")
    for reason in report.recommendation_reasons:
        typer.echo(f"  - {reason}")
    typer.echo(f"report: {result.job_dir / 'report.html'}")
    typer.echo(f"        {result.job_dir / 'report.json'}")
    raise typer.Exit(EXIT_CODES[report.recommendation])


def inspect(
    package: Annotated[Path | None, typer.Argument(exists=True, help="MSI, ZIP or .bundle folder.")] = None,
    kit: Annotated[
        Path | None, typer.Option("--kit", exists=True, file_okay=False, help="Input Kit folder.")
    ] = None,
    no_scan: NoScanOption = False,
    offline: OfflineOption = False,
    config_dir: ConfigDirOption = None,
    data_dir: DataDirOption = None,
) -> None:
    """Static-only analysis: every static check and report.json, without starting AutoCAD (P1-R11)."""
    _analyze(package, kit, no_scan, offline, config_dir, data_dir, dynamic=False)


def run(
    package: Annotated[Path | None, typer.Argument(exists=True, help="MSI, ZIP or .bundle folder.")] = None,
    kit: Annotated[
        Path | None, typer.Option("--kit", exists=True, file_okay=False, help="Input Kit folder.")
    ] = None,
    no_scan: NoScanOption = False,
    offline: OfflineOption = False,
    config_dir: ConfigDirOption = None,
    data_dir: DataDirOption = None,
) -> None:
    """Test a submission: static checks, then AutoCAD core-console runs. Give a package or --kit."""
    _analyze(package, kit, no_scan, offline, config_dir, data_dir, dynamic=True)
