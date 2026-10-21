"""Corpus runner and accuracy metrics (requirements.md P1-R25, P1-R26; roadmap.md E1.1-E1.3).

Two kinds of entries:
- synthetic SD cases (corpus/sd.py), measured against SD-01's baseline;
- real submissions with a manual verdict: `<corpus>/<id>/kit/` and `<corpus>/<id>/expected.yaml`:

      title: "Acme Tools 2.3"
      verdict: RECOMMEND_REJECT          # the reviewers' decision
      expected_checks: [CMD-002, RUN-002] # checks they expect to be not green
"""

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from mta.adapters.autocad.dynamic import run_dynamic_stage
from mta.config import MtaConfig
from mta.corpus.sd import CASES, REJECTED_AT_INTAKE, SdCase, not_green
from mta.corpus.synthetic import make_kit
from mta.engine.recommend import recommend
from mta.intake.pipeline import IntakeError, intake_kit
from mta.models import Recommendation
from mta.static import malware
from mta.static.stage import StaticServices, run_static_stage


@dataclass(frozen=True)
class RealEntry:
    id: str
    title: str
    kit: Path
    expected: frozenset[str]
    verdict: Recommendation | None = None


def load_entries(corpus_dir: Path) -> list[RealEntry]:
    entries = []
    for folder in sorted(p for p in corpus_dir.iterdir() if (p / "expected.yaml").is_file()):
        data = yaml.safe_load((folder / "expected.yaml").read_text(encoding="utf-8")) or {}
        verdict = data.get("verdict")
        entries.append(
            RealEntry(
                id=folder.name,
                title=str(data.get("title", folder.name)),
                kit=folder / "kit",
                expected=frozenset(data.get("expected_checks") or []),
                verdict=Recommendation(verdict) if verdict else None,
            )
        )
    return entries


@dataclass
class KitOutcome:
    raw: set[str]
    recommendation: Recommendation | None
    job: str
    seconds: float
    versions_run: int


def run_kit(kit: Path, cfg: MtaConfig, data_dir: Path) -> KitOutcome:
    """The full pipeline on one kit (static, then dynamic), as `mta run` does."""
    started = time.monotonic()
    try:
        intake = intake_kit(kit, cfg, data_dir, malware.scan)
    except IntakeError as exc:
        if any("Threat" in p.message or "malware" in p.message.lower() for p in exc.check.problems):
            elapsed = time.monotonic() - started
            return KitOutcome({REJECTED_AT_INTAKE}, Recommendation.REJECT, "rejected at intake", elapsed, 0)
        raise
    static = run_static_stage(intake, cfg, data_dir, StaticServices(offline=True))
    dynamic = run_dynamic_stage(intake, static, cfg, data_dir)
    results = static.results + dynamic.results
    recommendation, _ = recommend(results, cfg)
    raw = not_green(results)
    summary = {"not_green": sorted(raw), "recommendation": recommendation}
    (intake.job_dir / "corpus-case.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    versions = len({s.year for s in dynamic.sessions})
    return KitOutcome(raw, recommendation, str(intake.job_dir), time.monotonic() - started, versions)


def run_case(case: SdCase, cfg: MtaConfig, data_dir: Path) -> KitOutcome:
    """Package one synthetic case as a bundle in a kit, then run the full pipeline."""
    work = data_dir / "corpus" / case.id
    shutil.rmtree(work, ignore_errors=True)
    bundle = case.package(cfg, work / "pkg")
    kit = make_kit(bundle, work / "kits", f"mta.{case.id.lower()}", [])
    return run_kit(kit, cfg, data_dir)


@dataclass
class CaseResult:
    case: SdCase | RealEntry
    triggered: set[str] = field(default_factory=set)  # SD: not green minus SD-01's; real entries: not green
    raw: set[str] = field(default_factory=set)
    error: str | None = None
    job: str | None = None
    seconds: float = 0.0
    versions_run: int = 0
    recommendation: Recommendation | None = None

    @property
    def skipped(self) -> bool:
        return bool(self.error and self.error.startswith("skipped"))

    @property
    def ok(self) -> bool:
        if self.error is not None or self.triggered != set(self.case.expected):
            return False
        verdict = self.case.verdict if isinstance(self.case, RealEntry) else None
        return verdict is None or verdict == self.recommendation


def _result(case: SdCase | RealEntry, outcome: KitOutcome, baseline: set[str]) -> CaseResult:
    return CaseResult(
        case,
        outcome.raw - baseline,
        outcome.raw,
        None,
        outcome.job,
        outcome.seconds,
        outcome.versions_run,
        outcome.recommendation,
    )


def run_corpus(
    cfg: MtaConfig,
    data_dir: Path,
    *,
    only: list[str] | None = None,
    with_eicar: bool = False,
    entries: list[RealEntry] | None = None,
) -> list[CaseResult]:
    """One pass: the SD cases (against SD-01) and any real entries (as they are)."""
    try:
        base = run_case(CASES[0], cfg, data_dir)
    except Exception as exc:
        return [CaseResult(CASES[0], error=f"SD-01 baseline failed: {type(exc).__name__}: {exc}")]
    results: list[CaseResult] = []
    for case in CASES:
        if only and case.id not in only and case.id != "SD-01":
            continue
        if case.needs_eicar and not with_eicar:
            results.append(CaseResult(case, error="skipped: needs --with-eicar (test machine only)"))
            continue
        if case.id == "SD-01":
            results.append(_result(case, base, base.raw))
            continue
        try:
            results.append(_result(case, run_case(case, cfg, data_dir), base.raw))
        except Exception as exc:
            results.append(CaseResult(case, error=f"{type(exc).__name__}: {exc}"))
    for entry in entries or []:
        if only and entry.id not in only:
            continue
        try:
            results.append(_result(entry, run_kit(entry.kit, cfg, data_dir), set()))
        except Exception as exc:
            results.append(CaseResult(entry, error=f"{type(exc).__name__}: {exc}"))
    return results


@dataclass(frozen=True)
class Metrics:
    cases: int
    agreement: float  # cases matching exactly (checks, and the verdict for real entries) / cases
    recall: float | None  # expected defects found / expected defects
    false_positive_rate: float  # cases with an unexpected finding / cases
    determinism: float | None  # cases with identical not-green sets in every pass / cases (>= 2 passes)
    max_minutes_per_version: float
    mean_minutes_per_version: float
    passes: int


def measure(passes: list[list[CaseResult]]) -> Metrics:
    first = [r for r in passes[0] if not r.skipped]
    counted = [r for r in first if r.error is None]
    expected = sum(len(r.case.expected) for r in counted)
    found = sum(len(r.triggered & set(r.case.expected)) for r in counted)
    unexpected = [r for r in counted if r.triggered - set(r.case.expected)]
    stable = None
    if len(passes) > 1:
        by_case = [{r.case.id: r.raw for r in p if not r.skipped and r.error is None} for p in passes]
        ids = set.intersection(*(set(d) for d in by_case))
        same = [i for i in ids if all(d[i] == by_case[0][i] for d in by_case)]
        stable = len(same) / len(ids) if ids else None
    per_version = [r.seconds / 60 / max(1, r.versions_run) for p in passes for r in p if r.error is None]
    return Metrics(
        cases=len(first),
        agreement=sum(r.ok for r in first) / len(first) if first else 0.0,
        recall=found / expected if expected else None,
        false_positive_rate=len(unexpected) / len(counted) if counted else 0.0,
        determinism=stable,
        max_minutes_per_version=max(per_version, default=0.0),
        mean_minutes_per_version=sum(per_version) / len(per_version) if per_version else 0.0,
        passes=len(passes),
    )
