"""Packaging MTA's own synthetic plugins as Marketplace-style bundles and Input Kits (testing-strategy.md).

Only MTA-owned code is packaged here; these are the known-answer inputs of the corpus (SD-xx, canary).
"""

import shutil
import uuid
from pathlib import Path

import yaml

from mta.adapters.autocad.build import build_for, output_dir
from mta.config import REPO_ROOT, MtaConfig
from mta.intake.kit import init_kit

SYNTHETIC = REPO_ROOT / "dotnet" / "synthetic"


def built_dll(project: str, cfg: MtaConfig, year: int = 2026) -> Path:
    """A synthetic plugin built for `year`'s API major (`build_synthetic`)."""
    return output_dir(SYNTHETIC / project, cfg, year) / f"{project}.dll"


def build_synthetic(project: str, cfg: MtaConfig, year: int = 2026) -> Path:
    build_for(SYNTHETIC / project, cfg, year)
    return built_dll(project, cfg, year)


def make_bundle(
    dlls: list[Path],
    dest: Path,
    *,
    name: str,
    version: str = "1.0.0",
    series: tuple[str, str] = ("R25.0", "R25.1"),
    commands: list[str] | None = None,
    load_on_command: bool = False,
    module: str | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    """`<dest>/<name>.bundle` with PackageContents.xml and Contents/. `module` overrides the ModuleName."""
    bundle = dest / f"{name}.bundle"
    shutil.rmtree(bundle, ignore_errors=True)
    (bundle / "Contents").mkdir(parents=True)
    for dll in dlls:
        shutil.copy2(dll, bundle / "Contents" / dll.name)
    for rel, data in (extra_files or {}).items():
        (bundle / rel).parent.mkdir(parents=True, exist_ok=True)
        (bundle / rel).write_bytes(data)
    module = module or f"./Contents/{dlls[0].name}"
    load = 'LoadOnCommandInvocation="True"' if load_on_command else 'LoadOnAutoCADStartup="True"'
    command_xml = ""
    if commands:
        rows = "".join(f'<Command Global="{c}" Local="{c}" />' for c in commands)
        command_xml = f'<Commands GroupName="{name.upper()}">{rows}</Commands>'
    product_code = str(uuid.uuid5(uuid.NAMESPACE_URL, name)).upper()
    (bundle / "PackageContents.xml").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage SchemaVersion="1.0" AutodeskProduct="AutoCAD" ProductType="Application" Name="{name}"
  AppVersion="{version}" Author="MTA synthetic" ProductCode="{{{product_code}}}">
  <CompanyDetails Name="MTA synthetic" />
  <RuntimeRequirements OS="Win64" Platform="AutoCAD*" SeriesMin="{series[0]}" SeriesMax="{series[1]}" />
  <Components>
    <ComponentEntry AppName="{name}" ModuleName="{module}" {load}>{command_xml}</ComponentEntry>
  </Components>
</ApplicationPackage>
""",
        encoding="utf-8",
    )
    return bundle


def make_kit(package: Path, kits_root: Path, app_id: str, years: list[int], version: str = "1.0.0") -> Path:
    """An Input Kit around the package, declaring AutoCAD `years` (none: the listing declares no versions)."""
    kit = kits_root / app_id
    shutil.rmtree(kit, ignore_errors=True)
    init_kit(kit, package, app_id=app_id, version=version)
    manifest = kit / "submission.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["products"] = [{"host_id": "autocad", "versions": years}] if years else []
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return kit
