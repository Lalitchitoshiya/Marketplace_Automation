"""Authenticode signatures (SIG-001, SIG-002) via PowerShell `Get-AuthenticodeSignature`.

One PowerShell process checks every file (startup costs about a second). The file list goes through a temp
file, and only scalar fields are selected so the JSON stays small and stable.
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$paths = Get-Content -LiteralPath $args[0] -Encoding UTF8 | Where-Object { $_ }
$out = foreach ($p in $paths) {
    $s = Get-AuthenticodeSignature -LiteralPath $p
    $c = $s.SignerCertificate
    [pscustomobject]@{
        path           = [string]$p
        status         = [string]$s.Status
        status_message = [string]$s.StatusMessage
        signature_type = [string]$s.SignatureType
        signer         = if ($c) { $c.Subject } else { $null }
        issuer         = if ($c) { $c.Issuer } else { $null }
        thumbprint     = if ($c) { $c.Thumbprint } else { $null }
        not_after      = if ($c) { $c.NotAfter.ToString('o') } else { $null }
        timestamped    = [bool]$s.TimeStamperCertificate
    }
}
ConvertTo-Json -InputObject @($out) -Depth 2 -Compress
"""


class SigningError(Exception):
    """The signature check itself could not run (an MTA problem, so ERROR)."""


@dataclass(frozen=True)
class SignatureInfo:
    path: str
    status: str  # Valid, NotSigned, HashMismatch, NotTrusted, UnknownError, Incompatible
    status_message: str
    signature_type: str  # Authenticode (embedded) or Catalog
    signer: str | None
    issuer: str | None
    thumbprint: str | None
    not_after: str | None
    timestamped: bool

    @property
    def signed(self) -> bool:
        """A signer certificate is present. Tampered or untrusted files keep it (and fail SIG-002); a file
        that is not a valid PE reports UnknownError without one, which counts as unsigned."""
        return self.signer is not None

    @property
    def valid(self) -> bool:
        return self.status == "Valid"


def check_signatures(files: list[Path], timeout_s: int = 300) -> list[SignatureInfo]:
    if not files:
        return []
    with tempfile.TemporaryDirectory(prefix="mta-sig-") as temp:
        script = Path(temp) / "sig.ps1"
        script.write_text(_SCRIPT, encoding="utf-8-sig")
        listing = Path(temp) / "files.txt"
        listing.write_text("\n".join(str(f.resolve()) for f in files), encoding="utf-8-sig")
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
        try:
            done = subprocess.run(  # noqa: S603 (fixed script, file list via temp file)
                [*command, "-File", str(script), str(listing)],
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SigningError(f"signature check could not run: {exc}") from exc
    if done.returncode != 0:
        raise SigningError(f"signature check failed: {done.stderr.decode(errors='replace')[-500:]}")
    try:
        rows = json.loads(done.stdout.decode("utf-8-sig"))
        return [SignatureInfo(**row) for row in rows]
    except (ValueError, TypeError) as exc:
        raise SigningError(f"unexpected signature check output: {exc}") from exc
