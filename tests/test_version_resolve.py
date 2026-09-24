"""Checks for Git text output across source encodings."""

import subprocess
from unittest.mock import Mock

import pytest

from seetapsych_lib import _version_resolve


@pytest.mark.parametrize(
    ("stdout", "returncode", "expected"),
    [(b"r1.2.3-0-gabc1234\n", 0, "r1.2.3-0-gabc1234"), (b"\xff", 0, "\ufffd"), (b"", 0, None), (b"failure", 1, None)],
)
def test_run_git_ignores_diagnostic_encoding(
    stdout: bytes, returncode: int, expected: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Mock(return_value=subprocess.CompletedProcess([], returncode, stdout, b"\xff"))
    monkeypatch.setattr(_version_resolve.subprocess, "run", run)
    monkeypatch.setattr(_version_resolve.locale, "getpreferredencoding", lambda do_setlocale: "ascii")

    assert _version_resolve._run_git("describe") == expected
    assert not run.call_args.kwargs.get("text")
    assert run.call_args.kwargs["stderr"] == subprocess.DEVNULL


def test_run_git_handles_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_version_resolve.subprocess, "run", Mock(side_effect=FileNotFoundError))
    assert _version_resolve._run_git("describe") is None


@pytest.mark.parametrize("system_encoding", ["utf-8", "gbk", "cp1252"])
def test_run_git_accepts_utf8_text(system_encoding: str, monkeypatch: pytest.MonkeyPatch) -> None:
    text = "Update \u4e2d\u6587 documentation\nAuthor: Jos\u00e9"
    run = Mock(return_value=subprocess.CompletedProcess([], 0, (text + "\n").encode("utf-8")))
    monkeypatch.setattr(_version_resolve.subprocess, "run", run)
    monkeypatch.setattr(_version_resolve.locale, "getpreferredencoding", lambda do_setlocale: system_encoding)

    assert _version_resolve._run_git("log", "-1", "--format=%B") == text
    assert run.call_args.args[0][-3:] == ["log", "-1", "--format=%B"]


def test_run_git_falls_back_to_system_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "Update \u4e2d\u6587 documentation"
    run = Mock(return_value=subprocess.CompletedProcess([], 0, text.encode("gbk")))
    monkeypatch.setattr(_version_resolve.subprocess, "run", run)
    monkeypatch.setattr(_version_resolve.locale, "getpreferredencoding", lambda do_setlocale: "gbk")
    assert _version_resolve._run_git("log", "-1", "--format=%B") == text


@pytest.mark.parametrize(
    ("encoding", "raw", "expected"),
    [
        ("cp1252", b"\xc2\xa3", "\u00c2\u00a3"),
        ("utf-16", "\u4e2d\u6587".encode("utf-16"), "\u4e2d\u6587"),
        ("utf-8", b"text \xff", "text \ufffd"),
    ],
)
def test_run_git_honors_explicit_encoding(
    encoding: str, raw: bytes, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Mock(return_value=subprocess.CompletedProcess([], 0, raw))
    monkeypatch.setattr(_version_resolve.subprocess, "run", run)
    assert _version_resolve._run_git("log", "-1", f"--encoding={encoding}", encoding=encoding) == expected
    assert "encoding" not in run.call_args.kwargs
