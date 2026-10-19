import json
from pathlib import Path

import pytest

from mta import schemas
from mta.config import MtaConfig
from mta.intake.pipeline import IntakeError, intake_kit, intake_package
from mta.intake.store import ArtifactStore, sha256_file
from mta.models import PackageKind
from tests.conftest import KitFactory, clean_scanner, infected_scanner, make_bundle


def test_intake_kit_end_to_end(make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path) -> None:
    kit = make_kit("zip")
    data = tmp_path / "data"
    result = intake_kit(kit, cfg, data, clean_scanner)

    sub = result.submission
    assert sub.app_id == "acme.mytools" and sub.app_version == "2.3.0"
    assert sub.package.kind is PackageKind.ZIP
    assert sub.package.sha256 == sha256_file(kit / "package" / "Acme.zip")
    assert sub.listing is not None and sub.listing.description == "MyTools adds dimensions.\n"
    assert sub.products[0].versions == [2025, 2026]
    assert {d.kind.value for d in sub.documents} == {"user_guide", "quick_start", "listing_description"}
    assert sub.reviewer_inputs.scenarios == ["scenarios/dimall.yaml"]
    assert result.job.config_snapshot_sha256 == cfg.sha256

    # Every stored artifact is retrievable by hash (P1-R02).
    store = ArtifactStore(data / "artifacts")
    assert all(store.has(a.sha256) for a in result.artifacts)
    assert {a.path for a in result.artifacts} >= {"Acme.zip", "docs/user-guide.docx", "samples/site-plan.dwg"}

    # Job folder contents validate against the committed schemas.
    job_dir = result.job_dir
    assert schemas.validate("submission", json.loads((job_dir / "submission.json").read_text("utf-8"))) == []
    assert schemas.validate("job", json.loads((job_dir / "job.json").read_text("utf-8"))) == []
    assert (job_dir / "docs-text" / "user-guide.docx.txt").read_text("utf-8").startswith("Getting started")
    assert json.loads((job_dir / "malware-scan.json").read_text("utf-8"))["outcome"] == "clean"

    # Commands mentioned in the user guide (docx) and quick start (pdf) are indexed.
    mentions = json.loads((job_dir / "command-mentions.json").read_text("utf-8"))
    assert {"ACME_DIMALL", "ACME_EXPORTCSV"} <= set(mentions)


def test_intake_bundle_stores_every_file_and_tree(
    make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path
) -> None:
    result = intake_kit(make_kit("bundle"), cfg, tmp_path / "data", clean_scanner)
    paths = {a.path for a in result.artifacts}
    assert {"package/PackageContents.xml", "package/Contents/Acme.dll", "package-tree.json"} <= paths


def test_intake_rejects_infected_kit(make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path) -> None:
    with pytest.raises(IntakeError) as exc:
        intake_kit(make_kit(), cfg, tmp_path / "data", infected_scanner)
    assert any("EICAR" in p.message for p in exc.value.check.problems)
    assert not (tmp_path / "data" / "jobs").exists()  # nothing stored from an infected kit


def test_unreadable_document_is_a_warning_not_a_failure(
    make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path
) -> None:
    kit = make_kit()
    (kit / "docs" / "quick-start.pdf").write_bytes(b"corrupted")
    result = intake_kit(kit, cfg, tmp_path / "data", clean_scanner)
    assert any("text extraction failed" in w.message for w in result.warnings)
    assert "ACME_DIMALL" in result.mentions  # the other documents were still indexed


def test_intake_bare_package_builds_minimal_kit(cfg: MtaConfig, tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path / "src", "MyPlugin.bundle")
    result = intake_package(bundle, cfg, tmp_path / "data", clean_scanner)
    assert result.submission.app_id == "myplugin"
    assert result.submission.app_version == "unknown"
    assert result.submission.listing is None
    assert result.submission.package.kind is PackageKind.BUNDLE
