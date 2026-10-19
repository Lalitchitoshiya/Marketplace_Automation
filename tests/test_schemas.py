import copy
import json
from pathlib import Path
from typing import Any

import pytest

from mta import schemas
from mta.models import Report, Status

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_report() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "sample-report.json").read_text(encoding="utf-8"))
    return data


@pytest.mark.parametrize("name", list(schemas.SCHEMA_MODELS))
def test_committed_schema_matches_models(name: str) -> None:
    committed = json.loads(schemas.schema_path(name).read_text(encoding="utf-8"))
    assert committed == schemas.generate_schema(name), f"{name} schema drifted: run `mta schema export`"


def test_sample_report_is_valid(sample_report: dict[str, Any]) -> None:
    assert schemas.validate("report", sample_report) == []
    report = Report.model_validate(sample_report)
    assert report.results[1].status is Status.FAIL


def test_model_output_validates_against_schema(sample_report: dict[str, Any]) -> None:
    dumped = Report.model_validate(sample_report).model_dump(mode="json", by_alias=True, exclude_none=True)
    assert schemas.validate("report", dumped) == []


def test_invalid_report_is_rejected_with_path(sample_report: dict[str, Any]) -> None:
    broken = copy.deepcopy(sample_report)
    broken["recommendation"] = "MAYBE"
    del broken["mta"]
    errors = schemas.validate("report", broken)
    assert any(e.startswith("recommendation:") for e in errors)
    assert any("'mta' is a required property" in e for e in errors)
