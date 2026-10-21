"""`mta doctor`: environment health (requirements.md P1-R03)."""

import os
from pathlib import Path
from typing import Annotated

import typer

from mta.config import ConfigError, load_config
from mta.doctor import Diagnosis, check_basic, check_deep, fix_wer

_MARK = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}


def _print(diagnosis: Diagnosis) -> None:
    for item in diagnosis.items:
        typer.echo(f"  {_MARK[item.level]} {item.name}: {item.detail}")
        if item.hint:
            typer.echo(f"       fix: {item.hint}")


def doctor(
    deep: Annotated[
        bool, typer.Option("--deep", help="Also run the canary plugin in each core console.")
    ] = False,
    fix: Annotated[bool, typer.Option("--fix", help="Configure WER LocalDumps (administrator).")] = False,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", help="Config directory.")] = None,
    data_dir: Annotated[
        Path | None, typer.Option("--data-dir", help="Data directory (default .mta).")
    ] = None,
) -> None:
    """Check that this machine can run MTA. Exit code 1 when something required is missing."""
    try:
        cfg = load_config(config_dir)
    except ConfigError as exc:
        typer.echo(f"  FAIL config: {exc}")
        raise typer.Exit(1) from exc
    data = data_dir or Path(os.environ.get("MTA_DATA_DIR", ".mta"))
    if fix:
        typer.echo(fix_wer(data.resolve() / "dumps"))
    diagnosis = check_basic(cfg, data)
    typer.echo("environment:")
    _print(diagnosis)
    if deep and diagnosis.healthy:
        typer.echo("deep check (canary plugin, ADR-0003 behaviours):")
        deep_result = check_deep(cfg, data)
        _print(deep_result)
        diagnosis.items += deep_result.items
    typer.echo("HEALTHY" if diagnosis.healthy else "UNHEALTHY: dynamic checks would be ERROR")
    if not diagnosis.healthy:
        raise typer.Exit(1)
