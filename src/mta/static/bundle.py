"""Locate the `*.bundle` folder and parse `PackageContents.xml` safely (P1-R05).

Parsing uses defusedxml with DTDs forbidden, so entity expansion and external references cannot be used
against MTA. Element and attribute names are matched case-insensitively, as the AutoCAD autoloader does not
depend on case either.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import parse

from mta.config.models import HostConfig, HostVersion

MAX_MANIFEST_BYTES = 1 << 20
_SERIES = re.compile(r"^R(\d+)(?:\.(\d+))?$", re.IGNORECASE)
_GUID = re.compile(r"^\{?[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}?$", re.IGNORECASE)
_TRUE = {"true", "1", "yes"}


class ManifestError(Exception):
    """PackageContents.xml cannot be used at all (MAN-001)."""


@dataclass(frozen=True)
class Requirements:
    level: str  # "package", "components" or "component": where they were declared
    os: list[str]
    platforms: list[str]
    series_min: str | None
    series_max: str | None


@dataclass(frozen=True)
class ManifestCommand:
    global_name: str
    local_name: str | None
    group: str | None


@dataclass
class Component:
    app_name: str
    module: str  # ModuleName as written, e.g. "./Contents/MyTools.dll"
    version: str | None
    load_reasons: list[str]
    commands: list[ManifestCommand]
    requirements: Requirements | None  # effective: most specific level wins


@dataclass
class BundleManifest:
    attributes: dict[str, str]  # ApplicationPackage attributes, original case kept
    company: dict[str, str]
    requirements: Requirements | None  # package level
    components: list[Component] = field(default_factory=list)

    def attr(self, name: str) -> str | None:
        for key, value in self.attributes.items():
            if key.lower() == name.lower():
                return value.strip() or None
        return None

    @property
    def all_requirements(self) -> list[Requirements]:
        found = [self.requirements] if self.requirements else []
        return found + [c.requirements for c in self.components if c.requirements]


def find_bundles(payload: Path) -> list[Path]:
    """Top-most `*.bundle` folders (a bundle inside a bundle is part of the outer one)."""
    bundles: list[Path] = []
    for path in sorted(payload.rglob("*"), key=lambda p: len(p.parts)):
        if path.is_dir() and path.suffix.lower() == ".bundle" and not any(b in path.parents for b in bundles):
            bundles.append(path)
    return sorted(bundles)


def manifest_path(bundle: Path, file_name: str) -> Path | None:
    for child in bundle.iterdir():
        if child.is_file() and child.name.lower() == file_name.lower():
            return child
    return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in element if isinstance(c.tag, str) and _local(c.tag) == name.lower()]


def _get(element: ET.Element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if _local(key) == name.lower():
            return value.strip() or None
    return None


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split("|") if v.strip()]


def _requirements(element: ET.Element, level: str) -> Requirements | None:
    found = _children(element, "RuntimeRequirements")
    if not found:
        return None
    req = found[0]
    return Requirements(
        level=level,
        os=_split(_get(req, "OS")),
        platforms=_split(_get(req, "Platform")),
        series_min=_get(req, "SeriesMin"),
        series_max=_get(req, "SeriesMax"),
    )


def _load_reasons(entry: ET.Element) -> list[str]:
    reasons = [
        k for k, v in entry.attrib.items() if k.lower().startswith("loadon") and v.strip().lower() in _TRUE
    ]
    for block in _children(entry, "LoadReasons"):
        reasons += [_local(c.tag) for c in block if isinstance(c.tag, str)]
    return reasons


def parse_package_contents(path: Path) -> BundleManifest:
    """Parse and structurally validate the manifest; raises ManifestError for MAN-001 problems."""
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ManifestError(f"{path.name} is larger than {MAX_MANIFEST_BYTES} bytes")
    try:
        root = parse(str(path), forbid_dtd=True).getroot()
    except DefusedXmlException as exc:
        raise ManifestError(f"DTDs and entities are not allowed: {exc!r}") from exc
    except ET.ParseError as exc:
        raise ManifestError(f"not well-formed XML: {exc}") from exc
    if root is None or _local(root.tag) != "applicationpackage":
        found = _local(root.tag) if root is not None else "nothing"
        raise ManifestError(f"root element is <{found}>, expected <ApplicationPackage>")

    company = _children(root, "CompanyDetails")
    manifest = BundleManifest(
        attributes=dict(root.attrib),
        company=dict(company[0].attrib) if company else {},
        requirements=_requirements(root, "package"),
    )
    problems: list[str] = []
    for block in _children(root, "Components"):
        block_req = _requirements(block, "components")
        for index, entry in enumerate(_children(block, "ComponentEntry"), start=1):
            module = _get(entry, "ModuleName")
            name = _get(entry, "AppName") or f"component {index}"
            if module is None:
                problems.append(f"<ComponentEntry> '{name}' has no ModuleName")
                continue
            commands = [
                ManifestCommand(global_name=g, local_name=_get(c, "Local"), group=_get(group, "GroupName"))
                for group in _children(entry, "Commands")
                for c in _children(group, "Command")
                if (g := _get(c, "Global")) is not None
            ]
            manifest.components.append(
                Component(
                    app_name=name,
                    module=module,
                    version=_get(entry, "Version"),
                    load_reasons=_load_reasons(entry),
                    commands=commands,
                    requirements=_requirements(entry, "component") or block_req or manifest.requirements,
                )
            )
    if problems:
        raise ManifestError("; ".join(problems))
    if not manifest.components:
        raise ManifestError("no <Components>/<ComponentEntry> elements")
    return manifest


# ---- version ranges ---------------------------------------------------------------------------------------


def series(text: str | None) -> tuple[int, int | None] | None:
    """'R25.1' -> (25, 1); 'R25' -> (25, None) meaning every R25.x; invalid -> None."""
    match = _SERIES.match((text or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)) if match.group(2) is not None else None


def is_guid(text: str | None) -> bool:
    return bool(text and _GUID.match(text.strip()))


def _in_range(internal: str, req: Requirements) -> bool:
    version = series(internal)
    if version is None or version[1] is None:
        return False
    low, high = series(req.series_min), series(req.series_max)
    if low is not None and version < (low[0], low[1] or 0):
        return False
    return not (high is not None and version > (high[0], high[1] if high[1] is not None else 1 << 30))


def component_versions(req: Requirements | None, host: HostConfig) -> list[HostVersion]:
    """Host versions whose series is inside the range; no requirements means every version."""
    if req is None:
        return list(host.versions)
    return [v for v in host.versions if _in_range(v.internal, req)]


def loads_in_plain_host(req: Requirements | None, host: HostConfig) -> bool:
    """False when the component targets only verticals (e.g. Platform="Civil3D")."""
    if req is None or not req.platforms or host.manifest is None:
        return True
    plain = {p.lower() for p in host.manifest.plain_platforms}
    return any(p.lower() in plain for p in req.platforms)
