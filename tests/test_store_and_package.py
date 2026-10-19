from pathlib import Path

import pytest

from mta.intake.package import PackageError, detect_kind, package_sha256, tree_sha256
from mta.intake.store import ArtifactStore, sha256_file
from mta.models import PackageKind
from tests.conftest import make_bundle, make_msi, make_zip


def test_store_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store")
    source = tmp_path / "a.txt"
    source.write_text("hello", encoding="utf-8")
    first = store.put_file(source)
    second = store.put_bytes(b"hello")
    assert first.sha256 == second.sha256 == sha256_file(source)
    assert first.path == store.path_for(first.sha256)
    assert first.path.parent.name == first.sha256[:2]
    assert store.has(first.sha256)
    assert first.ref == f"sha256:{first.sha256}"
    assert len(list((tmp_path / "store" / "objects").rglob("*"))) == 2  # one folder + one object


@pytest.mark.parametrize(
    ("maker", "kind"),
    [(make_zip, PackageKind.ZIP), (make_msi, PackageKind.MSI), (make_bundle, PackageKind.BUNDLE)],
)
def test_detect_kind(tmp_path: Path, maker: object, kind: PackageKind) -> None:
    assert callable(maker)
    assert detect_kind(maker(tmp_path)) is kind


def test_extension_must_match_content(tmp_path: Path) -> None:
    fake = tmp_path / "evil.msi"
    fake.write_bytes(b"PK\x03\x04 actually a zip")
    with pytest.raises(PackageError, match="not an MSI"):
        detect_kind(fake)
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(PackageError, match="unsupported"):
        detect_kind(tmp_path / "notes.txt")
    (tmp_path / "plain").mkdir()
    with pytest.raises(PackageError, match=r"\.bundle"):
        detect_kind(tmp_path / "plain")


def test_tree_hash_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    a = make_bundle(tmp_path / "a")
    b = make_bundle(tmp_path / "b")
    assert tree_sha256(a) == tree_sha256(b)  # same content, different location
    (b / "Contents" / "Acme.dll").write_bytes(b"MZ changed")
    assert tree_sha256(a) != tree_sha256(b)
    assert package_sha256(a, PackageKind.BUNDLE) == tree_sha256(a)
