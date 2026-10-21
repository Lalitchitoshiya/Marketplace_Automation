"""Shared fixtures: config, synthetic packages, documents and Input Kits."""

import functools
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path

import docx
import pytest

from mta.config import REPO_ROOT, MtaConfig, load_config
from mta.static.dotnet import AssemblyReport, ObfuscationInfo
from mta.static.malware import ScanOutcome, ScanResult
from mta.static.signing import SignatureInfo
from mta.static.stage import StaticServices

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")

PACKAGE_CONTENTS = """<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage SchemaVersion="1.0" AutodeskProduct="AutoCAD" ProductType="Application" Name="Acme"
  AppVersion="2.3.0" Author="Acme Ltd" ProductCode="{6B1B5E2A-3C1D-4E0B-9F3A-0A1B2C3D4E5F}">
  <CompanyDetails Name="Acme Ltd" Email="support@acme.example" />
  <RuntimeRequirements OS="Win64" Platform="AutoCAD*" SeriesMin="R25.0" SeriesMax="R25.1" />
  <Components>
    <ComponentEntry AppName="Acme" ModuleName="./Contents/Acme.dll" LoadOnCommandInvocation="True">
      <Commands GroupName="ACME">
        <Command Global="ACME_DIMALL" Local="ACME_DIMALL" />
        <Command Global="ACME_EXPORTCSV" Local="ACME_EXPORTCSV" />
      </Commands>
    </ComponentEntry>
  </Components>
</ApplicationPackage>
"""


@pytest.fixture(scope="session")
def cfg() -> MtaConfig:
    return load_config(REPO_ROOT / "config")


def make_bundle(parent: Path, name: str = "Acme.bundle") -> Path:
    bundle = parent / name
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "PackageContents.xml").write_text(PACKAGE_CONTENTS, encoding="utf-8")
    (bundle / "Contents" / "Acme.dll").write_bytes(b"MZ fake dll")
    return bundle


def make_zip(parent: Path, name: str = "Acme.zip") -> Path:
    path = parent / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Acme.bundle/PackageContents.xml", PACKAGE_CONTENTS)
        zf.writestr("Acme.bundle/Contents/Acme.dll", b"MZ fake dll")
    return path


def make_msi(parent: Path, name: str = "Acme.msi") -> Path:
    path = parent / name
    path.write_bytes(OLE_MAGIC + b"\x00" * 504)
    return path


def make_docx(path: Path, paragraphs: list[str]) -> Path:
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(str(path))
    return path


def make_pdf(path: Path, text: str) -> Path:
    """A minimal one-page PDF with real text content and a correct xref table."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj".encode() + body + b"endobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


SUBMISSION_YAML = """\
kit_version: 1
app:
  id: acme.mytools
  version: "2.3.0"
  title: MyTools for AutoCAD
  publisher: Acme Ltd
  pricing: paid
products:
  - host_id: autocad
    versions: [2025, 2026]
listing:
  short_description: Automatic dimensioning.
  description_file: docs/listing-description.md
  support_email: support@acme.example
  privacy_policy_url: https://acme.example/privacy
  external_domains: [api.acme.example]
  screenshots: [media/screenshots/01-ribbon.png]
documents:
  - path: docs/user-guide.docx
    kind: user_guide
  - path: docs/quick-start.pdf
    kind: quick_start
  - path: docs/listing-description.md
    kind: listing_description
features:
  - id: F1
    name: Dimension all lines
    commands: [ACME_DIMALL]
    sample: samples/site-plan.dwg
    expected: Every line gets a dimension
"""

KitFactory = Callable[..., Path]


@pytest.fixture
def make_kit(tmp_path: Path) -> KitFactory:
    """Build a complete, valid kit; `package` chooses msi / zip / bundle."""

    def factory(package: str = "zip", name: str = "kit") -> Path:
        root = tmp_path / name
        for folder in ("package", "docs", "media/screenshots", "samples", "scenarios"):
            (root / folder).mkdir(parents=True)
        {"zip": make_zip, "msi": make_msi, "bundle": make_bundle}[package](root / "package")
        (root / "submission.yaml").write_text(SUBMISSION_YAML, encoding="utf-8")
        (root / "docs" / "listing-description.md").write_text("MyTools adds dimensions.\n", encoding="utf-8")
        make_docx(root / "docs" / "user-guide.docx", ["Getting started", "Type ACME_DIMALL and press Enter."])
        make_pdf(root / "docs" / "quick-start.pdf", "Run ACME_EXPORTCSV to export dimensions")
        (root / "media" / "screenshots" / "01-ribbon.png").write_bytes(b"\x89PNG fake")
        (root / "samples" / "site-plan.dwg").write_bytes(b"AC1032 fake drawing")
        (root / "scenarios" / "dimall.yaml").write_text("scenario: acme.mytools/dimall\n", encoding="utf-8")
        return root

    return factory


def clean_scanner(_: Path) -> ScanResult:
    return ScanResult(ScanOutcome.CLEAN, 0, "found no threats")


def infected_scanner(_: Path) -> ScanResult:
    return ScanResult(
        ScanOutcome.THREATS, 2, "Threat : Virus:DOS/EICAR_Test_File", ["Virus:DOS/EICAR_Test_File"]
    )


# ---- .NET fixtures (dotnet/tests/fixtures, see README there) ----------------------------------------------

DOTNET = REPO_ROOT / "dotnet"
NET_FIXTURES = {
    "plugin": DOTNET / "tests/fixtures/FixturePlugin/bin/Release/net8.0/FixturePlugin.dll",
    "fake_accoremgd": DOTNET / "tests/fixtures/FixturePlugin/bin/Release/net8.0/AcCoreMgd.dll",
    "net48": DOTNET / "tests/fixtures/FixtureNet48/bin/Release/net48/FixtureNet48.dll",
    "inspect": DOTNET / "src/MtaInspect/bin/Release/net8.0/mta-inspect.exe",
}


@pytest.fixture(scope="session")
def net_fixtures() -> dict[str, Path]:
    """Build mta-inspect and the fixture assemblies once if needed; skip when the .NET SDK is missing."""
    if not all(p.is_file() for p in NET_FIXTURES.values()):
        for project in ("src/MtaInspect", "tests/fixtures/FixturePlugin", "tests/fixtures/FixtureNet48"):
            try:
                done = subprocess.run(  # noqa: S603
                    ["dotnet", "build", str(DOTNET / project), "-c", "Release"],  # noqa: S607
                    capture_output=True,
                    check=False,
                    timeout=600,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                pytest.skip(f"cannot build .NET fixtures: {exc}")
            if done.returncode != 0:
                pytest.skip(f"cannot build {project}: {done.stdout.decode(errors='replace')[-500:]}")
    return NET_FIXTURES


# ---- offline services for the static stage (no Defender, PowerShell or network) -------------------------


def unsigned_signatures(files: list[Path], _timeout: int) -> list[SignatureInfo]:
    return [
        SignatureInfo(str(f), "NotSigned", "not signed", "None", None, None, None, None, False) for f in files
    ]


def fake_open_url(url: str, _timeout: int) -> tuple[int, str | None]:
    return 200, None


def fake_resolve(name: str, rdtype: str, _timeout: int) -> list[str]:
    return [f"10 mail.{name}."]


def not_pe_inspect(files: list[Path]) -> list[AssemblyReport]:
    """The conftest DLLs are fakes ("MZ fake dll"): report them as mta-inspect would, without the process."""
    return [
        AssemblyReport(
            path=str(f),
            is_managed=False,
            machine="UNKNOWN",
            architecture="unknown",
            mixed_mode=False,
            assembly_name=None,
            assembly_version=None,
            target_framework=None,
            obfuscation=ObfuscationInfo(suspected=False, signals=[]),
            error="BadImageFormatException: not a PE",
        )
        for f in files
    ]


OFFLINE_SERVICES = StaticServices(
    scanner=clean_scanner,
    signatures=unsigned_signatures,
    open_url=fake_open_url,
    resolve=fake_resolve,
    inspect=not_pe_inspect,
)


@pytest.fixture
def offline_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI commands use the offline fakes for signatures and network (the scanner still follows --no-scan),
    and `mta run` gets an empty dynamic stage: unit tests never start AutoCAD."""
    from mta.adapters.autocad.dynamic import DynamicOutcome
    from mta.cli import kit_cmds

    monkeypatch.setattr(kit_cmds, "run_dynamic_stage", lambda *a, **k: DynamicOutcome())

    monkeypatch.setattr(
        kit_cmds,
        "StaticServices",
        functools.partial(
            StaticServices,
            signatures=unsigned_signatures,
            open_url=fake_open_url,
            resolve=fake_resolve,
            inspect=not_pe_inspect,
        ),
    )
