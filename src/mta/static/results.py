"""Collects static CheckResults with the configured severity (checks.yaml, provisional cap applied)."""

from collections.abc import Iterable

from mta.config import MtaConfig
from mta.models import CheckResult, Source, Status
from mta.models.results import CheckTarget, Evidence

MAX_LISTED = 20


def excerpt(lines: Iterable[str]) -> str:
    """Evidence text listing at most MAX_LISTED items."""
    items = list(lines)
    more = f"\n... and {len(items) - MAX_LISTED} more" if len(items) > MAX_LISTED else ""
    return "\n".join(items[:MAX_LISTED]) + more


class ResultSink:
    def __init__(self, cfg: MtaConfig, source: Source = Source.STATIC) -> None:
        self._cfg = cfg
        self._source = source
        self.items: list[CheckResult] = []

    def add(
        self,
        check_id: str,
        status: Status,
        message: str,
        excerpt: str | None = None,
        fix: str | None = None,
        *,
        subject: str = "package",
        host_id: str | None = None,
        host_version: int | None = None,
    ) -> None:
        self.items.append(
            CheckResult(
                check_id=check_id,
                target=CheckTarget(
                    subject=subject,
                    host_id=host_id,
                    host_version=host_version,
                ),
                status=status,
                severity=self._cfg.checks.effective_severity(check_id),
                source=self._source,
                message=message,
                evidence=[Evidence(kind="excerpt", excerpt=excerpt)] if excerpt else [],
                remediation=fix,
            )
        )

    def skip(self, *check_ids: str, reason: str) -> None:
        for check_id in check_ids:
            self.add(check_id, Status.SKIPPED, reason)

    def sorted(self) -> list[CheckResult]:
        return sorted(self.items, key=lambda r: (r.check_id, r.target.subject, r.target.host_version or 0))
