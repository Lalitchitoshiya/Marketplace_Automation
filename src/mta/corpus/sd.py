"""The synthetic-defect corpus and the M2 measure (requirements.md P1-R26, testing-strategy.md).

Each SD case packages MTA's own code as a bundle. The runner (corpus/runner.py) runs the full pipeline and
compares it against SD-01: the checks that are not PASS/SKIPPED in the case but are in SD-01 must equal the
case's expected checks exactly.
"""

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mta.adapters.autocad.build import build_for
from mta.config import MtaConfig
from mta.corpus.synthetic import SYNTHETIC, built_dll, make_bundle
from mta.models import CheckResult, Status

EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
REJECTED_AT_INTAKE = "SIG-003"  # a kit rejected by the intake malware scan counts as SIG-003

_SIGN = r"""
using namespace System.Security.Cryptography
using namespace System.Security.Cryptography.X509Certificates
$ErrorActionPreference = 'Stop'
$rsa = [RSA]::Create(2048)
$req = [CertificateRequest]::new('CN=Synthetic test signer', $rsa, [HashAlgorithmName]::SHA256,
  [RSASignaturePadding]::Pkcs1)
$oids = [OidCollection]::new()
[void]$oids.Add([Oid]::new('1.3.6.1.5.5.7.3.3'))  # code signing
$req.CertificateExtensions.Add([X509EnhancedKeyUsageExtension]::new($oids, $false))
$cert = $req.CreateSelfSigned([DateTimeOffset]::Now.AddDays(-1), [DateTimeOffset]::Now.AddYears(1))
foreach ($f in (Get-Content -LiteralPath $args[0])) {
  if ($f) { [void](Set-AuthenticodeSignature -LiteralPath $f -Certificate $cert -HashAlgorithm SHA256) }
}
"""


def sign_untrusted(files: list[Path]) -> None:
    """Authenticode-sign with a throwaway self-signed certificate held in memory (no store is touched)."""
    if not files:
        return
    with tempfile.TemporaryDirectory(prefix="mta-sign-") as temp:
        script = Path(temp) / "sign.ps1"
        script.write_text(_SIGN, encoding="utf-8-sig")
        listing = Path(temp) / "files.txt"
        listing.write_text("\n".join(str(f.resolve()) for f in files), encoding="utf-8-sig")
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
        subprocess.run([*command, str(script), str(listing)], check=True, capture_output=True, timeout=300)  # noqa: S603


@dataclass(frozen=True)
class SdCase:
    id: str
    title: str
    expected: frozenset[str]
    package: Callable[[MtaConfig, Path], Path]  # builds the bundle under the given folder
    needs_eicar: bool = False


def _dll(project: str, cfg: MtaConfig) -> Path:
    dll = built_dll(project, cfg, 2026)
    if not dll.is_file():
        raise FileNotFoundError(f"{dll} missing: run `mta corpus build`")
    return dll


def _signed_bundle(name: str, dlls: list[Path], out: Path, *, sign: bool = True, **kw: object) -> Path:
    bundle = make_bundle(dlls, out, name=name, **kw)  # type: ignore[arg-type]
    if sign:
        sign_untrusted(sorted((bundle / "Contents").glob("*.dll")))
    return bundle


def _simple(project: str) -> Callable[[MtaConfig, Path], Path]:
    return lambda cfg, out: _signed_bundle(project, [_dll(project, cfg)], out)


def _sd06(cfg: MtaConfig, out: Path) -> Path:
    """SD-01's code built for .NET 10 against the 2026 (R25, .NET 8) assemblies: wrong target framework."""
    build_dir = build_for(SYNTHETIC / "Sd01Clean", cfg, 2026, tfm="net10.0-windows")
    return _signed_bundle("Sd06WrongTfm", [build_dir / "Sd01Clean.dll"], out)


def _sd08(cfg: MtaConfig, out: Path) -> Path:
    """SD-01 plus a copy of AutoCAD's own AcDbMgd.dll (Autodesk-signed)."""
    host = Path(cfg.hosts.hosts["autocad"].version(2026).install_dir) / "AcDbMgd.dll"
    bundle = _signed_bundle("Sd08ShipsHostDll", [_dll("Sd01Clean", cfg)], out)
    shutil.copy2(host, bundle / "Contents" / "AcDbMgd.dll")
    return bundle


CASES: list[SdCase] = [
    SdCase("SD-01", "Clean, well-behaved plugin", frozenset(), _simple("Sd01Clean")),
    SdCase("SD-02", "Throws in Initialize", frozenset({"LOD-001"}), _simple("Sd02InitThrow")),
    SdCase("SD-03", "Command throws NullReferenceException", frozenset({"CMD-002", "RUN-002"}),
           _simple("Sd03NullRef")),
    SdCase("SD-04", "Command hangs", frozenset({"CMD-004"}), _simple("Sd04Hang")),
    SdCase("SD-05", "Command crashes the host (native)", frozenset({"RUN-001"}), _simple("Sd05NativeCrash")),
    SdCase("SD-06", "Wrong target framework", frozenset({"BIN-001"}), _sd06),
    SdCase("SD-07", "Missing dependency DLL", frozenset({"BIN-004", "LOD-001"}), _simple("Sd07MissingDep")),
    SdCase("SD-08", "Ships host API DLLs", frozenset({"BIN-005"}), _sd08),
    SdCase("SD-09", "Manifest points to a missing module", frozenset({"MAN-004"}),
           lambda cfg, out: _signed_bundle("Sd09BadModule", [_dll("Sd01Clean", cfg)], out,
                                           module="./Contents/Missing.dll")),
    SdCase("SD-10", "Unsigned binaries", frozenset({"SIG-001"}),
           lambda cfg, out: _signed_bundle("Sd10Unsigned", [_dll("Sd01Clean", cfg)], out, sign=False)),
    SdCase("SD-11", "EICAR test file in the package", frozenset({"SIG-003"}),
           lambda cfg, out: _signed_bundle("Sd11Eicar", [_dll("Sd01Clean", cfg)], out,
                                           extra_files={"Contents/eicar.com": EICAR}), needs_eicar=True),
    SdCase("SD-16", "Command collides with a built-in (LINE)", frozenset({"CMD-003"}),
           _simple("Sd16Collision")),
]  # fmt: skip


def not_green(results: list[CheckResult]) -> set[str]:
    return {r.check_id for r in results if r.status not in (Status.PASS, Status.SKIPPED)}
