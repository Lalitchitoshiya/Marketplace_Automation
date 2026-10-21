"""`mta probe ...`: build the in-host probe from the confidential identity config (step 11)."""

from pathlib import Path
from typing import Annotated

import typer

from mta.adapters.autocad.console import installed_versions
from mta.adapters.autocad.probe import ProbeBuildError, build_probe, probe_dll
from mta.config import ConfigError, load_config

probe_app = typer.Typer(help="Build the in-host probe.", no_args_is_help=True)


@probe_app.command("build")
def probe_build(
    acad_version: Annotated[
        list[int] | None,
        typer.Option("--acad-version", help="AutoCAD versions (default: installed)."),
    ] = None,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", help="Config directory.")] = None,
) -> None:
    """Generate the identity from probe_identity.yaml and build the probe per installed AutoCAD API major."""
    try:
        cfg = load_config(config_dir)
        years = acad_version or installed_versions(cfg)
        if not years:
            raise ProbeBuildError("no AutoCAD installed: the probe builds against its assemblies")
        built: dict[Path, int] = {}
        for year in years:
            dll = probe_dll(cfg, year)
            if dll.parent in {d.parent for d in built}:
                continue  # same API major already built (e.g. 2025 and 2026)
            built[build_probe(cfg, acad_version=year)] = year
    except (ConfigError, ProbeBuildError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    for dll, year in built.items():
        typer.echo(f"probe built for AutoCAD {year}: {dll}")
