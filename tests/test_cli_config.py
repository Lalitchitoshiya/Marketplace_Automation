from pathlib import Path

from typer.testing import CliRunner

from mta.cli.app import app

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def test_config_validate_reports_ok() -> None:
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 0, result.output
    assert "config OK" in result.output
    assert "blocking now: PKG-001, SIG-003" in result.output


def test_config_validate_fails_on_bad_directory(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "validate", "--config-dir", str(tmp_path)])
    assert result.exit_code == 2
    assert "file not found" in result.output


def test_schema_check_accepts_sample_report() -> None:
    result = runner.invoke(app, ["schema", "check", "report", str(FIXTURES / "sample-report.json")])
    assert result.exit_code == 0, result.output
    assert "valid report" in result.output


def test_schema_check_rejects_invalid_document(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"report_version": 1}', encoding="utf-8")
    result = runner.invoke(app, ["schema", "check", "report", str(bad)])
    assert result.exit_code == 1
    assert "INVALID" in result.output


def test_schema_export_writes_all_schemas(tmp_path: Path) -> None:
    result = runner.invoke(app, ["schema", "export", "--out", str(tmp_path)])
    assert result.exit_code == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "check-result.schema.json",
        "job.schema.json",
        "report.schema.json",
        "run.schema.json",
        "submission.schema.json",
    ]
