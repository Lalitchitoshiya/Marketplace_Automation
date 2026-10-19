import subprocess
from pathlib import Path

import pytest

from mta.config import MtaConfig
from mta.intake.kit import KitCheck, app_id_from_name, init_kit, validate_kit
from mta.intake.package import PackageError
from tests.conftest import KitFactory, clean_scanner, infected_scanner, make_msi, make_zip


def _validate(root: Path, cfg: MtaConfig, **kwargs: object) -> KitCheck:
    return validate_kit(root, cfg.thresholds.kit, cfg.thresholds.extract, **kwargs)  # type: ignore[arg-type]


def _errors(check: KitCheck) -> list[str]:
    return [f"{p.path}: {p.message}" for p in check.problems if p.level == "error"]


@pytest.mark.parametrize("package", ["zip", "msi", "bundle"])
def test_complete_kit_is_valid(make_kit: KitFactory, cfg: MtaConfig, package: str) -> None:
    check = _validate(make_kit(package), cfg, scanner=clean_scanner)
    assert check.ok, _errors(check)
    assert check.manifest is not None and check.manifest.app.id == "acme.mytools"
    assert len(check.files["docs"]) == 3
    assert check.problems == []


def test_missing_manifest(make_kit: KitFactory, cfg: MtaConfig) -> None:
    root = make_kit()
    (root / "submission.yaml").unlink()
    assert any("submission.yaml: missing" in e for e in _errors(_validate(root, cfg)))


def test_manifest_schema_errors_are_located(make_kit: KitFactory, cfg: MtaConfig) -> None:
    root = make_kit()
    text = (root / "submission.yaml").read_text(encoding="utf-8")
    (root / "submission.yaml").write_text(
        text.replace("id: acme.mytools", "id: Acme Tools!"), encoding="utf-8"
    )
    errors = _errors(_validate(root, cfg))
    assert any(e.startswith("submission.yaml:app.id") for e in errors)


def test_package_folder_needs_exactly_one_package(make_kit: KitFactory, cfg: MtaConfig) -> None:
    root = make_kit()
    make_msi(root / "package")
    assert any("exactly one" in e for e in _errors(_validate(root, cfg)))


def test_disallowed_file_type_and_unknown_folder(make_kit: KitFactory, cfg: MtaConfig) -> None:
    root = make_kit()
    (root / "docs" / "run-me.exe").write_bytes(b"MZ")
    (root / "notes.txt").write_text("x", encoding="utf-8")
    check = _validate(root, cfg)
    assert any("docs/run-me.exe: file type not allowed" in e for e in _errors(check))
    assert any(p.level == "warning" and p.path == "notes.txt" for p in check.problems)


def test_size_and_count_limits(make_kit: KitFactory, cfg: MtaConfig) -> None:
    root = make_kit()
    kit = cfg.thresholds.kit.model_copy(update={"doc_max_bytes": 10, "screenshot_max_count": 0})
    check = validate_kit(root, kit, cfg.thresholds.extract)
    errors = _errors(check)
    assert any("byte limit for docs/" in e for e in errors)
    assert any("more than 0 screenshots" in e for e in errors)
    tiny = cfg.thresholds.extract.model_copy(update={"max_files": 2})
    assert any("exceed the limit of 2" in e for e in _errors(validate_kit(root, cfg.thresholds.kit, tiny)))


def test_references_must_exist_inside_the_kit(make_kit: KitFactory, cfg: MtaConfig) -> None:
    root = make_kit()
    text = (root / "submission.yaml").read_text(encoding="utf-8")
    text = text.replace("sample: samples/site-plan.dwg", "sample: ../../etc/passwd")
    text = text.replace("media/screenshots/01-ribbon.png", "media/screenshots/missing.png")
    (root / "submission.yaml").write_text(text, encoding="utf-8")
    errors = _errors(_validate(root, cfg))
    assert any("features[0].sample" in e and "outside the kit" in e for e in errors)
    assert any("listing.screenshots[0]" in e and "does not exist" in e for e in errors)


def test_unlisted_document_is_a_warning(make_kit: KitFactory, cfg: MtaConfig) -> None:
    root = make_kit()
    (root / "docs" / "faq.txt").write_text("FAQ", encoding="utf-8")
    check = _validate(root, cfg)
    assert check.ok
    assert any(p.path == "docs/faq.txt" and "not listed" in p.message for p in check.problems)


def test_junctions_are_rejected(make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path) -> None:
    # A directory junction needs no special rights on Windows, so a kit could use one to reach outside.
    root = make_kit()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.dwg").write_text("secret", encoding="utf-8")
    link = root / "samples" / "linked"
    made = subprocess.run(  # noqa: S603
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if made.returncode != 0:
        pytest.skip("could not create a directory junction")
    check = _validate(root, cfg)
    assert any("samples/linked: links are not allowed" in e for e in _errors(check))
    assert all(f.name != "secret.dwg" for f in check.files["samples"])  # never followed


def test_malware_found_is_an_error(make_kit: KitFactory, cfg: MtaConfig) -> None:
    check = _validate(make_kit(), cfg, scanner=infected_scanner)
    assert any("EICAR" in e for e in _errors(check))


def test_init_creates_layout_and_valid_template(tmp_path: Path, cfg: MtaConfig) -> None:
    package = make_zip(tmp_path, "My Tools 2.zip")
    root = init_kit(tmp_path / "kit", package, version="1.2.3")
    assert (root / "package" / "My Tools 2.zip").is_file()
    assert all(
        (root / d).is_dir() for d in ("docs", "media/screenshots", "media/videos", "samples", "scenarios")
    )
    check = _validate(root, cfg)
    assert check.ok, _errors(check)
    assert check.manifest is not None
    assert (check.manifest.app.id, check.manifest.app.version) == ("my-tools-2", "1.2.3")


def test_init_refuses_non_empty_folder_and_bad_package(tmp_path: Path) -> None:
    package = make_zip(tmp_path)
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "x").write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        init_kit(tmp_path / "busy", package)
    (tmp_path / "bad.exe").write_bytes(b"MZ")
    with pytest.raises(PackageError):
        init_kit(tmp_path / "kit2", tmp_path / "bad.exe")


@pytest.mark.parametrize(
    ("name", "expected"),
    [("MyTools.msi", "mytools"), ("Acme Tools v2.zip", "acme-tools-v2"), ("X.bundle", "app-x")],
)
def test_app_id_from_name(name: str, expected: str) -> None:
    assert app_id_from_name(name) == expected
