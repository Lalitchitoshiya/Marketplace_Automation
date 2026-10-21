"""SIG-001...003 and the dynamic-phase gate (P1-R08)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mta.config import MtaConfig
from mta.models import CheckResult, Status
from mta.static.malware import ScanOutcome, ScanResult
from mta.static.results import ResultSink, excerpt
from mta.static.signing import SignatureInfo, SigningError, check_signatures

SIGNABLE_SUFFIXES = frozenset({".dll", ".exe", ".arx", ".crx", ".dbx", ".msi"})

CheckSignatures = Callable[[list[Path], int], list[SignatureInfo]]
Scanner = Callable[[Path], ScanResult]


@dataclass
class SecurityAnalysis:
    signatures: dict[str, SignatureInfo] = field(default_factory=dict)  # payload-relative (or package) path
    scan: ScanResult | None = None
    results: list[CheckResult] = field(default_factory=list)


@dataclass(frozen=True)
class Gate:
    dynamic_allowed: bool
    reasons: list[str]


def _signing(sink: ResultSink, sigs: dict[str, SignatureInfo]) -> None:
    if not sigs:
        sink.skip("SIG-001", "SIG-002", reason="no signable files")
        return
    unsigned = sorted(rel for rel, s in sigs.items() if not s.signed)
    if unsigned:
        sink.add(
            "SIG-001",
            Status.FAIL,
            f"{len(unsigned)} of {len(sigs)} file(s) not signed",
            excerpt(unsigned),
            fix="Sign every DLL/EXE/ARX and the MSI with an Authenticode code-signing certificate.",
        )
    else:
        sink.add("SIG-001", Status.PASS, f"All {len(sigs)} file(s) signed")

    signed = {rel: s for rel, s in sigs.items() if s.signed}
    if not signed:
        sink.skip("SIG-002", reason="no signed files")
        return
    bad = [f"{rel}: {s.status}" for rel, s in sorted(signed.items()) if not s.valid]
    bad += [
        f"{rel}: not timestamped (invalid once the certificate expires)"
        for rel, s in sorted(signed.items())
        if s.valid and not s.timestamped
    ]
    signers = sorted({s.signer or "?" for s in signed.values()})
    if bad:
        sink.add(
            "SIG-002",
            Status.FAIL,
            "Invalid or untimestamped signatures",
            excerpt([*bad, "signers:", *signers]),
        )
    else:
        sink.add("SIG-002", Status.PASS, f"Signatures valid and timestamped; signer(s): {'; '.join(signers)}")


def _malware(sink: ResultSink, scan: ScanResult | None) -> None:
    if scan is None:
        sink.skip("SIG-003", reason="malware scan skipped (--no-scan, trusted MTA fixture)")
    elif scan.outcome is ScanOutcome.CLEAN:
        sink.add("SIG-003", Status.PASS, "Microsoft Defender found no threats in the extracted payload")
    elif scan.outcome is ScanOutcome.THREATS:
        sink.add("SIG-003", Status.FAIL, f"Malware found: {', '.join(scan.threats)}", excerpt(scan.threats))
    else:
        sink.add("SIG-003", Status.ERROR, f"Malware scan unavailable: {scan.output[-300:]}")


def analyze_security(
    payload: Path | None,
    files: list[Path],
    package: Path,
    cfg: MtaConfig,
    *,
    scanner: Scanner | None,
    check: CheckSignatures = check_signatures,
) -> SecurityAnalysis:
    """`scanner=None` means the scan was explicitly skipped (trusted fixtures only)."""
    sink = ResultSink(cfg)
    analysis = SecurityAnalysis()
    targets: dict[str, Path] = {}
    if package.is_file() and package.suffix.lower() == ".msi":
        targets[package.name] = package
    if payload is not None:
        targets |= {
            f.relative_to(payload).as_posix(): f for f in files if f.suffix.lower() in SIGNABLE_SUFFIXES
        }
    try:
        infos = check(list(targets.values()), cfg.thresholds.signing.timeout_s) if targets else []
        analysis.signatures = dict(zip(targets, infos, strict=True))
        _signing(sink, analysis.signatures)
    except SigningError as exc:
        sink.add("SIG-001", Status.ERROR, f"Signature check unavailable: {exc}")
        sink.add("SIG-002", Status.ERROR, f"Signature check unavailable: {exc}")

    if payload is None:
        sink.skip("SIG-003", reason="no payload extracted")
    else:
        analysis.scan = scanner(payload) if scanner is not None else None
        _malware(sink, analysis.scan)
    analysis.results = sink.sorted()
    return analysis


def dynamic_gate(results: list[CheckResult], *, scan_skipped: bool) -> Gate:
    """P1-R08: dynamic runs only after a clean scan of a safely extracted, deployable payload.

    `scan_skipped` is True only for an explicit `--no-scan` (trusted MTA fixtures).
    """
    by_id: dict[str, list[CheckResult]] = {}
    for r in results:
        by_id.setdefault(r.check_id, []).append(r)
    reasons = []
    sig003 = [r.status for r in by_id.get("SIG-003", [])]
    if sig003 != [Status.PASS] and not (scan_skipped and sig003 == [Status.SKIPPED]):
        reasons.append(f"SIG-003 {sig003[0] if sig003 else 'missing'}: payload not confirmed clean")
    for check_id in ("PKG-001", "PKG-002"):
        statuses = [r.status for r in by_id.get(check_id, [])]
        if statuses != [Status.PASS]:
            reasons.append(
                f"{check_id} {statuses[0] if statuses else 'missing'}: no safe, deployable payload"
            )
    return Gate(not reasons, reasons)
