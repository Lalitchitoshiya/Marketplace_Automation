"""JSON Schemas generated from the Pydantic models (the models are normative; data-contracts.md §1).

The committed `*.schema.json` files are what other tools and the dashboard consume. A test fails when they
drift from the models; regenerate with `mta schema export`.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import BaseModel

from mta.models import CheckResult, Job, Report, Run, Submission

SCHEMA_DIR = Path(__file__).parent
SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "submission": Submission,
    "job": Job,
    "run": Run,
    "check-result": CheckResult,
    "report": Report,
}


def generate_schema(name: str) -> dict[str, Any]:
    model = SCHEMA_MODELS[name]
    schema = model.model_json_schema(by_alias=True, mode="serialization")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://mta.autodesk.internal/schemas/{name}.schema.json",
        **schema,
    }


def schema_path(name: str) -> Path:
    return SCHEMA_DIR / f"{name}.schema.json"


def export_all(out_dir: Path = SCHEMA_DIR) -> list[Path]:
    written = []
    for name in SCHEMA_MODELS:
        path = out_dir / f"{name}.schema.json"
        path.write_text(json.dumps(generate_schema(name), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


@cache
def load_schema(name: str) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(schema_path(name).read_text(encoding="utf-8"))
    return schema


def validate(name: str, document: Any) -> list[str]:
    """Validate a JSON document against a committed schema. Returns error messages (empty = valid)."""
    validator = jsonschema.Draft202012Validator(load_schema(name))
    return [
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    ]
