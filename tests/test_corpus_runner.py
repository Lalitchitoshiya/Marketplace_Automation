"""Step 15: real corpus entries, accuracy metrics (agreement, recall, false positives, determinism, time)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mta.cli.app import app
from mta.config import MtaConfig
from mta.corpus import runner
from mta.corpus.runner import CaseResult, KitOutcome, RealEntry, load_entries, measure
from mta.corpus.sd import CASES
from mta.models import Recommendation


def _entry(id_: str, expected: set[str], verdict: Recommendation | None = None) -> RealEntry:
    return RealEntry(id_, id_, Path("kit"), frozenset(expected), verdict)


def test_load_entries(tmp_path: Path) -> None:
    (tmp_path / "acme-2.3" / "kit").mkdir(parents=True)
    (tmp_path / "acme-2.3" / "expected.yaml").write_text(
        "title: Acme 2.3\nverdict: RECOMMEND_REJECT\nexpected_checks: [CMD-002, RUN-002]\n", encoding="utf-8"
    )
    (tmp_path / "plain" / "kit").mkdir(parents=True)
    (tmp_path / "plain" / "expected.yaml").write_text("{}\n", encoding="utf-8")
    (tmp_path / "notes").mkdir()
    entries = {e.id: e for e in load_entries(tmp_path)}
    assert set(entries) == {"acme-2.3", "plain"}
    assert entries["acme-2.3"].verdict is Recommendation.REJECT
    assert entries["acme-2.3"].expected == {"CMD-002", "RUN-002"}
    assert entries["plain"].verdict is None and entries["plain"].expected == frozenset()


def test_real_entry_needs_the_verdict_too() -> None:
    entry = _entry("a", {"CMD-002"}, Recommendation.REJECT)
    assert CaseResult(entry, {"CMD-002"}, {"CMD-002"}, recommendation=Recommendation.REJECT).ok
    assert not CaseResult(entry, {"CMD-002"}, {"CMD-002"}, recommendation=Recommendation.NEEDS_HUMAN).ok


def test_measure() -> None:
    sd03 = next(c for c in CASES if c.id == "SD-03")
    sd04 = next(c for c in CASES if c.id == "SD-04")
    sd10 = next(c for c in CASES if c.id == "SD-10")
    first = [
        CaseResult(sd03, {"CMD-002", "RUN-002"}, {"CMD-002", "RUN-002"}, seconds=120, versions_run=1),
        CaseResult(sd04, {"CMD-004", "PKG-005"}, {"CMD-004", "PKG-005"}, seconds=240, versions_run=2),
        CaseResult(sd10, set(), set(), seconds=60, versions_run=1),  # missed SIG-001
        CaseResult(CASES[10], error="skipped: needs --with-eicar"),
    ]
    second = [CaseResult(r.case, r.triggered, set(r.raw), r.error, seconds=60, versions_run=1) for r in first]
    second[0] = CaseResult(sd03, {"CMD-002"}, {"CMD-002"}, seconds=60, versions_run=1)  # unstable
    m = measure([first, second])
    assert m.cases == 3 and m.passes == 2
    assert m.agreement == pytest.approx(1 / 3)  # only SD-03 matches exactly in the first pass
    assert m.recall == pytest.approx(3 / 4)  # CMD-002, RUN-002, CMD-004 of 4 expected
    assert m.false_positive_rate == pytest.approx(1 / 3)  # SD-04's PKG-005
    assert m.determinism == pytest.approx(2 / 3)
    assert m.max_minutes_per_version == pytest.approx(2.0)
    assert measure([first]).determinism is None


def test_run_corpus_with_real_entries(
    cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "run_case", lambda case, c, d: KitOutcome({"SIG-002"}, None, "job", 30, 1))
    monkeypatch.setattr(
        runner, "run_kit", lambda kit, c, d: KitOutcome({"CMD-002"}, Recommendation.NEEDS_HUMAN, "job", 30, 1)
    )
    entry = _entry("real-1", {"CMD-002"}, Recommendation.REJECT)
    results = runner.run_corpus(cfg, tmp_path, only=["real-1"], entries=[entry])
    assert [r.case.id for r in results] == ["SD-01", "real-1"]
    real = results[1]
    assert real.triggered == {"CMD-002"}  # real entries are not measured against SD-01
    assert not real.ok  # MTA says NEEDS_HUMAN, the reviewers rejected: no agreement


def test_baseline_failure_is_reported(
    cfg: MtaConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> KitOutcome:
        raise FileNotFoundError("Sd01Clean.dll missing: run `mta corpus build`")

    monkeypatch.setattr(runner, "run_case", broken)
    results = runner.run_corpus(cfg, tmp_path)
    assert len(results) == 1 and "SD-01 baseline failed" in (results[0].error or "")


def test_cli_corpus_run_writes_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(cfg: MtaConfig, data: Path, **_: object) -> list[CaseResult]:
        return [CaseResult(CASES[0], set(), {"SIG-002"}, seconds=30, versions_run=1)]

    monkeypatch.setattr("mta.cli.corpus_cmds.run_corpus", fake)
    out = tmp_path / "m.json"
    result = CliRunner().invoke(app, ["corpus", "run", "--repeat", "2", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "determinism: 1.000" in result.output and "CORPUS OK" in result.output
    assert out.is_file()
