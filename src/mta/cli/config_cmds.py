"""`mta config ...` and `mta schema ...` commands (step 5)."""

import json
from pathlib import Path
from typing import Annotated

import typer

from mta import schemas
from mta.config import ConfigError, load_config

config_app = typer.Typer(help="Inspect and validate the config/ directory.", no_args_is_help=True)
schema_app = typer.Typer(help="Export and use the JSON Schemas of the data contracts.", no_args_is_help=True)

ConfigDirOption = Annotated[
    Path | None, typer.Option("--config-dir", help="Config directory (default: MTA_CONFIG_DIR or ./config).")
]


@config_app.command("validate")
def config_validate(config_dir: ConfigDirOption = None) -> None:
    """Validate all config files and their cross-references."""
    try:
        cfg = load_config(config_dir)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    typer.echo(f"config OK: {cfg.directory}")
    typer.echo(f"  snapshot sha256: {cfg.sha256}")
    for host_id, host in cfg.hosts.hosts.items():
        versions = ", ".join(f"{v.year}{'' if v.verified else ' (unverified)'}" for v in host.versions)
        typer.echo(f"  host {host_id}: {versions}")
    enabled = [c for c in cfg.checks.checks.values() if c.enabled]
    blocking = [cid for cid in cfg.checks.checks if cfg.checks.effective_severity(cid).value == "BLOCKER"]
    typer.echo(f"  checks: {len(enabled)} enabled, blocking now: {', '.join(blocking) or 'none'}")


@schema_app.command("export")
def schema_export(
    out_dir: Annotated[Path, typer.Option("--out", help="Output directory.")] = schemas.SCHEMA_DIR,
) -> None:
    """Regenerate the JSON Schemas from the models."""
    for path in schemas.export_all(out_dir):
        typer.echo(f"wrote {path}")


@schema_app.command("check")
def schema_check(
    name: Annotated[str, typer.Argument(help=f"One of: {', '.join(schemas.SCHEMA_MODELS)}")],
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="JSON document to validate.")],
) -> None:
    """Validate a JSON document (e.g. a report.json) against a schema."""
    if name not in schemas.SCHEMA_MODELS:
        typer.echo(f"unknown schema '{name}'", err=True)
        raise typer.Exit(2)
    errors = schemas.validate(name, json.loads(file.read_text(encoding="utf-8")))
    if errors:
        typer.echo(f"{file}: INVALID ({len(errors)} errors)", err=True)
        for error in errors:
            typer.echo(f"  {error}", err=True)
        raise typer.Exit(1)
    typer.echo(f"{file}: valid {name}")
