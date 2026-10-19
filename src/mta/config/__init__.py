"""Loading and validation of the config/ directory (Constitution §5: host facts live in config, not code)."""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from mta.config.models import ChecksConfig, HostsConfig, ProbeIdentity, StaticRules, Thresholds

CONFIG_FILES = ("hosts.yaml", "checks.yaml", "thresholds.yaml", "probe_identity.yaml", "static_rules.yaml")
REPO_ROOT = Path(__file__).resolve().parents[3]


class ConfigError(Exception):
    """Invalid or inconsistent configuration. The message lists every problem found."""


@dataclass(frozen=True)
class MtaConfig:
    directory: Path
    hosts: HostsConfig
    checks: ChecksConfig
    thresholds: Thresholds
    probe_identity: ProbeIdentity
    static_rules: StaticRules
    sha256: str  # snapshot hash of all config files, recorded on every Job (Constitution §9)

    def command_flags(self, host_id: str) -> dict[str, int]:
        """CommandFlags name -> value; empty when the host has no flags table."""
        file = self.hosts.hosts[host_id].command_flags_file
        if file is None:
            return {}
        data: dict[str, int] = json.loads((self.data_root / file).read_text(encoding="utf-8"))
        return data

    @property
    def data_root(self) -> Path:
        """Relative data paths in config (e.g. builtin_commands_file) resolve against the config's parent."""
        return self.directory.parent

    def builtin_commands(self, host_id: str, year: int) -> set[str]:
        version = self.hosts.hosts[host_id].version(year)
        if version.builtin_commands_file is None:
            return set()
        path = self.data_root / version.builtin_commands_file
        return {
            line.strip().upper()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }


def default_config_dir() -> Path:
    return Path(os.environ.get("MTA_CONFIG_DIR", REPO_ROOT / "config"))


def _read_yaml(path: Path, problems: list[str]) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        problems.append(f"{path.name}: file not found in {path.parent}")
    except yaml.YAMLError as exc:
        problems.append(f"{path.name}: invalid YAML: {exc}")
    return None


def _parse[M: BaseModel](model: type[M], name: str, data: Any, problems: list[str]) -> M | None:
    if data is None:
        return None
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            location = ".".join(str(p) for p in err["loc"]) or "<root>"
            problems.append(f"{name}: {location}: {err['msg']}")
    return None


def _cross_check(cfg: MtaConfig, problems: list[str]) -> None:
    for host_id, host in cfg.hosts.hosts.items():
        for version in host.versions:
            if (
                version.builtin_commands_file
                and not (cfg.data_root / version.builtin_commands_file).is_file()
            ):
                problems.append(
                    f"hosts.yaml: {host_id} {version.year}: builtin_commands_file not found: "
                    f"{version.builtin_commands_file}"
                )

        if host.command_flags_file and not (cfg.data_root / host.command_flags_file).is_file():
            problems.append(f"hosts.yaml: {host_id}: command_flags_file not found: {host.command_flags_file}")

    # Probe commands must not collide with built-in AutoCAD commands (ADR-0003 F24: the built-in would win).
    probe_cmds = {c.upper() for c in cfg.probe_identity.autocad.commands.all()}
    if "autocad" in cfg.hosts.hosts:
        for version in cfg.hosts.hosts["autocad"].versions:
            if version.builtin_commands_file and (cfg.data_root / version.builtin_commands_file).is_file():
                clashes = sorted(probe_cmds & cfg.builtin_commands("autocad", version.year))
                if clashes:
                    problems.append(
                        f"probe_identity.yaml: commands collide with AutoCAD {version.year}: {clashes}"
                    )


def load_config(directory: Path | None = None) -> MtaConfig:
    directory = (directory or default_config_dir()).resolve()
    problems: list[str] = []
    raw = {name: _read_yaml(directory / name, problems) for name in CONFIG_FILES}

    hosts = _parse(HostsConfig, "hosts.yaml", raw["hosts.yaml"], problems)
    checks = _parse(ChecksConfig, "checks.yaml", raw["checks.yaml"], problems)
    thresholds = _parse(Thresholds, "thresholds.yaml", raw["thresholds.yaml"], problems)
    probe = _parse(ProbeIdentity, "probe_identity.yaml", raw["probe_identity.yaml"], problems)
    rules = _parse(StaticRules, "static_rules.yaml", raw["static_rules.yaml"], problems)

    if problems or hosts is None or checks is None or thresholds is None or probe is None or rules is None:
        raise ConfigError("invalid configuration:\n  " + "\n  ".join(problems))

    digest = hashlib.sha256()
    for name in CONFIG_FILES:
        digest.update(name.encode())
        digest.update((directory / name).read_bytes())

    cfg = MtaConfig(directory, hosts, checks, thresholds, probe, rules, digest.hexdigest())
    _cross_check(cfg, problems)
    if problems:
        raise ConfigError("invalid configuration:\n  " + "\n  ".join(problems))
    return cfg
