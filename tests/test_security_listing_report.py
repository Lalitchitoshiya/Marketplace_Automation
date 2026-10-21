"""Step 10: signing (SIG-001/002), malware (SIG-003), dynamic gate, listing (LST-001...003), report.json."""

import json
import shutil
import socket
import ssl
import subprocess
import threading
import urllib.error
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import dns.exception
import dns.resolver
import pytest
from typer.testing import CliRunner

from mta import schemas
from mta.cli.app import app
from mta.config import MtaConfig
from mta.engine.recommend import label, recommend
from mta.intake.pipeline import intake_kit
from mta.models import (
    CheckResult,
    PackageKind,
    ProductDecl,
    Recommendation,
    Severity,
    Source,
    Status,
    Submission,
)
from mta.models.results import CheckTarget, Evidence
from mta.models.submission import Listing, PackageRef
from mta.report.builder import ReportError, matrix, summarize, write_job_report
from mta.static.listing import check_privacy_url, check_support_email, listing_checks, open_url
from mta.static.malware import ScanOutcome, ScanResult
from mta.static.security_checks import analyze_security, dynamic_gate
from mta.static.signing import SignatureInfo, SigningError, check_signatures
from mta.static.stage import StaticServices, run_static_stage
from tests.conftest import (
    OFFLINE_SERVICES,
    KitFactory,
    clean_scanner,
    fake_open_url,
    fake_resolve,
    infected_scanner,
    make_bundle,
    make_msi,
)

# ---- signing ---------------------------------------------------------------------------------------------


def _sig(
    path: str, status: str = "Valid", timestamped: bool = True, signer: str | None = "CN=Acme"
) -> SignatureInfo:
    signed = status not in ("NotSigned", "UnknownError")
    return SignatureInfo(
        path,
        status,
        status,
        "Authenticode" if signed else "None",
        signer if signed else None,
        None,
        None,
        None,
        timestamped and signed,
    )


def _signed_file() -> Path:
    candidate = Path(shutil.which("dotnet") or r"C:\Program Files\dotnet\dotnet.exe")
    if not candidate.is_file():
        pytest.skip("no Authenticode-signed file available (dotnet.exe)")
    return candidate


def test_real_signatures_valid_tampered_unsigned(tmp_path: Path, net_fixtures: dict[str, Path]) -> None:
    signed = _signed_file()
    tampered = tmp_path / "tampered.exe"
    data = bytearray(signed.read_bytes())
    data[len(data) // 2] ^= 0xFF
    tampered.write_bytes(bytes(data))
    unsigned = tmp_path / "unsigned.dll"  # a real PE without a signature
    unsigned.write_bytes(net_fixtures["inspect"].with_suffix(".dll").read_bytes())
    junk = tmp_path / "junk.dll"
    junk.write_bytes(b"MZ not a PE")
    valid, broken, none, bad = check_signatures([signed, tampered, unsigned, junk])
    assert (valid.status, valid.signature_type, valid.timestamped) == ("Valid", "Authenticode", True)
    assert valid.signer and "Microsoft" in valid.signer
    assert broken.status == "HashMismatch" and broken.signed and not broken.valid
    assert none.status == "NotSigned" and not none.signed
    assert none.path == str(unsigned.resolve())
    assert bad.status == "UnknownError" and not bad.signed
    assert check_signatures([]) == []


def test_signing_tool_failures_raise(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def run(stdout: bytes, code: int) -> Any:
        return lambda *a, **k: subprocess.CompletedProcess(a, code, stdout, b"denied")

    monkeypatch.setattr(subprocess, "run", run(b"not json", 0))
    with pytest.raises(SigningError, match="unexpected"):
        check_signatures([tmp_path / "a.dll"])
    monkeypatch.setattr(subprocess, "run", run(b"", 1))
    with pytest.raises(SigningError, match="denied"):
        check_signatures([tmp_path / "a.dll"])


def _security(
    tmp_path: Path,
    cfg: MtaConfig,
    sigs: dict[str, SignatureInfo],
    scan: ScanResult | None = None,
    msi: bool = False,
) -> dict[str, CheckResult]:
    payload = tmp_path / "payload"
    payload.mkdir()
    for name in sigs:
        if name.endswith(".msi"):
            continue
        (payload / name).write_bytes(b"MZ")
    (payload / "readme.txt").write_text("not signable", encoding="utf-8")
    package = make_msi(tmp_path, "Acme.msi") if msi else tmp_path / "Acme.zip"
    files = sorted(payload.rglob("*"))

    def fake_check(paths: list[Path], _timeout: int) -> list[SignatureInfo]:
        return [sigs[p.name] for p in paths]

    analysis = analyze_security(
        payload, files, package, cfg, scanner=(lambda _: scan) if scan else None, check=fake_check
    )
    return {r.check_id: r for r in analysis.results}


def test_sig001_sig002_rules(tmp_path: Path, cfg: MtaConfig) -> None:
    results = _security(
        tmp_path,
        cfg,
        {
            "a.dll": _sig("a.dll"),
            "b.dll": _sig("b.dll", "NotSigned"),
            "c.arx": _sig("c.arx", timestamped=False),
            "d.exe": _sig("d.exe", "NotTrusted", signer="CN=Self"),
            "Acme.msi": _sig("Acme.msi"),
        },
        msi=True,
    )
    sig001, sig002 = results["SIG-001"], results["SIG-002"]
    assert sig001.status is Status.FAIL and sig001.message == "1 of 5 file(s) not signed"
    assert sig002.status is Status.FAIL
    text = sig002.evidence[0].excerpt or ""
    assert "d.exe: NotTrusted" in text and "c.arx: not timestamped" in text and "CN=Self" in text
    assert results["SIG-003"].status is Status.SKIPPED  # scanner=None: explicit --no-scan


def test_all_signed_and_timestamped(tmp_path: Path, cfg: MtaConfig) -> None:
    clean = ScanResult(ScanOutcome.CLEAN, 0, "")
    results = _security(tmp_path, cfg, {"a.dll": _sig("a.dll")}, scan=clean)
    assert results["SIG-001"].status is Status.PASS and results["SIG-002"].status is Status.PASS
    assert "CN=Acme" in results["SIG-002"].message
    assert results["SIG-003"].status is Status.PASS


def test_nothing_signed_skips_sig002(tmp_path: Path, cfg: MtaConfig) -> None:
    results = _security(tmp_path, cfg, {"a.dll": _sig("a.dll", "NotSigned")})
    assert results["SIG-002"].status is Status.SKIPPED


@pytest.mark.parametrize(
    ("scan", "status"),
    [
        (ScanResult(ScanOutcome.THREATS, 2, "x", ["Virus:DOS/EICAR_Test_File"]), Status.FAIL),
        (ScanResult(ScanOutcome.UNAVAILABLE, None, "Defender CLI not found"), Status.ERROR),
    ],
)
def test_sig003_outcomes(tmp_path: Path, cfg: MtaConfig, scan: ScanResult, status: Status) -> None:
    result = _security(tmp_path, cfg, {"a.dll": _sig("a.dll")}, scan=scan)["SIG-003"]
    assert result.status is status
    assert result.severity is Severity.BLOCKER  # non-provisional safety gate


def test_signing_unavailable_is_error(tmp_path: Path, cfg: MtaConfig) -> None:
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "a.dll").write_bytes(b"MZ")

    def broken(_: list[Path], __: int) -> list[SignatureInfo]:
        raise SigningError("PowerShell missing")

    analysis = analyze_security(
        tmp_path / "p",
        [tmp_path / "p" / "a.dll"],
        tmp_path / "x.zip",
        cfg,
        scanner=clean_scanner,
        check=broken,
    )
    statuses = {r.check_id: r.status for r in analysis.results}
    assert statuses == {"SIG-001": Status.ERROR, "SIG-002": Status.ERROR, "SIG-003": Status.PASS}


def test_no_payload(tmp_path: Path, cfg: MtaConfig) -> None:
    analysis = analyze_security(
        None, [], tmp_path / "x.zip", cfg, scanner=clean_scanner, check=lambda f, t: []
    )
    assert {r.check_id: r.status for r in analysis.results} == {
        "SIG-001": Status.SKIPPED,
        "SIG-002": Status.SKIPPED,
        "SIG-003": Status.SKIPPED,
    }


# ---- dynamic gate ----------------------------------------------------------------------------------------


def _result(check_id: str, status: Status, severity: Severity = Severity.MAJOR, **target: Any) -> CheckResult:
    evidence = (
        [Evidence(kind="excerpt", excerpt="x")]
        if status in (Status.FAIL, Status.WARN, Status.NEEDS_REVIEW)
        else []
    )
    return CheckResult(
        check_id=check_id,
        target=CheckTarget(subject=target.pop("subject", "package"), **target),
        status=status,
        severity=severity,
        source=Source.STATIC,
        message="m",
        evidence=evidence,
    )


SAFE = [_result("PKG-001", Status.PASS), _result("PKG-002", Status.PASS)]


@pytest.mark.parametrize(
    ("sig003", "scan_skipped", "allowed"),
    [
        (Status.PASS, False, True),
        (Status.SKIPPED, True, True),
        (Status.SKIPPED, False, False),
        (Status.FAIL, False, False),
        (Status.ERROR, False, False),
    ],
)
def test_gate_needs_a_clean_scan(sig003: Status, scan_skipped: bool, allowed: bool) -> None:
    gate = dynamic_gate([*SAFE, _result("SIG-003", sig003)], scan_skipped=scan_skipped)
    assert gate.dynamic_allowed is allowed
    assert bool(gate.reasons) is not allowed


def test_gate_needs_a_safe_payload() -> None:
    gate = dynamic_gate(
        [_result("PKG-001", Status.FAIL), _result("SIG-003", Status.PASS)], scan_skipped=False
    )
    assert not gate.dynamic_allowed
    assert gate.reasons == [
        "PKG-001 FAIL: no safe, deployable payload",
        "PKG-002 missing: no safe, deployable payload",
    ]


# ---- LST-001 ---------------------------------------------------------------------------------------------


def _urls(responses: dict[str, Any]) -> Any:
    def fake(url: str, _timeout: int) -> tuple[int, str | None]:
        found = responses[url]
        if isinstance(found, Exception):
            raise found
        return found  # type: ignore[no-any-return]

    return fake


@pytest.mark.parametrize(
    ("url", "responses", "status", "text"),
    [
        ("https://a.example/p", {"https://a.example/p": (200, None)}, Status.PASS, "(200)"),
        (
            "https://a.example/p",
            {"https://a.example/p": (301, "/privacy"), "https://a.example/privacy": (200, None)},
            Status.PASS,
            "",
        ),
        ("http://a.example/p", {}, Status.FAIL, "not HTTPS"),
        (
            "https://a.example/p",
            {"https://a.example/p": (302, "http://a.example/p")},
            Status.FAIL,
            "not HTTPS",
        ),
        ("https://a.example/p", {"https://a.example/p": (404, None)}, Status.FAIL, "HTTP 404"),
        (
            "https://a.example/p",
            {"https://a.example/p": (403, None)},
            Status.NEEDS_REVIEW,
            "check it in a browser",
        ),
        ("https://a.example/p", {"https://a.example/p": (500, None)}, Status.FAIL, "HTTP 500"),
        (
            "https://a.example/p",
            {"https://a.example/p": urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))},
            Status.FAIL,
            "does not resolve",
        ),
        (
            "https://a.example/p",
            {"https://a.example/p": urllib.error.URLError(ssl.SSLCertVerificationError("bad cert"))},
            Status.FAIL,
            "TLS",
        ),
        (
            "https://a.example/p",
            {"https://a.example/p": urllib.error.URLError(ConnectionRefusedError())},
            Status.FAIL,
            "refused",
        ),
        (
            "https://a.example/p",
            {"https://a.example/p": TimeoutError("timed out")},
            Status.ERROR,
            "could not be checked",
        ),
        (
            "https://a.example/p",
            {"https://a.example/p": urllib.error.URLError(TimeoutError("timed out"))},
            Status.ERROR,
            "could not be checked",
        ),
        ("https://a.example/p", {"https://a.example/p": (301, "/p")}, Status.FAIL, "More than 2 redirects"),
    ],
)
def test_privacy_url(url: str, responses: dict[str, Any], status: Status, text: str) -> None:
    verdict = check_privacy_url(url, _urls(responses), timeout=5, max_redirects=2)
    assert verdict.status is status, verdict
    assert text in verdict.message


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/moved":
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
        else:
            self.send_response(200)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def local_server() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_open_url_does_not_follow_redirects(local_server: str) -> None:
    assert open_url(f"{local_server}/ok", 5) == (200, None)
    assert open_url(f"{local_server}/moved", 5) == (302, "/elsewhere")


# ---- LST-002 ---------------------------------------------------------------------------------------------


def _dns(answers: dict[tuple[str, str], Any]) -> Any:
    def fake(name: str, rdtype: str, _timeout: int) -> list[str]:
        found = answers.get((name, rdtype), dns.resolver.NoAnswer)
        if isinstance(found, type):
            raise found
        return found  # type: ignore[no-any-return]

    return fake


@pytest.mark.parametrize(
    ("answers", "email", "status"),
    [
        ({("acme.example", "MX"): ["10 mx.acme.example."]}, "support@acme.example", Status.PASS),
        ({}, "not-an-email", Status.FAIL),
        ({("acme.example", "MX"): dns.resolver.NXDOMAIN}, "support@acme.example", Status.FAIL),
        ({("acme.example", "A"): ["1.2.3.4"]}, "support@acme.example", Status.WARN),
        ({}, "support@acme.example", Status.FAIL),
        ({("acme.example", "MX"): dns.exception.Timeout}, "support@acme.example", Status.ERROR),
    ],
)
def test_support_email(answers: dict[tuple[str, str], Any], email: str, status: Status) -> None:
    assert check_support_email(email, _dns(answers), timeout=2).status is status


# ---- LST-003 and listing_checks --------------------------------------------------------------------------


def _submission(listing: Listing | None = None, years: list[int] | None = None) -> Submission:
    return Submission(
        submission_id="sub-1",
        app_id="acme.tools",
        app_version="2.3.0",
        package=PackageRef(filename="Acme.zip", sha256="0" * 64, size_bytes=1, kind=PackageKind.ZIP),
        products=[ProductDecl(host_id="autocad", versions=years)] if years else [],
        listing=listing,
        received_at=datetime.now(UTC),
    )


LISTING = Listing(
    title="Acme",
    publisher="Acme Ltd",
    privacy_policy_url="https://acme.example/privacy",
    support_email="support@acme.example",
)


def _lst(
    cfg: MtaConfig,
    submission: Submission,
    covered: set[int],
    prior: list[CheckResult] | None = None,
    **kw: Any,
) -> dict[str, CheckResult]:
    results = listing_checks(
        submission, covered, prior or [], cfg, open_url=fake_open_url, resolve=fake_resolve, **kw
    )
    return {r.check_id: r for r in results}


def test_listing_checks_all_pass(cfg: MtaConfig) -> None:
    results = _lst(cfg, _submission(LISTING, [2025, 2026]), {2025, 2026, 2027})
    assert {k: v.status for k, v in results.items()} == dict.fromkeys(
        ("LST-001", "LST-002", "LST-003"), Status.PASS
    )
    assert "package also supports [2027]" in results["LST-003"].message


def test_listing_missing_offline_and_absent(cfg: MtaConfig) -> None:
    bare = Listing(title="Acme", publisher="Acme Ltd")
    results = _lst(cfg, _submission(bare), set())
    assert (
        results["LST-001"].status is Status.NEEDS_REVIEW and results["LST-002"].status is Status.NEEDS_REVIEW
    )
    assert results["LST-003"].status is Status.SKIPPED
    offline = _lst(cfg, _submission(LISTING), set(), offline=True)
    assert offline["LST-001"].status is Status.SKIPPED and "offline" in offline["LST-001"].message
    assert _lst(cfg, _submission(None), set())["LST-002"].status is Status.SKIPPED


def test_lst003_uncovered_and_broken_versions(cfg: MtaConfig) -> None:
    bin001 = _result("BIN-001", Status.FAIL, host_version=2025, host_id="autocad", subject="file:a.dll")
    other = _result("BIN-001", Status.FAIL, host_version=2024, host_id="autocad", subject="file:a.dll")
    result = _lst(cfg, _submission(None, [2025, 2026, 2027]), {2025, 2026}, [bin001, other])["LST-003"]
    text = result.evidence[0].excerpt or ""
    assert result.status is Status.FAIL
    assert "2027: not covered by the manifest" in text and "2025: BIN-001" in text
    assert "2024" not in text  # not declared on the listing


# ---- recommendation and report ---------------------------------------------------------------------------


def test_recommendation_order(cfg: MtaConfig) -> None:
    blocker = _result("SIG-003", Status.FAIL, Severity.BLOCKER)
    error = _result("BIN-001", Status.ERROR)
    major = _result("SIG-001", Status.FAIL)
    review = _result("PKG-003", Status.NEEDS_REVIEW)
    minor = _result("PKG-006", Status.FAIL, Severity.MINOR)
    warn = _result("BIN-007", Status.WARN)
    assert recommend([blocker, error, major], cfg) == (Recommendation.REJECT, ["SIG-003 FAIL (BLOCKER)"])
    assert recommend([error, major], cfg) == (Recommendation.NEEDS_HUMAN, ["BIN-001 ERROR (MAJOR)"])
    assert recommend([major, review, minor], cfg)[0] is Recommendation.NEEDS_HUMAN
    assert recommend([minor, warn, _result("PKG-001", Status.PASS)], cfg) == (Recommendation.APPROVE, [])


def test_labels_name_version_and_subject() -> None:
    result = _result(
        "BIN-001", Status.FAIL, host_version=2025, host_id="autocad", subject="file:Contents/a.dll"
    )
    assert label(result) == "BIN-001 FAIL (MAJOR) on AutoCAD 2025 [file:Contents/a.dll]"


def test_matrix_counts_version_and_global_results() -> None:
    results = [
        _result("PKG-001", Status.PASS),
        _result("BIN-001", Status.FAIL, host_version=2024, host_id="autocad"),
        _result("BIN-001", Status.PASS, host_version=2025, host_id="autocad"),
    ]
    rows = {m.host_version: m.summary for m in matrix(results, [2025, 2024], "autocad", "headless")}  # type: ignore[arg-type]
    assert (rows[2024].pass_, rows[2024].fail) == (1, 1)
    assert (rows[2025].pass_, rows[2025].fail) == (2, 0)
    assert summarize([]).model_dump(by_alias=True)["pass"] == 0


def test_job_report_end_to_end(make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path) -> None:
    data = tmp_path / "data"
    intake = intake_kit(make_kit("bundle"), cfg, data, clean_scanner)
    outcome = run_static_stage(intake, cfg, data, OFFLINE_SERVICES)
    report = write_job_report(intake, outcome, cfg, duration_ms=1234)

    job_dir = intake.job_dir
    document = json.loads((job_dir / "report.json").read_text("utf-8"))
    assert schemas.validate("report", document) == []
    assert json.loads((job_dir / "job.json").read_text("utf-8"))["state"] == "REPORTED"
    assert json.loads((job_dir / "static-gate.json").read_text("utf-8"))["dynamic_allowed"] is True
    for name in ("static-security.json", "static-listing.json"):
        assert (job_dir / "checks" / name).is_file()
    assert [m.host_version for m in report.matrix] == [2025, 2026]
    assert report.recommendation is Recommendation.NEEDS_HUMAN  # unsigned (SIG-001 MAJOR), fake DLL (BIN-*)
    assert "SIG-001 FAIL (MAJOR)" in report.recommendation_reasons
    assert report.inventory.components[0]["app_name"] == "Acme"
    assert {"source": "listing", "domain": "api.acme.example"} in report.inventory.network
    assert report.mta.duration_ms == 1234


def test_malware_in_payload_rejects_and_blocks_dynamic(
    make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    intake = intake_kit(make_kit("zip"), cfg, data, clean_scanner)  # the archive looked clean at intake
    services = StaticServices(
        scanner=infected_scanner,
        signatures=OFFLINE_SERVICES.signatures,
        open_url=fake_open_url,
        resolve=fake_resolve,
    )
    outcome = run_static_stage(intake, cfg, data, services)
    report = write_job_report(intake, outcome, cfg, duration_ms=1)
    assert report.recommendation is Recommendation.REJECT
    assert report.recommendation_reasons == ["SIG-003 FAIL (BLOCKER)"]
    assert not outcome.gate.dynamic_allowed


def test_invalid_report_is_refused(
    make_kit: KitFactory, cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    intake = intake_kit(make_kit(), cfg, data, clean_scanner)
    outcome = run_static_stage(intake, cfg, data, OFFLINE_SERVICES)
    monkeypatch.setattr(schemas, "validate", lambda name, doc: ["results: broken"])
    with pytest.raises(ReportError, match="does not match"):
        write_job_report(intake, outcome, cfg, duration_ms=1)
    assert not (intake.job_dir / "report.json").exists()


@pytest.mark.usefixtures("offline_cli")
def test_cli_inspect(make_kit: KitFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kit = make_kit("bundle")
    monkeypatch.setenv("MTA_OFFLINE", "1")
    result = CliRunner().invoke(
        app, ["inspect", "--kit", str(kit), "--no-scan", "--data-dir", str(tmp_path / "d")]
    )
    assert result.exit_code == 10, result.output  # NEEDS_HUMAN (P1-R24): unsigned test kit
    assert "RECOMMENDATION: NEEDS_HUMAN" in result.output
    assert "dynamic phase: allowed" in result.output
    assert "LST-001 SKIPPED" in result.output
    assert "BIN-001 PASS" not in result.output or "[2025]" in result.output
    report = next((tmp_path / "d" / "jobs").glob("*/report.json"))
    assert json.loads(report.read_text("utf-8"))["recommendation"] == "NEEDS_HUMAN"


@pytest.mark.usefixtures("offline_cli")
def test_cli_inspect_with_package_bundle(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path / "src")
    args = ["inspect", str(bundle), "--no-scan", "--offline", "--data-dir", str(tmp_path / "d")]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 10, result.output  # NEEDS_HUMAN (P1-R24): unsigned test kit
    assert "report:" in result.output
