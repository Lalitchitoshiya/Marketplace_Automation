"""Typed models for the files in config/ (hosts, checks, thresholds, probe identity)."""

import re
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StringConstraints, field_validator

from mta.models.common import CheckId, HostId, Model, Severity


def _parse_exit_code(value: object) -> object:
    """Exit codes are written as hex strings in YAML ("0xC0000005") for readability."""
    if isinstance(value, str):
        return int(value, 16) if value.lower().startswith("0x") else int(value)
    return value


ExitCode = Annotated[int, BeforeValidator(_parse_exit_code)]
Runtime = Literal["net48", "net8.0-windows", "net10.0-windows", "python3.10", "python3.11", "python3.12"]


# ---- hosts.yaml ------------------------------------------------------------------------------------------


class CoreConsoleFacts(Model):
    exe: str
    output_encoding: str
    script_line_ending: Literal["lf"]
    product_switch: str | None = None
    language: str = "en-US"
    isolate: bool = True
    cancel_line: str
    quit_lines: list[str] = Field(min_length=1)
    command_exists_lisp: str
    dotnet_load_command: str
    crash_reporter: list[str] = Field(default_factory=list)
    errors_file: str | None = None

    @field_validator("command_exists_lisp")
    @classmethod
    def _has_name_placeholder(cls, value: str) -> str:
        if "{name}" not in value:
            raise ValueError("must contain the {name} placeholder")
        return value


class HostVersion(Model):
    year: int = Field(ge=2000, le=2100)
    internal: str
    runtime: Runtime
    api_major: int
    arx_import: str | None = None
    install_dir: str
    exe: str
    headless_exe: str | None = None
    builtin_commands_file: str | None = None
    verified: bool = False


class ManifestFacts(Model):
    file: str
    autodesk_product: str
    product_types: list[str]
    os_values: list[str]
    required_os: str
    plain_platforms: list[str]
    known_platforms: list[str]


class HostConfig(Model):
    display_name: str
    family: str
    core_console: CoreConsoleFacts | None = None
    exit_codes: dict[str, ExitCode] = Field(default_factory=dict)
    api_assemblies: list[str] = Field(default_factory=list)
    gui_only_assemblies: list[str] = Field(default_factory=list)
    plugin_dirs: list[str] = Field(default_factory=list)
    gui_type_prefixes: list[str] = Field(default_factory=list)  # BIN-008
    provided_assemblies: list[str] = Field(default_factory=list)  # BIN-004
    never_ship_assemblies: list[str] = Field(default_factory=list)  # BIN-005
    command_flags_file: str | None = None  # CommandFlags name -> value (F27)
    payload_extensions: list[str] = Field(default_factory=list)  # PKG-002 "deployable payload"
    manifest: ManifestFacts | None = None
    versions: list[HostVersion] = Field(min_length=1)

    @field_validator("versions")
    @classmethod
    def _unique_years(cls, versions: list[HostVersion]) -> list[HostVersion]:
        years = [v.year for v in versions]
        if len(years) != len(set(years)):
            raise ValueError(f"duplicate version years: {years}")
        return versions

    def version(self, year: int) -> HostVersion:
        for v in self.versions:
            if v.year == year:
                return v
        raise KeyError(f"{self.display_name} {year} is not configured")


class HostsConfig(Model):
    hosts: dict[HostId, HostConfig]


# ---- checks.yaml -----------------------------------------------------------------------------------------


class CheckConfig(Model):
    severity: Severity
    title: str
    enabled: bool = True
    provisional: bool = True  # capped at the provisional severity until validated on the corpus


class RecommendationConfig(Model):
    error_means_needs_human: bool = True
    provisional_severity_cap: Severity = Severity.MAJOR


class ChecksConfig(Model):
    recommendation: RecommendationConfig = Field(default_factory=RecommendationConfig)
    checks: dict[CheckId, CheckConfig]

    def effective_severity(self, check_id: str) -> Severity:
        """Catalog severity, capped while the check is provisional (check-catalog.md, Rules)."""
        cfg = self.checks[check_id]
        if cfg.provisional and cfg.severity is Severity.BLOCKER:
            return self.recommendation.provisional_severity_cap
        return cfg.severity


# ---- thresholds.yaml -------------------------------------------------------------------------------------


class CoreConsoleThresholds(Model):
    startup_timeout_s: int = Field(gt=0)
    quit_timeout_s: int = Field(gt=0)
    crash_exit_grace_s: int = Field(gt=0)
    max_profile_path: int = Field(gt=0)


class LoadThresholds(Model):
    per_component_warn_s: float = Field(gt=0)
    per_component_timeout_s: int = Field(gt=0)


class SmokeThresholds(Model):
    per_command_timeout_s: int = Field(gt=0)
    cancel_lines: int = Field(ge=1)
    batch: bool = True


class ScenarioThresholds(Model):
    default_timeout_s: int = Field(gt=0)


class ExtractThresholds(Model):
    max_bytes: int = Field(gt=0)
    max_files: int = Field(gt=0)
    max_compression_ratio: int = Field(gt=0)
    ratio_min_bytes: int = Field(ge=0)
    msi_timeout_s: int = Field(gt=0)


class ListingThresholds(Model):
    http_timeout_s: int = Field(gt=0)
    dns_timeout_s: int = Field(gt=0)
    max_redirects: int = Field(ge=0)


class SigningThresholds(Model):
    timeout_s: int = Field(gt=0)


class KitThresholds(Model):
    doc_max_bytes: int = Field(gt=0)
    screenshot_max_bytes: int = Field(gt=0)
    screenshot_max_count: int = Field(gt=0)
    video_max_bytes: int = Field(gt=0)
    sample_max_bytes: int = Field(gt=0)


class DoctorThresholds(Model):
    deep_max_start_quit_s: int = Field(gt=0)


class Thresholds(Model):
    coreconsole: CoreConsoleThresholds
    load: LoadThresholds
    smoke: SmokeThresholds
    scenario: ScenarioThresholds
    extract: ExtractThresholds
    listing: ListingThresholds
    signing: SigningThresholds
    kit: KitThresholds
    doctor: DoctorThresholds


# ---- probe_identity.yaml ---------------------------------------------------------------------------------

_REVEALING = re.compile(r"mta|probe|test", re.IGNORECASE)


# Probe names are written into generated C# source (mta probe build), so they are strictly constrained.
CommandName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,30}$")]
LispName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,30}$")]
FileName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")]
DotNetName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9.]{1,40}$")]
EnvName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,40}$")]


class ProbeCommands(Model):
    load: CommandName
    enumerate: CommandName
    mark: CommandName
    assert_: CommandName = Field(alias="assert")
    end: CommandName

    def all(self) -> list[str]:
        return [self.load, self.enumerate, self.mark, self.assert_, self.end]


class HostProbeIdentity(Model):
    assembly_name: DotNetName
    run_dir_env: EnvName
    lisp_function: LispName  # receives (getcname "X") results from the script (ADR-0003 F18)
    plan_file: FileName  # probe-protocol.md names these probe-plan.json / probe-events.ndjson
    events_file: FileName
    commands: ProbeCommands

    def visible_names(self) -> list[str]:
        return [
            self.assembly_name,
            self.run_dir_env,
            self.lisp_function,
            self.plan_file,
            self.events_file,
            *self.commands.all(),
        ]


class ProbeIdentity(Model):
    autocad: HostProbeIdentity

    @field_validator("autocad")
    @classmethod
    def _names_are_neutral(cls, identity: HostProbeIdentity) -> HostProbeIdentity:
        revealing = [n for n in identity.visible_names() if _REVEALING.search(n)]
        if revealing:
            raise ValueError(
                f"probe names must not reveal the test environment (Constitution §11): {revealing}"
            )
        return identity


# ---- static_rules.yaml -----------------------------------------------------------------------------------


class RiskyApi(Model):
    pattern: str
    why: str


class RiskyPInvoke(Model):
    dll: str
    entry: str
    why: str


class StaticRules(Model):
    risky_apis: list[RiskyApi]
    risky_pinvokes: list[RiskyPInvoke]
    ignored_url_hosts: list[str]
    framework_assemblies: list[str]
