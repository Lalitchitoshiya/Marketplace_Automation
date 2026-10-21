"""Safe ZIP extraction against malicious-archive fixtures, and PKG-001...003 per package kind."""

import dataclasses
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from mta import schemas
from mta.config import MtaConfig
from mta.config.models import ExtractThresholds
from mta.intake.pipeline import intake_kit
from mta.intake.store import ArtifactStore, sha256_file
from mta.models import CheckResult, PackageKind, Status
from mta.static import extract as extract_module
from mta.static.extract import (
    ExtractError,
    _check_tree,
    _tree,
    check_member_name,
    extract_package,
    safe_extract_zip,
)
from mta.static.msi import AdminExtractResult
from mta.static.results import ResultSink
from mta.static.stage import run_static_stage
from tests.conftest import OFFLINE_SERVICES, KitFactory, clean_scanner, make_bundle, make_msi, make_zip
from tests.msi_builder import Action, build_msi

PAYLOAD = {
    "Acme.bundle/PackageContents.xml": b"<ApplicationPackage/>",
    "Acme.bundle/Contents/Acme.dll": b"MZ" + bytes(range(256)) * 20,
}


def _zip(path: Path, entries: dict[str, bytes], compression: int = zipfile.ZIP_STORED) -> Path:
    with zipfile.ZipFile(path, "w", compression) as zf:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zf.compression
            zf.writestr(info, data)
    return path


def _limits(cfg: MtaConfig, **update: int) -> ExtractThresholds:
    return cfg.thresholds.extract.model_copy(update=update)


def _get(results: list[CheckResult], check_id: str) -> CheckResult:
    return next(r for r in results if r.check_id == check_id)


def _status(results: list[CheckResult]) -> dict[str, Status]:
    return {r.check_id: r.status for r in results}


# ---- safe_extract_zip ------------------------------------------------------------------------------------


def test_clean_zip_extracts_and_lists_nested_archives(tmp_path: Path, cfg: MtaConfig) -> None:
    archive = _zip(tmp_path / "a.zip", {**PAYLOAD, "Acme.bundle/extras/inner.zip": b"PK\x05\x06" + bytes(18)})
    done = safe_extract_zip(archive, tmp_path / "out", cfg.thresholds.extract)
    assert (tmp_path / "out" / "Acme.bundle" / "Contents" / "Acme.dll").read_bytes() == PAYLOAD[
        "Acme.bundle/Contents/Acme.dll"
    ]
    assert len(done.files) == 3
    assert done.nested_archives == ["Acme.bundle/extras/inner.zip"]


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("../evil.dll", "path traversal"),
        ("a/../../evil.dll", "path traversal"),
        ("/abs/evil.dll", "absolute path"),
        ("C:/Windows/evil.dll", "drive letter"),
        ("readme.txt:hidden", "alternate data stream"),
        ("Contents/CON.txt", "reserved name"),
        ("Contents/aux", "reserved name"),
        ("Contents/evil.dll.", "dot or space"),
        ("Contents/evil ", "dot or space"),
        ("a//b.dll", "empty or '.'"),
        ("./a.dll", "empty or '.'"),
    ],
)
def test_malicious_names_are_rejected(tmp_path: Path, cfg: MtaConfig, name: str, reason: str) -> None:
    archive = _zip(tmp_path / "bad.zip", {"ok.txt": b"ok", name: b"evil"})
    with pytest.raises(ExtractError) as exc:
        safe_extract_zip(archive, tmp_path / "out", cfg.thresholds.extract)
    assert any(reason in p for p in exc.value.problems), exc.value.problems
    assert not (tmp_path / "out").exists()  # nothing written, not even the safe entry
    assert not (tmp_path / "evil.dll").exists()


def test_nul_and_backslash_names() -> None:
    assert check_member_name("a\0b") == "contains a NUL character"
    assert check_member_name("..\\..\\evil.dll") == "path traversal ('..')"
    assert check_member_name("Acme.bundle/Contents/") is None


def test_symlink_entry_is_rejected(tmp_path: Path, cfg: MtaConfig) -> None:
    info = zipfile.ZipInfo("Contents/link")
    info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(tmp_path / "s.zip", "w") as zf:
        zf.writestr(info, "../../Windows/System32")
    with pytest.raises(ExtractError, match="symbolic link"):
        safe_extract_zip(tmp_path / "s.zip", tmp_path / "out", cfg.thresholds.extract)


def test_encrypted_entry_is_rejected(tmp_path: Path, cfg: MtaConfig) -> None:
    data = bytearray(_zip(tmp_path / "e.zip", {"secret.dll": b"x"}).read_bytes())
    # zipfile cannot write encrypted entries, so set the "encrypted" flag bit in both headers directly.
    data[6] |= 0x1
    data[data.index(b"PK") + 8] |= 0x1
    (tmp_path / "e.zip").write_bytes(bytes(data))
    with pytest.raises(ExtractError, match="encrypted"):
        safe_extract_zip(tmp_path / "e.zip", tmp_path / "out", cfg.thresholds.extract)


def test_case_duplicates_and_file_folder_clash(tmp_path: Path, cfg: MtaConfig) -> None:
    archive = _zip(tmp_path / "d.zip", {"A.dll": b"1", "a.dll": b"2", "x": b"3", "X/y.dll": b"4"})
    with pytest.raises(ExtractError) as exc:
        safe_extract_zip(archive, tmp_path / "out", cfg.thresholds.extract)
    problems = "\n".join(exc.value.problems)
    assert "duplicate of A.dll" in problems
    assert "x: a file and a folder have the same name" in problems


def test_zip_bomb_ratio_is_rejected_before_writing(tmp_path: Path, cfg: MtaConfig) -> None:
    archive = _zip(tmp_path / "bomb.zip", {"zeros.bin": bytes(4 << 20)}, compression=zipfile.ZIP_DEFLATED)
    with pytest.raises(ExtractError, match="zip bomb"):
        safe_extract_zip(archive, tmp_path / "out", cfg.thresholds.extract)
    assert not (tmp_path / "out").exists()


def test_count_and_declared_size_limits(tmp_path: Path, cfg: MtaConfig) -> None:
    archive = _zip(tmp_path / "many.zip", {f"f{i}.txt": b"0123456789" for i in range(5)})
    with pytest.raises(ExtractError, match="exceed the limit of 4"):
        safe_extract_zip(archive, tmp_path / "o1", _limits(cfg, max_files=4))
    with pytest.raises(ExtractError, match="declared size 50 bytes"):
        safe_extract_zip(archive, tmp_path / "o2", _limits(cfg, max_bytes=49))


def test_corrupt_archive(tmp_path: Path, cfg: MtaConfig) -> None:
    archive = make_zip(tmp_path)
    data = bytearray(archive.read_bytes())
    data[40:60] = bytes(20)  # damage the first entry's data; CRC check fails while writing
    archive.write_bytes(bytes(data))
    with pytest.raises(ExtractError, match="corrupt or unsupported"):
        safe_extract_zip(archive, tmp_path / "out", cfg.thresholds.extract)
    assert not (tmp_path / "out").exists()  # partial output removed


def test_paths_longer_than_max_path(tmp_path: Path, cfg: MtaConfig) -> None:
    name = "/".join(["d" * 80] * 3) + "/Acme.dll"
    done = safe_extract_zip(
        _zip(tmp_path / "long.zip", {name: b"MZ"}), tmp_path / "out", cfg.thresholds.extract
    )
    assert len(str(done.files[0])) > 260


# ---- extract_package: PKG-001...003 ----------------------------------------------------------------------


def _extract(
    cfg: MtaConfig, package: Path, kind: PackageKind, tmp_path: Path
) -> extract_module.PackageExtraction:
    return extract_package(package, kind, tmp_path / "payload", cfg, work_dir=tmp_path)


def test_bundle_package(tmp_path: Path, cfg: MtaConfig) -> None:
    out = _extract(cfg, make_bundle(tmp_path / "src"), PackageKind.BUNDLE, tmp_path)
    assert _status(out.results) == {"PKG-001": Status.PASS, "PKG-002": Status.PASS, "PKG-003": Status.SKIPPED}
    assert (tmp_path / "payload" / "Acme.bundle" / "PackageContents.xml").is_file()


def test_zip_without_plugin_files_fails_pkg002(tmp_path: Path, cfg: MtaConfig) -> None:
    archive = _zip(tmp_path / "docs.zip", {"readme.txt": b"hi", "img/logo.png": b"png"})
    out = _extract(cfg, archive, PackageKind.ZIP, tmp_path)
    assert _status(out.results)["PKG-002"] is Status.FAIL
    failed = next(r for r in out.results if r.check_id == "PKG-002")
    assert failed.evidence[0].excerpt == "img/logo.png\nreadme.txt"
    assert failed.remediation


def test_loose_plugin_files_count_as_payload(tmp_path: Path, cfg: MtaConfig) -> None:
    out = _extract(
        cfg, _zip(tmp_path / "l.zip", {"Acme.dll": b"MZ", "acme.lsp": b"(defun)"}), PackageKind.ZIP, tmp_path
    )
    assert _status(out.results)["PKG-002"] is Status.PASS


def test_unsafe_zip_fails_pkg001_and_skips_pkg002(tmp_path: Path, cfg: MtaConfig) -> None:
    out = _extract(cfg, _zip(tmp_path / "bad.zip", {"../evil.dll": b"MZ"}), PackageKind.ZIP, tmp_path)
    assert _status(out.results) == {
        "PKG-003": Status.SKIPPED,
        "PKG-001": Status.FAIL,
        "PKG-002": Status.SKIPPED,
    }
    assert out.payload_dir is None
    pkg001 = next(r for r in out.results if r.check_id == "PKG-001")
    assert pkg001.severity.value == "BLOCKER"  # non-provisional safety gate


def test_extracted_tree_with_junction_fails(tmp_path: Path, cfg: MtaConfig) -> None:
    root = tmp_path / "tree"
    (root / "a").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    made = subprocess.run(  # noqa: S603
        ["cmd", "/c", "mklink", "/J", str(root / "link"), str(tmp_path / "outside")],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if made.returncode != 0:
        pytest.skip("could not create a directory junction")
    files, links = _tree(root)
    results = ResultSink(cfg)
    assert not _check_tree(results, root, files, links, cfg.thresholds.extract)
    assert results.items[0].evidence[0].excerpt == "link: links are not allowed"


# ---- MSI -------------------------------------------------------------------------------------------------


def test_real_msi_admin_extraction(tmp_path: Path, cfg: MtaConfig) -> None:
    msi = build_msi(tmp_path / "Acme.msi", PAYLOAD, tmp_path / "work")
    out = _extract(cfg, msi, PackageKind.MSI, tmp_path)
    assert _status(out.results) == {"PKG-003": Status.PASS, "PKG-001": Status.PASS, "PKG-002": Status.PASS}
    for rel, content in PAYLOAD.items():
        assert (tmp_path / "payload" / rel).read_bytes() == content
    assert not (tmp_path / "payload" / "Acme.msi").exists()  # the admin-image copy is not payload
    assert out.msi is not None and out.msi.properties["ProductName"] == "Acme"
    assert (out.msi.file_count, out.msi.custom_actions) == (2, [])
    assert (tmp_path / "msiexec-admin.log").is_file()


def test_msi_custom_action_inventory(tmp_path: Path, cfg: MtaConfig) -> None:
    actions = (
        Action("SetInstallDir", 51, "INSTALLDIR", "[TARGETDIR]", "InstallExecuteSequence"),
        Action("RegisterPlugin", 1, "PluginCA", "Register", "InstallExecuteSequence"),
        Action("InlineScript", 38, None, "MsgBox " + "x" * 300, "InstallExecuteSequence"),
    )
    msi = build_msi(tmp_path / "Acme.msi", PAYLOAD, tmp_path / "work", actions)
    out = _extract(cfg, msi, PackageKind.MSI, tmp_path)
    assert out.msi is not None
    kinds = {a.name: (a.kind, a.executes_code, a.sequences) for a in out.msi.custom_actions}
    assert kinds == {
        "SetInstallDir": ("data", False, ["InstallExecuteSequence"]),
        "RegisterPlugin": ("dll", True, ["InstallExecuteSequence"]),
        "InlineScript": ("vbscript", True, ["InstallExecuteSequence"]),
    }
    assert all(len(a.target or "") <= 200 for a in out.msi.custom_actions)
    # Install-sequence actions do not run in an admin install, so extraction went ahead.
    pkg003 = next(r for r in out.results if r.check_id == "PKG-003")
    assert pkg003.status is Status.PASS and "2 code custom action(s)" in pkg003.message


def test_admin_sequence_code_is_never_run(
    tmp_path: Path, cfg: MtaConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    actions = (Action("Payload", 34, "TARGETDIR", "cmd.exe /c echo pwned", "AdminExecuteSequence"),)
    msi = build_msi(tmp_path / "Acme.msi", PAYLOAD, tmp_path / "work", actions)

    def never(*_: object) -> AdminExtractResult:
        raise AssertionError("msiexec must not be started")

    monkeypatch.setattr(extract_module, "msi_admin_extract", never)
    out = _extract(cfg, msi, PackageKind.MSI, tmp_path)
    assert _status(out.results) == {
        "PKG-003": Status.NEEDS_REVIEW,
        "PKG-001": Status.SKIPPED,
        "PKG-002": Status.SKIPPED,
    }
    review = _get(out.results, "PKG-003")
    assert review.evidence[0].excerpt == "Payload (type 34, exe) in AdminExecuteSequence"


def test_unreadable_msi_fails_pkg003(tmp_path: Path, cfg: MtaConfig) -> None:
    out = _extract(cfg, make_msi(tmp_path), PackageKind.MSI, tmp_path)
    assert _status(out.results) == {
        "PKG-003": Status.FAIL,
        "PKG-001": Status.SKIPPED,
        "PKG-002": Status.SKIPPED,
    }


def test_msi_over_declared_limits_is_not_extracted(tmp_path: Path, cfg: MtaConfig) -> None:
    msi = build_msi(tmp_path / "Acme.msi", PAYLOAD, tmp_path / "work")
    limits = _limits(cfg, max_files=1, max_bytes=10)
    small = dataclasses.replace(cfg, thresholds=cfg.thresholds.model_copy(update={"extract": limits}))
    out = _extract(small, msi, PackageKind.MSI, tmp_path)
    assert _status(out.results)["PKG-001"] is Status.FAIL
    assert "2 files exceed" in (_get(out.results, "PKG-001").evidence[0].excerpt or "")
    assert not (tmp_path / "payload").exists()


@pytest.mark.parametrize(
    ("exit_code", "status", "text"),
    [
        (1618, Status.ERROR, "another installation"),
        (None, Status.ERROR, "timed out"),
        (1603, Status.FAIL, "exit 1603"),
    ],
)
def test_msiexec_outcomes(
    tmp_path: Path,
    cfg: MtaConfig,
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int | None,
    status: Status,
    text: str,
) -> None:
    msi = build_msi(tmp_path / "Acme.msi", PAYLOAD, tmp_path / "work")
    monkeypatch.setattr(
        extract_module, "msi_admin_extract", lambda *_: AdminExtractResult(exit_code, "log tail")
    )
    out = _extract(cfg, msi, PackageKind.MSI, tmp_path)
    pkg003 = _get(out.results, "PKG-003")
    assert (pkg003.check_id, pkg003.status) == ("PKG-003", status)
    assert text in pkg003.message
    assert pkg003.evidence[0].excerpt == "log tail"


# ---- stage after intake ----------------------------------------------------------------------------------


@pytest.mark.parametrize("package", ["zip", "bundle"])
def test_package_stage_writes_job_files(
    make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path, package: str
) -> None:
    data = tmp_path / "data"
    intake = intake_kit(make_kit(package), cfg, data, clean_scanner)
    outcome = run_static_stage(intake, cfg, data, OFFLINE_SERVICES)

    job_dir = intake.job_dir
    assert json.loads((job_dir / "job.json").read_text("utf-8"))["state"] == "STATIC_ANALYSIS"
    results = json.loads((job_dir / "checks" / "static-package.json").read_text("utf-8"))
    assert all(schemas.validate("check-result", r) == [] for r in results)
    assert {r["check_id"]: r["status"] for r in results}["PKG-002"] == "PASS"

    listing = json.loads((job_dir / "payload-files.json").read_text("utf-8"))
    store = ArtifactStore(data / "artifacts")
    assert {f["path"] for f in listing["files"]} == {
        "Acme.bundle/PackageContents.xml",
        "Acme.bundle/Contents/Acme.dll",
    }
    assert all(store.has(f["sha256"]) for f in listing["files"])
    assert outcome.extraction.payload_dir == job_dir / "payload"


def test_package_stage_msi_writes_tables(make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path) -> None:
    kit = make_kit("zip")
    (kit / "package" / "Acme.zip").unlink()
    build_msi(kit / "package" / "Acme.msi", PAYLOAD, tmp_path / "work")
    data = tmp_path / "data"
    intake = intake_kit(kit, cfg, data, clean_scanner)
    run_static_stage(intake, cfg, data, OFFLINE_SERVICES)
    tables = json.loads((intake.job_dir / "msi-tables.json").read_text("utf-8"))
    assert tables["properties"]["ProductName"] == "Acme"
    dll = intake.job_dir / "payload" / "Acme.bundle" / "Contents" / "Acme.dll"
    assert sha256_file(dll) == next(
        f["sha256"]
        for f in json.loads((intake.job_dir / "payload-files.json").read_text("utf-8"))["files"]
        if f["path"].endswith("Acme.dll")
    )
