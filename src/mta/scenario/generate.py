"""Scenario authoring aids (requirements.md P1-R20, P1-R27): skeletons and scenarios from kit features.

Generated files are drafts for a reviewer: commands become `run` steps, the publisher's expected result
becomes a comment above an assertion placeholder. They always parse, so they can be run as-is.
"""

import re
from pathlib import Path

import yaml

from mta.models import Feature


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "scenario"


def skeleton(app_id: str, commands: list[str]) -> str:
    lines = [
        f"scenario: {app_id}/basic",
        "version: 1",
        f"title: {yaml.safe_dump(f'{app_id}: basic workflow', default_style=None).strip()}",
        "hosts: [autocad]",
        'host_versions: ">=2025"',
        "ui_mode: headless",
        "timeout_s: 120",
        "setup: {}",
        "#  open: samples/your-drawing.dwg       # from the kit's samples/",
        "steps:",
        "  - script: ['(princ)']                 # replace with real steps; keeps the file runnable",
        "# Commands found in the package (uncomment, add inputs and assertions):",
    ]
    for command in commands:
        lines += [f"#  - run: {command}", "#    inputs: []", "#    expect_outcome: completed"]
    lines += [
        "#  - assert:",
        "#      entity_count: {type: AcDbLine, op: '>=', value: 1}",
        "#      layer_exists: '0'",
    ]
    return "\n".join(lines) + "\n"


def from_feature(app_id: str, feature: Feature) -> str:
    data: dict[str, object] = {
        "scenario": f"{app_id}/{_slug(feature.id)}-{_slug(feature.name)}",
        "version": 1,
        "title": feature.name,
        "hosts": ["autocad"],
        "host_versions": ">=2025",
        "ui_mode": "headless",
        "timeout_s": 120,
        "setup": {"open": feature.sample} if feature.sample else {},
        "steps": [{"run": c, "inputs": []} for c in feature.commands] or [{"script": ["(princ)"]}],
    }
    header = [f"# Draft from Input Kit feature {feature.id}. Review the inputs and add assertions."]
    if feature.how_to:
        header.append(f"# How to (publisher): {feature.how_to}")
    if feature.expected:
        header.append(f"# Expected (publisher): {feature.expected}")
    header.append("# Example assertion step:  - assert: {entity_count: {type: AcDbLine, op: '>=', value: 1}}")
    return "\n".join(header) + "\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def write_from_features(app_id: str, features: list[Feature], out_dir: Path, *, overwrite: bool = False
                        ) -> list[Path]:  # fmt: skip
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for feature in features:
        path = out_dir / f"{_slug(feature.id)}-{_slug(feature.name)}.yaml"
        if path.exists() and not overwrite:
            continue
        path.write_text(from_feature(app_id, feature), encoding="utf-8")
        written.append(path)
    return written
