"""Package identification and hashing. Reads bytes only; never executes or extracts anything."""

import hashlib
from pathlib import Path

from mta.intake.store import sha256_file
from mta.models import PackageKind

_OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")  # MSI files are OLE compound documents
_ZIP_MAGIC = b"PK\x03\x04"
_ZIP_EMPTY_MAGIC = b"PK\x05\x06"


class PackageError(Exception):
    """The path is not a package MTA understands."""


def detect_kind(path: Path) -> PackageKind:
    """Identify by structure and magic bytes, not just the extension."""
    if path.is_dir():
        if path.suffix.lower() == ".bundle":
            return PackageKind.BUNDLE
        raise PackageError(f"{path.name}: a folder package must be a '*.bundle' folder")
    with path.open("rb") as handle:
        head = handle.read(8)
    suffix = path.suffix.lower()
    if suffix == ".msi":
        if head != _OLE_MAGIC:
            raise PackageError(f"{path.name}: has .msi extension but is not an MSI (OLE) file")
        return PackageKind.MSI
    if suffix == ".zip":
        if not head.startswith((_ZIP_MAGIC, _ZIP_EMPTY_MAGIC)):
            raise PackageError(f"{path.name}: has .zip extension but is not a ZIP file")
        return PackageKind.ZIP
    raise PackageError(f"{path.name}: unsupported package type (expected .msi, .zip or a .bundle folder)")


def bundle_files(bundle: Path) -> list[Path]:
    return sorted(
        (p for p in bundle.rglob("*") if p.is_file()), key=lambda p: p.relative_to(bundle).as_posix()
    )


def tree_sha256(bundle: Path) -> str:
    """Deterministic hash of a folder: relative paths + file hashes, independent of timestamps and order."""
    digest = hashlib.sha256()
    for file in bundle_files(bundle):
        digest.update(f"{file.relative_to(bundle).as_posix()}\0{sha256_file(file)}\n".encode())
    return digest.hexdigest()


def package_sha256(path: Path, kind: PackageKind) -> str:
    return tree_sha256(path) if kind is PackageKind.BUNDLE else sha256_file(path)


def package_size(path: Path, kind: PackageKind) -> int:
    if kind is PackageKind.BUNDLE:
        return sum(f.stat().st_size for f in bundle_files(path))
    return path.stat().st_size
