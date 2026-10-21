"""report.html: one offline file for the reviewer (requirements.md P1-R22, design.md §7).

Rendered from the validated report.json document, so the HTML never shows anything the JSON does not have.
No external resources: CSS and JS are inline, and screenshots are embedded as data URIs.
"""

import base64
import mimetypes
from collections import defaultdict
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

_ORDER = {"FAIL": 0, "ERROR": 1, "NEEDS_REVIEW": 2, "WARN": 3, "PASS": 4, "SKIPPED": 5}
_SEVERITY = {"BLOCKER": 0, "MAJOR": 1, "MINOR": 2, "INFO": 3}
_FAMILIES = {
    "PKG": "Package", "MAN": "Manifest", "BIN": "Binaries", "SIG": "Signing & malware", "LST": "Listing",
    "LOD": "Loading", "CMD": "Commands", "RUN": "Runtime health", "WFL": "Workflow scenarios",
}  # fmt: skip
MAX_SCREENSHOT_BYTES = 3 * 1024 * 1024


def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("mta.report", "templates"), autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True, lstrip_blocks=True,
    )  # fmt: skip
    env.filters["family"] = lambda check_id: _FAMILIES.get(
        str(check_id).split("-")[0], str(check_id).split("-")[0]
    )
    return env


def screenshot_uris(kit_root: Path, paths: list[str]) -> list[tuple[str, str]]:
    """Listing screenshots as (name, data URI); skipped when missing or too large."""
    found = []
    for rel in paths:
        path = (kit_root / rel).resolve()
        if not path.is_file() or not path.is_relative_to(kit_root.resolve()):
            continue
        if path.stat().st_size > MAX_SCREENSHOT_BYTES:
            continue
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        found.append((rel, f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"))
    return found


def render_html(
    document: dict[str, Any],
    *,
    screenshots: list[tuple[str, str]] | None = None,
    sessions: list[dict[str, Any]] | None = None,
) -> str:
    results = sorted(
        document.get("results", []),
        key=lambda r: (_ORDER.get(r["status"], 9), _SEVERITY.get(r["severity"], 9), r["check_id"],
                       r["target"].get("host_version") or 0),
    )  # fmt: skip
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        families[r["check_id"].split("-")[0]].append(r)
    versions = [m["host_version"] for m in document.get("matrix", [])]
    commands: dict[str, dict[str, Any]] = {}
    for c in document.get("inventory", {}).get("commands", []):
        row = commands.setdefault(c["name"], {"name": c["name"], "group": c.get("group"), "outcomes": {}})
        row["outcomes"].update({str(k): v for k, v in (c.get("outcomes") or {}).items()})
    counts = {s: sum(1 for r in results if r["status"] == s) for s in _ORDER}
    template = _environment().get_template("report.html.j2")
    return template.render(
        report=document,
        families=sorted(families.items(), key=lambda kv: min(_ORDER.get(r["status"], 9) for r in kv[1])),
        family_names=_FAMILIES,
        versions=versions,
        commands=sorted(commands.values(), key=lambda c: c["name"]),
        counts=counts,
        screenshots=screenshots or [],
        sessions=sessions or [],
    )
