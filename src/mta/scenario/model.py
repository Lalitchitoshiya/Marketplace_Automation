"""Scenario DSL v1 (scenario-dsl.md): parsing and validation. Phase 1 verbs: open, new, run, assert, save_as,
script (requirements.md P1-R19). GUI verbs (click, dialog, ...) are rejected until Phase 2.
"""

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Op = Literal["==", "!=", ">=", "<=", ">", "<"]
_VERSIONS = re.compile(r"^\s*(>=|<=|==|>|<)?\s*(\d{4})\s*$")


class ScenarioError(Exception):
    """The scenario file is invalid (a reviewer problem; the scenario is reported, never silently skipped)."""


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Count(_Base):
    op: Op
    value: int


class EntityCount(_Base):
    type: str = "*"  # ObjectARX class name, e.g. AcDbLine; "*" = any
    layer: str | None = None
    op: Op
    value: int


class Sysvar(_Base):
    name: str
    value: str | int | float


class Assertion(_Base):
    """One `assert:` mapping; several keys in one mapping are all checked."""

    entity_count: EntityCount | None = None
    layer_exists: str | None = None
    block_exists: str | None = None
    sysvar: Sysvar | None = None
    file_exists: str | None = None
    file_lines: Count | None = None
    file_contains: str | None = None
    no_exception: bool | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "Assertion":
        if not self.model_dump(exclude_none=True):
            raise ValueError("an assert step needs at least one assertion")
        if (self.file_lines or self.file_contains) and not self.file_exists:
            raise ValueError("file_lines / file_contains need file_exists (which file)")
        return self


class RunStep(_Base):
    run: str
    inputs: list[str] = Field(default_factory=list)  # prompt answers in order; "" = Enter
    expect_outcome: Literal["completed", "awaiting_input", "cancelled"] | None = None


class AssertStep(_Base):
    assert_: Assertion = Field(alias="assert")


class SaveAsStep(_Base):
    save_as: str  # file name inside the run folder


class ScriptStep(_Base):
    script: list[str]  # raw core-console script lines (escape hatch)


class OpenStep(_Base):
    open: str


Step = Annotated[RunStep | AssertStep | SaveAsStep | ScriptStep | OpenStep, Field(union_mode="left_to_right")]


class Setup(_Base):
    open: str | None = None  # sample drawing, relative to the kit's samples/ or the scenario file
    new: str | None = None  # template name; default: the core console's blank drawing


class Scenario(_Base):
    scenario: str
    version: Literal[1] = 1
    title: str
    hosts: list[str] = Field(default_factory=lambda: ["autocad"])
    host_versions: str = ">=2000"
    ui_mode: Literal["headless", "gui", "any"] = "any"
    timeout_s: int = Field(default=120, gt=0)
    setup: Setup = Field(default_factory=Setup)
    steps: list[Step] = Field(min_length=1)
    teardown: dict[str, Any] = Field(default_factory=dict)

    @field_validator("host_versions")
    @classmethod
    def _version_spec(cls, value: str) -> str:
        if not _VERSIONS.match(value):
            raise ValueError("host_versions must look like '>=2025' or '2026'")
        return value

    def applies_to(self, host_id: str, year: int) -> bool:
        match = _VERSIONS.match(self.host_versions)
        if match is None:  # pragma: no cover - validated on load
            return False
        op, bound = match.group(1) or "==", int(match.group(2))
        ok = {
            ">=": year >= bound,
            "<=": year <= bound,
            "==": year == bound,
            ">": year > bound,
            "<": year < bound,
        }
        return host_id in self.hosts and ok[op] and self.ui_mode in ("headless", "any")


def load_scenario(path: Path) -> Scenario:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Scenario.model_validate(data)
    except (OSError, yaml.YAMLError) as exc:
        raise ScenarioError(f"{path.name}: cannot read: {exc}") from exc
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
        raise ScenarioError(f"{path.name}: {problems}") from exc
