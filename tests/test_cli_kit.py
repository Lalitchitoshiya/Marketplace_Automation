from pathlib import Path

import pytest
from typer.testing import CliRunner

from mta.cli.app import app
from tests.conftest import KitFactory, make_zip

runner = CliRunner()


def test_kit_init_then_validate(tmp_path: Path) -> None:
    package = make_zip(tmp_path)
    result = runner.invoke(app, ["kit", "init", str(tmp_path / "kit"), "--package", str(package)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["kit", "validate", str(tmp_path / "kit"), "--no-scan"])
    assert result.exit_code == 0, result.output
    assert "VALID: 0 error(s)" in result.output


def test_kit_validate_reports_errors(make_kit: KitFactory) -> None:
    kit = make_kit()
    (kit / "submission.yaml").unlink()
    result = runner.invoke(app, ["kit", "validate", str(kit), "--no-scan"])
    assert result.exit_code == 1
    assert "INVALID" in result.output


@pytest.mark.usefixtures("offline_cli")
def test_run_with_kit_performs_intake(make_kit: KitFactory, tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["run", "--kit", str(make_kit()), "--no-scan", "--offline", "--data-dir", str(tmp_path / "data")]
    )
    assert result.exit_code == 10, result.output  # NEEDS_HUMAN (P1-R24): unsigned test kit
    assert "RECEIVED" in result.output
    assert "acme.mytools 2.3.0" in result.output
    assert "PKG-001 PASS" in result.output
    assert "PKG-002 PASS" in result.output
    assert len(list((tmp_path / "data" / "jobs").iterdir())) == 1


@pytest.mark.usefixtures("offline_cli")
def test_run_with_package(tmp_path: Path) -> None:
    package = make_zip(tmp_path)
    result = runner.invoke(
        app, ["run", str(package), "--no-scan", "--offline", "--data-dir", str(tmp_path / "data")]
    )
    assert result.exit_code == 10, result.output  # NEEDS_HUMAN (P1-R24): unsigned test kit
    assert "Acme.zip (zip" in result.output


def test_run_needs_exactly_one_input(make_kit: KitFactory, tmp_path: Path) -> None:
    assert runner.invoke(app, ["run"]).exit_code == 2
    package = make_zip(tmp_path)
    assert runner.invoke(app, ["run", str(package), "--kit", str(make_kit())]).exit_code == 2


def test_run_with_invalid_kit_exits_2(make_kit: KitFactory, tmp_path: Path) -> None:
    kit = make_kit()
    (kit / "submission.yaml").unlink()
    result = runner.invoke(
        app, ["run", "--kit", str(kit), "--no-scan", "--offline", "--data-dir", str(tmp_path / "d")]
    )
    assert result.exit_code == 2
