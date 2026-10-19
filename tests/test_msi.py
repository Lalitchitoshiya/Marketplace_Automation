"""Low-level MSI helpers: log reading, timeout, custom-action classification."""

import subprocess
from pathlib import Path

import pytest

from mta.static.msi import AdminExtractResult, CustomAction, _action_kind, _read_log, msi_admin_extract


@pytest.mark.parametrize(
    ("action_type", "kind"),
    [
        (1, "dll"),
        (2, "exe"),
        (34, "exe"),
        (19, "data"),
        (35, "data"),
        (51, "data"),
        (37, "jscript"),
        (38, "vbscript"),
        (39, "nested_install"),
        (1025, "dll"),
        (4, "unknown"),
    ],
)
def test_action_kind(action_type: int, kind: str) -> None:
    assert _action_kind(action_type) == kind


def test_unknown_kind_counts_as_code() -> None:
    action = CustomAction("X", 4, "unknown", None, None, sequences=["AdminUISequence"])
    assert action.executes_code and action.runs_in_admin_install


def test_read_log_handles_utf16_plain_and_missing(tmp_path: Path) -> None:
    (tmp_path / "u.log").write_bytes("﻿line 1\r\nline 2\r\n".encode("utf-16-le"))
    (tmp_path / "a.log").write_text("a\nb\nc\n", encoding="utf-8")
    assert _read_log(tmp_path / "u.log").endswith("line 2")
    assert _read_log(tmp_path / "a.log", lines=2) == "b\nc"
    assert _read_log(tmp_path / "missing.log") == "(no msiexec log)"


def test_admin_extract_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*_: object, **__: object) -> None:
        raise subprocess.TimeoutExpired("msiexec", 1)

    monkeypatch.setattr(subprocess, "run", slow)
    result = msi_admin_extract(tmp_path / "x.msi", tmp_path / "out", tmp_path / "x.log", 1)
    assert result.exit_code is None
    assert result.environment_problem == "msiexec timed out"
    assert not result.succeeded


def test_result_classification() -> None:
    assert AdminExtractResult(3010, "").succeeded
    assert AdminExtractResult(1625, "").environment_problem == "blocked by system policy"
    assert AdminExtractResult(1603, "").environment_problem is None
