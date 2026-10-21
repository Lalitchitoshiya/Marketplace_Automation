"""`mta scenario ...`: authoring aids for workflow scenarios (requirements.md P1-R20, P1-R27)."""

from pathlib import Path
from typing import Annotated

import typer

from mta.config import load_config
from mta.intake.kit import validate_kit
from mta.intake.prefill import prefill_from_package
from mta.scenario.generate import skeleton, write_from_features
from mta.scenario.model import ScenarioError, load_scenario

scenario_app = typer.Typer(help="Write and check workflow scenarios.", no_args_is_help=True)
KitOption = Annotated[Path, typer.Option("--kit", exists=True, file_okay=False, help="Input Kit folder.")]


@scenario_app.command("new")
def scenario_new(
    app_id: Annotated[str, typer.Argument(help="App id, e.g. acme.mytools.")],
    kit: Annotated[
        Path | None, typer.Option("--kit", exists=True, file_okay=False, help="Kit to read commands from.")
    ] = None,
    out: Annotated[Path | None, typer.Option("--out", help="Write here (default: print).")] = None,
) -> None:
    """Skeleton scenario listing the package's commands as commented `run` steps."""
    commands: list[str] = []
    if kit is not None:
        check = validate_kit(kit, load_config().thresholds.kit, load_config().thresholds.extract)
        if check.package is not None:
            commands = prefill_from_package(check.package, load_config()).commands
    text = skeleton(app_id, commands)
    if out is None:
        typer.echo(text, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        typer.echo(f"written: {out}")


@scenario_app.command("from-features")
def scenario_from_features(
    kit: KitOption,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Replace existing files.")] = False,
) -> None:
    """One draft scenario per feature in the kit's submission.yaml, written to the kit's scenarios/."""
    check = validate_kit(kit, load_config().thresholds.kit, load_config().thresholds.extract)
    if check.manifest is None:
        typer.echo("error: the kit's submission.yaml is not valid (run `mta kit validate`)", err=True)
        raise typer.Exit(2)
    if not check.manifest.features:
        typer.echo("no features in submission.yaml: nothing to generate")
        return
    for path in write_from_features(check.manifest.app.id, check.manifest.features, kit / "scenarios",
                                    overwrite=overwrite):  # fmt: skip
        typer.echo(f"written: {path}")


@scenario_app.command("check")
def scenario_check(
    files: Annotated[list[Path], typer.Argument(exists=True, help="Scenario YAML files.")],
) -> None:
    """Validate scenario files against the DSL (exit 1 when any is invalid)."""
    bad = 0
    for path in files:
        try:
            scenario = load_scenario(path)
            typer.echo(f"OK   {path}: {scenario.scenario} ({len(scenario.steps)} steps)")
        except ScenarioError as exc:
            bad += 1
            typer.echo(f"FAIL {exc}")
    if bad:
        raise typer.Exit(1)
