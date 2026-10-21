"""Listing checks LST-001...003 (P1-R09).

Network access is injectable (`open_url`, `resolve`) so tests never touch the internet. The user agent is
neutral: nothing tells the publisher's server that MTA is calling (Constitution §11).
"""

import re
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import dns.exception
import dns.resolver

from mta.config import MtaConfig
from mta.models import CheckResult, Status, Submission
from mta.static.results import ResultSink, excerpt

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
# Bot protection (Akamai, Cloudflare, ...) answers automated clients with these even when the page works in
# a browser, e.g. autodesk.com's privacy page returns 403 "AkamaiGHost" (step 10 demo): not a dead page.
BLOCKED_CODES = frozenset({401, 403, 429, 503})
_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})$")

# open_url(url, timeout) -> (status code, Location header or None); raises OSError subclasses on failure.
OpenUrl = Callable[[str, int], tuple[int, str | None]]
# resolve(name, rdtype, timeout) -> record texts; raises dns.exception.DNSException subclasses.
Resolve = Callable[[str, str, int], list[str]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None  # every hop is checked by hand (it must stay HTTPS)


def open_url(url: str, timeout: int) -> tuple[int, str | None]:
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers=HEADERS, method="GET")  # noqa: S310
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status), None
    except urllib.error.HTTPError as exc:  # non-2xx, including the 3xx we refused to follow
        return exc.code, exc.headers.get("Location")


def resolve(name: str, rdtype: str, timeout: int) -> list[str]:
    resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout
    return [r.to_text() for r in resolver.resolve(name, rdtype)]


@dataclass(frozen=True)
class Verdict:
    status: Status
    message: str
    evidence: str | None = None


def check_privacy_url(url: str, open_url: OpenUrl, timeout: int, max_redirects: int) -> Verdict:
    chain = [url]
    for _ in range(max_redirects + 1):
        current = chain[-1]
        if urlsplit(current).scheme.lower() != "https":
            return Verdict(Status.FAIL, "Privacy policy URL is not HTTPS", " -> ".join(chain))
        try:
            code, location = open_url(current, timeout)
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, socket.gaierror):
                return Verdict(Status.FAIL, "Privacy policy host does not resolve", f"{current}: {reason}")
            if isinstance(reason, ssl.SSLError):
                return Verdict(
                    Status.FAIL, "Privacy policy site has a TLS/certificate problem", f"{current}: {reason}"
                )
            if isinstance(reason, ConnectionRefusedError):
                return Verdict(
                    Status.FAIL, "Privacy policy server refused the connection", f"{current}: {reason}"
                )
            return Verdict(Status.ERROR, f"Privacy policy URL could not be checked: {reason}", current)
        except ssl.SSLError as exc:
            return Verdict(
                Status.FAIL, "Privacy policy site has a TLS/certificate problem", f"{current}: {exc}"
            )
        except (TimeoutError, OSError) as exc:
            return Verdict(Status.ERROR, f"Privacy policy URL could not be checked: {exc}", current)
        if 300 <= code < 400 and location:
            chain.append(urljoin(current, location))
            continue
        if 200 <= code < 300:
            return Verdict(Status.PASS, f"Privacy policy reachable over HTTPS ({code})", " -> ".join(chain))
        if code in BLOCKED_CODES:
            return Verdict(
                Status.NEEDS_REVIEW,
                f"Privacy policy server refused an automated request (HTTP {code}); check it in a browser",
                " -> ".join(chain),
            )
        return Verdict(Status.FAIL, f"Privacy policy URL returned HTTP {code}", " -> ".join(chain))
    return Verdict(Status.FAIL, f"More than {max_redirects} redirects", " -> ".join(chain))


def check_support_email(email: str, resolve: Resolve, timeout: int) -> Verdict:
    match = _EMAIL.match(email.strip())
    if not match:
        return Verdict(Status.FAIL, "Support email is not a valid address", email)
    domain = match.group(1)
    try:
        records = resolve(domain, "MX", timeout)
        return Verdict(Status.PASS, f"Support email domain {domain} has MX records", excerpt(records))
    except dns.resolver.NXDOMAIN:
        return Verdict(Status.FAIL, f"Support email domain {domain} does not exist", email)
    except dns.resolver.NoAnswer:
        pass
    except (dns.exception.Timeout, dns.resolver.NoNameservers) as exc:
        return Verdict(Status.ERROR, f"DNS lookup failed: {type(exc).__name__}", domain)
    try:
        resolve(domain, "A", timeout)
    except dns.exception.DNSException:
        return Verdict(Status.FAIL, f"Support email domain {domain} has no MX or A record", email)
    return Verdict(
        Status.WARN, f"Support email domain {domain} has no MX record (mail falls back to A)", domain
    )


def _lst003(
    sink: ResultSink, submission: Submission, covered: set[int], prior: list[CheckResult], host_id: str
) -> None:
    declared = sorted({v for p in submission.products if p.host_id == host_id for v in p.versions})
    if not declared:
        sink.skip("LST-003", reason="the listing declares no versions for this host")
        return
    broken = sorted(
        {
            f"{r.target.host_version}: {r.check_id} {r.message}"
            for r in prior
            if r.check_id in ("BIN-001", "BIN-002")
            and r.status is Status.FAIL
            and r.target.host_version in declared
        }
    )
    problems = [
        f"{y}: not covered by the manifest" for y in declared if covered and y not in covered
    ] + broken
    extra = sorted(covered - set(declared))
    note = f"; package also supports {extra}" if extra else ""
    if problems:
        sink.add(
            "LST-003",
            Status.FAIL,
            "Listing declares versions the package does not support",
            excerpt(problems),
            fix="Correct the supported versions on the listing or rebuild the package for them.",
        )
    else:
        sink.add("LST-003", Status.PASS, f"Listing versions {declared} consistent with the package{note}")


def listing_checks(
    submission: Submission,
    covered_versions: set[int],
    prior_results: list[CheckResult],
    cfg: MtaConfig,
    *,
    open_url: OpenUrl = open_url,
    resolve: Resolve = resolve,
    offline: bool = False,
    host_id: str = "autocad",
) -> list[CheckResult]:
    limits = cfg.thresholds.listing
    sink = ResultSink(cfg)
    listing = submission.listing
    if listing is None:
        sink.skip("LST-001", "LST-002", reason="no listing metadata in the kit")
    elif offline:
        sink.skip("LST-001", "LST-002", reason="offline mode: network checks not run")
    else:
        if listing.privacy_policy_url:
            v = check_privacy_url(
                listing.privacy_policy_url, open_url, limits.http_timeout_s, limits.max_redirects
            )
            sink.add("LST-001", v.status, v.message, v.evidence)
        else:
            sink.add(
                "LST-001",
                Status.NEEDS_REVIEW,
                "No privacy policy URL in the kit",
                "listing.privacy_policy_url: missing",
            )
        if listing.support_email:
            v = check_support_email(listing.support_email, resolve, limits.dns_timeout_s)
            sink.add("LST-002", v.status, v.message, v.evidence)
        else:
            sink.add(
                "LST-002",
                Status.NEEDS_REVIEW,
                "No support email in the kit",
                "listing.support_email: missing",
            )
    _lst003(sink, submission, covered_versions, prior_results, host_id)
    return sink.sorted()
