"""Native PE reading for ARX/DBX/CRX and native DLLs (P1-R07): machine type and imported DLLs, with pefile.

pefile only parses the file; nothing is loaded or executed.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import pefile  # type: ignore[import-untyped]

_MACHINES = {0x8664: "AMD64", 0x14C: "I386", 0xAA64: "ARM64"}
_ACDB = re.compile(r"^acdb(\d+)\.dll$", re.IGNORECASE)


@dataclass(frozen=True)
class NativeReport:
    path: str
    machine: str
    imports: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def acdb_major(self) -> int | None:
        """API major from the imported acdbNN.dll, e.g. acdb25.dll -> 25."""
        for name in self.imports:
            match = _ACDB.match(name)
            if match:
                return int(match.group(1))
        return None


def read_native(path: Path) -> NativeReport:
    try:
        pe = pefile.PE(str(path), fast_load=True)
    except (pefile.PEFormatError, OSError) as exc:
        return NativeReport(str(path), "UNKNOWN", error=f"{type(exc).__name__}: {exc}")
    try:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        machine = _MACHINES.get(pe.FILE_HEADER.Machine, hex(pe.FILE_HEADER.Machine))
        imports = sorted(
            {entry.dll.decode(errors="replace") for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])},
            key=str.lower,
        )
        return NativeReport(str(path), machine, imports)
    finally:
        pe.close()
