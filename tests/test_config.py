import shutil
from pathlib import Path

import pytest

from mta.config import REPO_ROOT, ConfigError, load_config
from mta.models import Severity

REPO_CONFIG = REPO_ROOT / "config"


@pytest.fixture
def config_copy(tmp_path: Path) -> Path:
    """A writable copy of the repo config, with the data/ folder it references."""
    shutil.copytree(REPO_CONFIG, tmp_path / "config")
    shutil.copytree(REPO_ROOT / "data", tmp_path / "data")
    return tmp_path / "config"


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {path.name}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_repo_config_loads() -> None:
    cfg = load_config(REPO_CONFIG)
    autocad = cfg.hosts.hosts["autocad"]
    assert autocad.version(2026).verified
    assert autocad.core_console is not None
    assert autocad.core_console.cancel_line == "(command)"
    assert len(cfg.checks.checks) == 40


def test_hex_exit_codes_are_parsed() -> None:
    codes = load_config(REPO_CONFIG).hosts.hosts["autocad"].exit_codes
    assert codes["access_violation"] == 0xC0000005
    assert codes["failfast"] == 0x80131623


def test_builtin_command_list_is_available() -> None:
    commands = load_config(REPO_CONFIG).builtin_commands("autocad", 2026)
    assert {"LINE", "CIRCLE", "NETLOAD"} <= commands
    assert len(commands) > 400


def test_provisional_blockers_are_capped() -> None:
    checks = load_config(REPO_CONFIG).checks
    assert checks.effective_severity("SIG-003") is Severity.BLOCKER  # safety gate, not provisional
    assert checks.effective_severity("CMD-002") is Severity.MAJOR  # provisional BLOCKER capped
    assert checks.effective_severity("LST-002") is Severity.MINOR


def test_snapshot_hash_is_stable_and_content_sensitive(config_copy: Path) -> None:
    first = load_config(config_copy).sha256
    assert load_config(config_copy).sha256 == first
    _edit(config_copy / "thresholds.yaml", "per_command_timeout_s: 20", "per_command_timeout_s: 25")
    assert load_config(config_copy).sha256 != first


def test_revealing_probe_names_are_rejected(config_copy: Path) -> None:
    _edit(config_copy / "probe_identity.yaml", "WorkspaceAssist", "MtaProbe")
    with pytest.raises(ConfigError, match="must not reveal"):
        load_config(config_copy)


def test_probe_command_colliding_with_builtin_is_rejected(config_copy: Path) -> None:
    _edit(config_copy / "probe_identity.yaml", "end: WSA_END", "end: LINE")
    with pytest.raises(ConfigError, match=r"collide with AutoCAD 2026: \['LINE'\]"):
        load_config(config_copy)


def test_missing_command_list_is_reported(config_copy: Path) -> None:
    (config_copy.parent / "data" / "autocad" / "2026" / "commands.txt").unlink()
    with pytest.raises(ConfigError, match="builtin_commands_file not found"):
        load_config(config_copy)


def test_all_problems_are_reported_together(config_copy: Path) -> None:
    _edit(config_copy / "checks.yaml", "PKG-001:", "pkg-1:")
    _edit(config_copy / "thresholds.yaml", "cancel_lines: 2", "cancel_lines: 0")
    with pytest.raises(ConfigError) as exc:
        load_config(config_copy)
    assert "checks.yaml" in str(exc.value)
    assert "thresholds.yaml" in str(exc.value)


def test_missing_file_is_reported(config_copy: Path) -> None:
    (config_copy / "hosts.yaml").unlink()
    with pytest.raises(ConfigError, match=r"hosts\.yaml: file not found"):
        load_config(config_copy)
