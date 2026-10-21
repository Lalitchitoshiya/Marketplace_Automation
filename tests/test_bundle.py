"""Bundle locating, safe manifest parsing and rules PKG-004...006, MAN-001...007 (step 8)."""

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mta.cli.app import app
from mta.config import MtaConfig
from mta.intake.kit import init_kit, validate_kit
from mta.intake.pipeline import intake_kit
from mta.intake.prefill import prefill_from_package
from mta.models import PackageKind, ProductDecl, Status, Submission
from mta.models.submission import PackageRef
from mta.static.bundle import (
    ManifestError,
    find_bundles,
    loads_in_plain_host,
    parse_package_contents,
    series,
)
from mta.static.bundle_checks import BundleAnalysis, analyze_bundle, normalize_version
from mta.static.stage import run_static_stage
from tests.conftest import (
    OFFLINE_SERVICES,
    PACKAGE_CONTENTS,
    KitFactory,
    clean_scanner,
    make_bundle,
    make_msi,
    make_zip,
)
from tests.msi_builder import build_msi

GUID = "{6B1B5E2A-3C1D-4E0B-9F3A-0A1B2C3D4E5F}"

# Two component blocks: the first inherits the Components-level range, the second has its own (P1-R05).
GOOD = f"""<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage SchemaVersion="1.0" AutodeskProduct="AutoCAD" ProductType="Application" Name="Acme Tools"
  AppVersion="2.3.0" ProductCode="{GUID}">
  <CompanyDetails Name="Acme Ltd" />
  <RuntimeRequirements OS="Win64" Platform="AutoCAD*" SeriesMin="R24.0" SeriesMax="R26.0" />
  <Components>
    <RuntimeRequirements OS="Win64" Platform="AutoCAD*" SeriesMin="R25.0" SeriesMax="R25" />
    <ComponentEntry AppName="AcmeNet" ModuleName="./Contents/Acme.dll">
      <LoadReasons><LoadOnCommandInvocation /><LoadOnAutoCADStartup /></LoadReasons>
      <Commands GroupName="ACME"><Command Global="ACME_DIMALL" Local="ACME_DIMALL" /></Commands>
    </ComponentEntry>
    <ComponentEntry AppName="AcmeLegacy" ModuleName=".\\Contents\\Legacy\\Acme24.dll">
      <RuntimeRequirements OS="Win64" Platform="AutoCAD" SeriesMin="R24.0" SeriesMax="R24.3" />
    </ComponentEntry>
  </Components>
</ApplicationPackage>
"""


def _payload(tmp_path: Path, manifest: str = GOOD, extra: dict[str, bytes] | None = None) -> Path:
    payload = tmp_path / "payload"
    bundle = payload / "Acme.bundle"
    (bundle / "Contents" / "Legacy").mkdir(parents=True)
    (bundle / "PackageContents.xml").write_text(manifest, encoding="utf-8")
    (bundle / "Contents" / "Acme.dll").write_bytes(b"MZ")
    (bundle / "Contents" / "Legacy" / "Acme24.dll").write_bytes(b"MZ")
    for rel, data in (extra or {}).items():
        (payload / rel).parent.mkdir(parents=True, exist_ok=True)
        (payload / rel).write_bytes(data)
    return payload


def _submission(version: str = "2.3.0", years: list[int] | None = None) -> Submission:
    return Submission(
        submission_id="sub-1",
        app_id="acme.tools",
        app_version=version,
        package=PackageRef(filename="Acme.zip", sha256="0" * 64, size_bytes=1, kind=PackageKind.ZIP),
        products=[ProductDecl(host_id="autocad", versions=years)] if years else [],
        received_at=datetime.now(UTC),
    )


def _analyze(
    cfg: MtaConfig, payload: Path, submission: Submission | None = None, msi_version: str | None = None
) -> BundleAnalysis:
    files = sorted(p for p in payload.rglob("*") if p.is_file())
    return analyze_bundle(
        payload, files, submission or _submission(years=[2025, 2026]), cfg, msi_version=msi_version
    )


def _status(analysis: BundleAnalysis) -> dict[str, Status]:
    return {r.check_id: r.status for r in analysis.results}


def _evidence(analysis: BundleAnalysis, check_id: str) -> str:
    result = next(r for r in analysis.results if r.check_id == check_id)
    return "\n".join(e.excerpt or "" for e in result.evidence) + result.message


# ---- the good case ---------------------------------------------------------------------------------------


def test_good_bundle_passes_everything(tmp_path: Path, cfg: MtaConfig) -> None:
    analysis = _analyze(cfg, _payload(tmp_path))
    statuses = _status(analysis)
    assert set(statuses.values()) == {Status.PASS}, analysis.results
    assert set(statuses) == {f"PKG-00{i}" for i in (4, 5, 6)} | {f"MAN-00{i}" for i in (1, 2, 3, 4, 6, 7)}


def test_per_component_requirements_win(tmp_path: Path, cfg: MtaConfig) -> None:
    components = {c.app_name: c for c in _analyze(cfg, _payload(tmp_path)).components}
    net, legacy = components["AcmeNet"], components["AcmeLegacy"]
    assert (net.requirements_level, net.host_versions) == ("components", [2025, 2026])  # R25 = all R25.x
    assert (legacy.requirements_level, legacy.host_versions) == ("component", [2024])
    assert net.load_reasons == ["loadoncommandinvocation", "loadonautocadstartup"]
    assert net.commands == ["ACME_DIMALL"]
    assert legacy.path == "Acme.bundle/Contents/Legacy/Acme24.dll" and legacy.exists  # backslashes accepted


def test_case_insensitive_names(tmp_path: Path, cfg: MtaConfig) -> None:
    manifest = GOOD.replace("<ComponentEntry AppName", "<componententry appname").replace(
        "</ComponentEntry>", "</componententry>"
    )
    manifest = manifest.replace("ModuleName=", "modulename=")
    bundle = _payload(tmp_path, manifest) / "Acme.bundle"
    (bundle / "PackageContents.xml").rename(bundle / "packagecontents.XML")
    assert _status(_analyze(cfg, bundle.parent))["MAN-001"] is Status.PASS


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("R25.1", (25, 1)),
        ("r24", (24, None)),
        (" R26.0 ", (26, 0)),
        ("25.0", None),
        (None, None),
        ("R2x", None),
    ],
)
def test_series(text: str | None, expected: tuple[int, int | None] | None) -> None:
    assert series(text) == expected


def test_vertical_only_component_does_not_load_in_plain_autocad(tmp_path: Path, cfg: MtaConfig) -> None:
    manifest = GOOD.replace(
        'Platform="AutoCAD" SeriesMin="R24.0"', 'Platform="Civil3D|Map" SeriesMin="R24.0"'
    )
    components = {c.app_name: c for c in _analyze(cfg, _payload(tmp_path, manifest)).components}
    assert components["AcmeNet"].loads_in_plain_host
    assert not components["AcmeLegacy"].loads_in_plain_host
    assert loads_in_plain_host(None, cfg.hosts.hosts["autocad"])


def test_no_requirements_means_every_version(tmp_path: Path, cfg: MtaConfig) -> None:
    manifest = PACKAGE_CONTENTS.replace(
        '<RuntimeRequirements OS="Win64" Platform="AutoCAD*" SeriesMin="R25.0" SeriesMax="R25.1" />', ""
    )
    payload = tmp_path / "p"
    make_bundle(payload)
    (payload / "Acme.bundle" / "PackageContents.xml").write_text(manifest, encoding="utf-8")
    analysis = _analyze(cfg, payload)
    assert analysis.components[0].host_versions == [2024, 2025, 2026, 2027]
    assert analysis.components[0].requirements_level is None


# ---- PKG-004 ---------------------------------------------------------------------------------------------


def test_no_bundle(tmp_path: Path, cfg: MtaConfig) -> None:
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "Acme.dll").write_bytes(b"MZ")
    analysis = _analyze(cfg, tmp_path / "p")
    assert _status(analysis)["PKG-004"] is Status.FAIL
    assert _status(analysis)["MAN-001"] is Status.SKIPPED
    assert _status(analysis)["PKG-006"] is Status.SKIPPED  # nothing declares a version


def test_two_bundles(tmp_path: Path, cfg: MtaConfig) -> None:
    payload = _payload(tmp_path)
    make_bundle(payload / "other", "Second.bundle")
    analysis = _analyze(cfg, payload)
    assert _status(analysis)["PKG-004"] is Status.FAIL
    assert "Acme.bundle\nother/Second.bundle" in _evidence(analysis, "PKG-004")


def test_bundle_inside_bundle_is_one_bundle(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    (payload / "Acme.bundle" / "Contents" / "Help.bundle").mkdir()
    assert find_bundles(payload) == [payload / "Acme.bundle"]


def test_bundle_without_manifest(tmp_path: Path, cfg: MtaConfig) -> None:
    payload = _payload(tmp_path)
    (payload / "Acme.bundle" / "PackageContents.xml").unlink()
    assert _status(_analyze(cfg, payload))["PKG-004"] is Status.FAIL


# ---- MAN-001 ---------------------------------------------------------------------------------------------

BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
<ApplicationPackage Name="&lol2;"/>"""
EXTERNAL_ENTITY = """<?xml version="1.0"?>
<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///C:/Windows/win.ini">]>
<ApplicationPackage Name="&xxe;"/>"""


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ("<ApplicationPackage><Components>", "not well-formed"),
        (BILLION_LAUGHS, "DTDs and entities are not allowed"),
        (EXTERNAL_ENTITY, "DTDs and entities are not allowed"),
        ("<Package><Components/></Package>", "expected <ApplicationPackage>"),
        ("<ApplicationPackage><Components/></ApplicationPackage>", "no <Components>/<ComponentEntry>"),
        (
            '<ApplicationPackage><Components><ComponentEntry AppName="X"/></Components></ApplicationPackage>',
            "'X' has no ModuleName",
        ),
    ],
)
def test_broken_manifests_fail_man001(tmp_path: Path, cfg: MtaConfig, manifest: str, message: str) -> None:
    analysis = _analyze(cfg, _payload(tmp_path, manifest))
    statuses = _status(analysis)
    assert statuses["MAN-001"] is Status.FAIL
    assert message in _evidence(analysis, "MAN-001")
    assert all(statuses[c] is Status.SKIPPED for c in ("MAN-002", "MAN-003", "MAN-004", "MAN-006", "MAN-007"))


def test_oversized_manifest(tmp_path: Path) -> None:
    path = tmp_path / "PackageContents.xml"
    path.write_text("<ApplicationPackage>" + " " * (1 << 20) + "</ApplicationPackage>", encoding="utf-8")
    with pytest.raises(ManifestError, match="larger than"):
        parse_package_contents(path)


# ---- MAN-002...007 ---------------------------------------------------------------------------------------


def test_man002_missing_metadata(tmp_path: Path, cfg: MtaConfig) -> None:
    manifest = GOOD.replace(GUID, "not-a-guid").replace('AppVersion="2.3.0" ', "")
    manifest = manifest.replace('<CompanyDetails Name="Acme Ltd" />', "")
    analysis = _analyze(cfg, _payload(tmp_path, manifest))
    evidence = _evidence(analysis, "MAN-002")
    assert _status(analysis)["MAN-002"] is Status.FAIL
    assert "ProductCode is not a GUID" in evidence
    assert "AppVersion missing" in evidence
    assert "Author / CompanyDetails Name missing" in evidence


def test_man003_uncovered_declared_version(tmp_path: Path, cfg: MtaConfig) -> None:
    analysis = _analyze(cfg, _payload(tmp_path), _submission(years=[2024, 2026, 2027]))
    assert _status(analysis)["MAN-003"] is Status.FAIL
    assert "[2027]" in _evidence(analysis, "MAN-003")
    assert _status(_analyze(cfg, _payload(tmp_path / "b"), _submission()))["MAN-003"] is Status.SKIPPED


def test_man004_missing_and_escaping_modules(tmp_path: Path, cfg: MtaConfig) -> None:
    manifest = GOOD.replace("./Contents/Acme.dll", "./Contents/Missing.dll").replace(
        ".\\Contents\\Legacy\\Acme24.dll", "../../Windows/evil.dll"
    )
    analysis = _analyze(cfg, _payload(tmp_path, manifest))
    evidence = _evidence(analysis, "MAN-004")
    assert _status(analysis)["MAN-004"] is Status.FAIL
    assert "AcmeNet: ./Contents/Missing.dll not found" in evidence
    assert "AcmeLegacy: ../../Windows/evil.dll escapes the bundle" in evidence


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('AutodeskProduct="AutoCAD"', 'AutodeskProduct="Revit"', "AutodeskProduct='Revit'"),
        ('ProductType="Application"', 'ProductType="Plugin"', "ProductType='Plugin'"),
        ('OS="Win64" Platform="AutoCAD" ', 'OS="Win32" Platform="AutoCAD" ', "does not include Win64"),
        ('OS="Win64" Platform="AutoCAD" ', 'OS="Linux" Platform="AutoCAD" ', "invalid OS ['Linux']"),
        ('SeriesMax="R24.3"', 'SeriesMax="2024"', "SeriesMax='2024' is not like 'R25.0'"),
    ],
)
def test_man006_invalid_values(tmp_path: Path, cfg: MtaConfig, old: str, new: str, message: str) -> None:
    assert old in GOOD
    analysis = _analyze(cfg, _payload(tmp_path, GOOD.replace(old, new)))
    assert _status(analysis)["MAN-006"] is Status.FAIL
    assert message in _evidence(analysis, "MAN-006")


def test_man006_unknown_platform_is_a_warning(tmp_path: Path, cfg: MtaConfig) -> None:
    analysis = _analyze(cfg, _payload(tmp_path, GOOD.replace('Platform="AutoCAD" ', 'Platform="AcmeCAD" ')))
    assert _status(analysis)["MAN-006"] is Status.WARN
    assert "AcmeCAD" in _evidence(analysis, "MAN-006")


def test_man007_orphan_component(tmp_path: Path, cfg: MtaConfig) -> None:
    manifest = GOOD.replace('SeriesMin="R24.0" SeriesMax="R24.3"', 'SeriesMin="R30.0" SeriesMax="R31"')
    analysis = _analyze(cfg, _payload(tmp_path, manifest))
    assert _status(analysis)["MAN-007"] is Status.FAIL
    assert "AcmeLegacy: range R30.0..R31" in _evidence(analysis, "MAN-007")


# ---- PKG-005 / PKG-006 -----------------------------------------------------------------------------------


def test_pkg005_undeclared_scripts(tmp_path: Path, cfg: MtaConfig) -> None:
    payload = _payload(tmp_path, extra={"Acme.bundle/Contents/setup.ps1": b"", "tools/fix.BAT": b""})
    analysis = _analyze(cfg, payload)
    assert _status(analysis)["PKG-005"] is Status.WARN
    assert "Acme.bundle/Contents/setup.ps1\ntools/fix.BAT" in _evidence(analysis, "PKG-005")


def test_pkg005_declared_javascript_component_is_fine(tmp_path: Path, cfg: MtaConfig) -> None:
    manifest = GOOD.replace(".\\Contents\\Legacy\\Acme24.dll", "./Contents/acme.js")
    payload = _payload(tmp_path, manifest, extra={"Acme.bundle/Contents/acme.js": b"//"})
    assert _status(_analyze(cfg, payload))["PKG-005"] is Status.PASS


@pytest.mark.parametrize(("a", "b"), [("v2.3", "2.3.0"), ("2.3.0.0", "2.3"), ("1.10", "1.10.0")])
def test_normalize_version_equal(a: str, b: str) -> None:
    assert normalize_version(a) == normalize_version(b)


def test_pkg006_version_checks(tmp_path: Path, cfg: MtaConfig) -> None:
    payload = _payload(tmp_path)
    assert _status(_analyze(cfg, payload, _submission("v2.3")))["PKG-006"] is Status.PASS
    mismatch = _analyze(cfg, payload, _submission("2.4.0"))
    assert _status(mismatch)["PKG-006"] is Status.FAIL
    assert "manifest AppVersion = '2.3.0', listing = '2.4.0'" in _evidence(mismatch, "PKG-006")
    msi = _analyze(cfg, payload, _submission("2.3.0"), msi_version="2.2.9")
    assert "MSI ProductVersion = '2.2.9'" in _evidence(msi, "PKG-006")
    assert _status(_analyze(cfg, payload, _submission("unknown")))["PKG-006"] is Status.SKIPPED


# ---- stage and kit pre-fill ------------------------------------------------------------------------------


def test_stage_writes_bundle_json(make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path) -> None:
    data = tmp_path / "data"
    intake = intake_kit(make_kit("zip"), cfg, data, clean_scanner)
    outcome = run_static_stage(intake, cfg, data, OFFLINE_SERVICES)
    assert outcome.bundle is not None
    bundle = json.loads((intake.job_dir / "bundle.json").read_text("utf-8"))
    assert bundle["bundle"] == "Acme.bundle"
    assert bundle["components"][0]["host_versions"] == [2025, 2026]
    statuses = {r.check_id: r.status for r in outcome.results}
    assert statuses["MAN-003"] is Status.PASS and statuses["PKG-006"] is Status.PASS
    assert (intake.job_dir / "checks" / "static-manifest.json").is_file()


@pytest.mark.parametrize("kind", ["bundle", "zip"])
def test_prefill_from_manifest(tmp_path: Path, cfg: MtaConfig, kind: str) -> None:
    package = make_bundle(tmp_path) if kind == "bundle" else make_zip(tmp_path)
    found = prefill_from_package(package, cfg)
    assert (found.version, found.title, found.publisher) == ("2.3.0", "Acme", "Acme Ltd")
    assert found.products == [ProductDecl(host_id="autocad", versions=[2025, 2026])]
    assert found.commands == ["ACME_DIMALL", "ACME_EXPORTCSV"]


def test_prefill_from_msi_uses_tables_only(tmp_path: Path, cfg: MtaConfig) -> None:
    msi = build_msi(tmp_path / "Acme.msi", {"Acme.bundle/PackageContents.xml": b"<x/>"}, tmp_path / "w")
    found = prefill_from_package(msi, cfg)
    assert (found.version, found.title, found.publisher) == ("1.0.0", "Acme", "MTA synthetic")
    assert found.products == [] and "after the scan" in found.notes[0]
    assert "not a readable MSI" in prefill_from_package(make_msi(tmp_path, "Bad.msi"), cfg).notes[0]


def test_prefill_problems_become_notes(tmp_path: Path, cfg: MtaConfig) -> None:
    with zipfile.ZipFile(tmp_path / "evil.zip", "w") as zf:
        zf.writestr("../evil.dll", "MZ")
    assert "ZIP not extracted" in prefill_from_package(tmp_path / "evil.zip", cfg).notes[0]
    with zipfile.ZipFile(tmp_path / "loose.zip", "w") as zf:
        zf.writestr("Acme.dll", "MZ")
    assert "found 0" in prefill_from_package(tmp_path / "loose.zip", cfg).notes[0]
    bundle = make_bundle(tmp_path / "x")
    (bundle / "PackageContents.xml").write_text("<broken", encoding="utf-8")
    assert "PackageContents.xml" in prefill_from_package(bundle, cfg).notes[0]
    (bundle / "PackageContents.xml").unlink()
    assert "has no PackageContents.xml" in prefill_from_package(bundle, cfg).notes[0]


def test_prefilled_kit_is_valid(tmp_path: Path, cfg: MtaConfig) -> None:
    package = make_zip(tmp_path)
    root = init_kit(tmp_path / "kit", package, prefill=prefill_from_package(package, cfg))
    check = validate_kit(root, cfg.thresholds.kit, cfg.thresholds.extract)
    assert check.ok, check.problems
    assert check.manifest is not None
    assert check.manifest.app.version == "2.3.0"
    assert check.manifest.app.title == "Acme" and check.manifest.app.publisher == "Acme Ltd"
    assert check.manifest.products == [ProductDecl(host_id="autocad", versions=[2025, 2026])]
    text = (root / "submission.yaml").read_text("utf-8")
    assert "# Commands found in the package: ACME_DIMALL, ACME_EXPORTCSV" in text
    explicit = init_kit(tmp_path / "kit2", package, version="9.9", prefill=prefill_from_package(package, cfg))
    assert 'version: "9.9"' in (explicit / "submission.yaml").read_text("utf-8")  # explicit wins


def test_cli_kit_init_reports_detected_values(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["kit", "init", str(tmp_path / "kit"), "--package", str(make_zip(tmp_path))]
    )
    assert result.exit_code == 0, result.output
    assert "detected version: 2.3.0" in result.output
    assert "detected autocad versions: [2025, 2026]" in result.output
    assert "detected commands: ACME_DIMALL, ACME_EXPORTCSV" in result.output
