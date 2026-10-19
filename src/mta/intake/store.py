"""Content-addressed artifact store (P1-R02, Constitution §9).

Every file is stored once under its SHA-256: <root>/objects/<first 2 hex>/<sha256>. Storing the same content
twice is a no-op, so references in reports stay valid and reproducible.
"""

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class StoredArtifact:
    sha256: str
    size_bytes: int
    path: Path

    @property
    def ref(self) -> str:
        return f"sha256:{self.sha256}"


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects = root / "objects"

    def path_for(self, sha256: str) -> Path:
        return self.objects / sha256[:2] / sha256

    def has(self, sha256: str) -> bool:
        return self.path_for(sha256).is_file()

    def put_file(self, source: Path) -> StoredArtifact:
        sha = sha256_file(source)
        target = self.path_for(sha)
        if not target.is_file():
            self._write_atomically(target, source.read_bytes())
        return StoredArtifact(sha, target.stat().st_size, target)

    def put_bytes(self, data: bytes) -> StoredArtifact:
        sha = hashlib.sha256(data).hexdigest()
        target = self.path_for(sha)
        if not target.is_file():
            self._write_atomically(target, data)
        return StoredArtifact(sha, len(data), target)

    @staticmethod
    def _write_atomically(target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            Path(tmp).replace(target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
