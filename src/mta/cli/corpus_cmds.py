"""`mta corpus ...`: MTA's own known-answer plugins and the accuracy run (requirements.md P1-R25, P1-R26)."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from mta.adapters.autocad.build import BuildError
from mta.adapters.autocad.console import installed_versions
from mta.config import ConfigError, load_config
from mta.corpus.runner import CaseResult, load_entries, measure, run_corpus
from mta.corpus.synthetic import SYNTHETIC, build_synthetic, built_dll

corpus_app = typer.Typer(help="MTA's own test plugins and the corpus accuracy run.", no_args_is_help=True)


@corpus_app.command("build")
def corpus_build(
    acad_version: Annotated[
        list[int] | None,
        typer.Option("--acad-version", help="AutoCAD versions (default: installed)."),
    ] = None,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", help="Config directory.")] = None,
) -> None:
    """Build every synthetic plugin (dotnet/synthetic/*) per installed AutoCAD API major."""
    try:
        cfg = load_config(config_dir)
        years = acad_version or installed_versions(cfg)
        projects = sorted(p.name for p in SYNTHETIC.iterdir() if (p / f"{p.name}.csproj").is_file())
        done: set[Path] = set()
        for year in years:
            for project in projects:
                if built_dll(project, cfg, year).parent in done:
                    continue
                typer.echo(f"built for AutoCAD {year}: {build_synthetic(project, cfg, year)}")
            done |= {built_dll(p, cfg, year).parent for p in projects}
    except (ConfigError, BuildError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _print_pass(results: list[CaseResult]) -> int:
    failed = 0
    for r in results:
        if r.skipped:
            typer.echo(f"  SKIP {r.case.id} {r.case.title}: {r.error}")
            continue
        failed += not r.ok
        expected = sorted(r.case.expected) or "-"
        detail = r.error or f"triggered {sorted(r.triggered) or '-'}, expected {expected}"
        timing = f" [{r.seconds:.0f} s, {r.versions_run} version(s)]" if r.error is None else ""
        typer.echo(f"  {'OK  ' if r.ok else 'FAIL'} {r.case.id} {r.case.title}: {detail}{timing}")
    baseline = next((r for r in results if r.case.id == "SD-01"), None)
    if baseline is not None:
        typer.echo(f"  SD-01 not green (environment baseline): {sorted(baseline.raw) or 'none'}")
        if baseline.error:
            typer.echo(f"  {baseline.error}")
    return failed


@corpus_app.command("run")
def corpus_run(
    only: Annotated[list[str] | None, typer.Option("--only", help="Only these cases (plus SD-01).")] = None,
    with_eicar: Annotated[
        bool, typer.Option("--with-eicar", help="Include SD-11 (EICAR file; Defender reports it).")
    ] = False,
    corpus_dir: Annotated[
        Path | None,
        typer.Option("--corpus-dir", exists=True, file_okay=False, help="Real entries (expected.yaml)."),
    ] = None,
    repeat: Annotated[int, typer.Option("--repeat", min=1, help="Passes, for determinism (E1.3).")] = 1,
    out: Annotated[Path | None, typer.Option("--out", help="Write metrics and cases as JSON.")] = None,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", help="Config directory.")] = None,
    data_dir: Annotated[Path | None, typer.Option("--data-dir", help="Data dir (default .mta).")] = None,
) -> None:
    """Run the corpus. Every case must match its expected checks (M2); prints the accuracy metrics."""
    cfg = load_config(config_dir)
    entries = load_entries(corpus_dir) if corpus_dir else []
    passes: list[list[CaseResult]] = []
    failed = 0
    for index in range(repeat):
        typer.echo(f"pass {index + 1} of {repeat}:")
        results = run_corpus(cfg, data_dir or Path(".mta"), only=only, with_eicar=with_eicar, entries=entries)
        failed += _print_pass(results)
        passes.append(results)
    metrics = measure(passes)
    typer.echo("metrics:")
    for name, value in asdict(metrics).items():
        shown = f"{value:.3f}" if isinstance(value, float) else value
        typer.echo(f"  {name}: {shown}")
    if out is not None:
        cases = [
            {
                "id": r.case.id,
                "pass": i + 1,
                "ok": r.ok,
                "triggered": sorted(r.triggered),
                "raw": sorted(r.raw),
                "expected": sorted(r.case.expected),
                "error": r.error,
                "seconds": round(r.seconds, 1),
                "versions_run": r.versions_run,
                "recommendation": r.recommendation,
                "job": r.job,
            }
            for i, p in enumerate(passes)
            for r in p
        ]
        out.write_text(json.dumps({"metrics": asdict(metrics), "cases": cases}, indent=2), encoding="utf-8")
        typer.echo(f"written: {out}")
    typer.echo("CORPUS OK" if not failed else f"CORPUS FAILED: {failed} case result(s)")
    if failed:
        raise typer.Exit(1)
