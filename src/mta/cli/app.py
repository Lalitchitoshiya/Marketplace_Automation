"""Entry point for the `mta` command.

Commands are added step by step (specs/phase-1-autocad-headless/steps.md).
"""

from typing import Annotated

import typer

from mta import __version__
from mta.cli.config_cmds import config_app, schema_app
from mta.cli.corpus_cmds import corpus_app
from mta.cli.doctor_cmds import doctor
from mta.cli.kit_cmds import inspect, kit_app, run
from mta.cli.probe_cmds import probe_app
from mta.cli.scenario_cmds import scenario_app

app = typer.Typer(
    name="mta",
    help="Marketplace Test Automation: automated testing of Autodesk Marketplace submissions.",
    no_args_is_help=True,
    add_completion=False,
)
app.command("run")(run)
app.command("inspect")(inspect)
app.command("doctor")(doctor)
app.add_typer(kit_app, name="kit")
app.add_typer(config_app, name="config")
app.add_typer(schema_app, name="schema")
app.add_typer(probe_app, name="probe")
app.add_typer(corpus_app, name="corpus")
app.add_typer(scenario_app, name="scenario")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"mta {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_print_version, is_eager=True, help="Show the MTA version and exit."
        ),
    ] = False,
) -> None:
    """Marketplace Test Automation."""


def main() -> None:
    app()
