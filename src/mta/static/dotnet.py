"""Run `mta-inspect` (C#, metadata only, never loads plugin code) and parse its report (P1-R06)."""

import os
import subprocess
import tempfile
from pathlib import Path

from pydantic import Field, ValidationError

from mta.config import REPO_ROOT
from mta.models.common import Model

INSPECT_ENV = "MTA_INSPECT"
_BUILD_DIR = REPO_ROOT / "dotnet" / "src" / "MtaInspect" / "bin"
_TIMEOUT_S = 300


class InspectError(Exception):
    """mta-inspect is missing or failed: an MTA problem (ERROR), never the publisher's."""


class AssemblyRef(Model):
    name: str
    version: str


class CommandInfo(Model):
    global_name: str
    local_name: str | None
    group: str | None
    flags: int
    type: str
    method: str
    registered: bool


class LispFunctionInfo(Model):
    name: str
    type: str
    method: str


class PInvokeInfo(Model):
    dll: str
    entry: str


class ObfuscationInfo(Model):
    suspected: bool
    signals: list[str]


class AssemblyReport(Model):
    """Mirror of dotnet/src/MtaInspect/Report.cs; `extra="forbid"` catches contract drift."""

    path: str
    is_managed: bool
    machine: str
    architecture: str
    mixed_mode: bool
    assembly_name: str | None
    assembly_version: str | None
    target_framework: str | None
    references: list[AssemblyRef] = Field(default_factory=list)
    commands: list[CommandInfo] = Field(default_factory=list)
    lisp_functions: list[LispFunctionInfo] = Field(default_factory=list)
    command_classes: list[str] = Field(default_factory=list)
    extension_app_attributes: list[str] = Field(default_factory=list)
    extension_app_types: list[str] = Field(default_factory=list)
    pinvokes: list[PInvokeInfo] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    type_refs: list[str] = Field(default_factory=list)
    member_refs: list[str] = Field(default_factory=list)
    obfuscation: ObfuscationInfo
    error: str | None


class _Reports(Model):
    items: list[AssemblyReport]


def find_inspect() -> Path | None:
    """MTA_INSPECT, else the Release (then Debug) build in the repo."""
    configured = os.environ.get(INSPECT_ENV)
    if configured:
        return Path(configured) if Path(configured).is_file() else None
    for configuration in ("Release", "Debug"):
        candidate = _BUILD_DIR / configuration / "net8.0" / "mta-inspect.exe"
        if candidate.is_file():
            return candidate
    return None


def inspect_files(files: list[Path], tool: Path | None = None) -> list[AssemblyReport]:
    """One report per file, in order. Files are passed through a list file (no command-line length limit)."""
    if not files:
        return []
    tool = tool or find_inspect()
    if tool is None:
        raise InspectError(f"mta-inspect not found: build dotnet/src/MtaInspect or set {INSPECT_ENV}")
    with tempfile.TemporaryDirectory(prefix="mta-inspect-") as temp:
        listing = Path(temp) / "files.txt"
        listing.write_text("\n".join(str(f) for f in files), encoding="utf-8")
        try:
            done = subprocess.run(  # noqa: S603 (our own tool, fixed arguments)
                [str(tool), "--files-from", str(listing)],
                capture_output=True,
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InspectError(f"mta-inspect could not run: {exc}") from exc
    if done.returncode != 0:
        raise InspectError(
            f"mta-inspect exit {done.returncode}: {done.stderr.decode(errors='replace')[-500:]}"
        )
    try:
        return _Reports.model_validate_json(b'{"items":' + done.stdout + b"}").items
    except ValidationError as exc:
        raise InspectError(f"mta-inspect output does not match the contract: {exc}") from exc
