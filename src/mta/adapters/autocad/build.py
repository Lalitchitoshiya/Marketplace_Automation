"""Building MTA's own in-host code (probe, canary, synthetic plugins) for one AutoCAD version.

AutoCAD's API major is a binary break (design.md §4): 2025/2026 are R25 on .NET 8, 2027 is R26 on .NET 10
(verified from the installed assemblies in step 12). One build per API major, referencing that version's
installed assemblies, goes to `bin/acad<major>/`.
"""

import subprocess
from pathlib import Path

from mta.config import MtaConfig


class BuildError(Exception):
    """A build of MTA's own code failed (an MTA problem: dependent checks become ERROR)."""


def target_framework(cfg: MtaConfig, year: int, host_id: str = "autocad") -> str:
    return cfg.hosts.hosts[host_id].version(year).runtime


def output_dir(
    project: Path, cfg: MtaConfig, year: int, host_id: str = "autocad", tfm: str | None = None
) -> Path:
    name = f"acad{cfg.hosts.hosts[host_id].version(year).api_major}"
    return project / "bin" / (f"{name}-{tfm}" if tfm else name)


def build_for(
    project: Path,
    cfg: MtaConfig,
    year: int,
    *,
    assembly_name: str | None = None,
    tfm: str | None = None,
    timeout_s: int = 600,
) -> Path:
    """dotnet build against AutoCAD `year`; returns the output folder. `tfm` overrides the version's runtime
    (the corpus uses it for the wrong-framework case SD-06)."""
    out = output_dir(project, cfg, year, tfm=tfm)
    # Separate restore/intermediate folders per API major: one shared obj/ only knows one target framework.
    intermediate = f"{project / 'obj' / out.name}\\"
    command = [
        "dotnet",
        "build",
        str(project),
        "-c",
        "Release",
        f"-p:AcadVersion={year}",
        f"-p:AcadTfm={tfm or target_framework(cfg, year)}",
        f"-p:BaseIntermediateOutputPath={intermediate}",
        f"-p:MSBuildProjectExtensionsPath={intermediate}",
        "-p:DefaultItemExcludes=obj/**",  # every obj/ tree, not only this build's
        "-o",
        str(out),
        "-nologo",
    ]
    if assembly_name:
        command.append(f"-p:AssemblyName={assembly_name}")
    try:
        done = subprocess.run(command, capture_output=True, timeout=timeout_s, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BuildError(f"dotnet build could not run: {exc}") from exc
    if done.returncode != 0:
        output = done.stdout.decode(errors="replace").splitlines()
        errors = [line for line in output if "error" in line.lower()]
        raise BuildError(
            f"{project.name} build for AutoCAD {year} failed:\n" + "\n".join((errors or output)[-15:])
        )
    return out
