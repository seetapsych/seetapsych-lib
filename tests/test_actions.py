"""Offline regression tests for installer output forwarding."""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import threading
from typing import IO, Any
from unittest.mock import Mock

import pytest

from seetapsych_lib.runtime import actions


@pytest.mark.parametrize("text_only", [False, True])
def test_tee_pipe_forwards_before_eof(text_only: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    read_fd, write_fd = os.pipe()
    src = io.open(read_fd, "rb")
    writer = io.open(write_fd, "wb", buffering=0)
    output = io.BytesIO()
    dst: IO[str] = io.StringIO() if text_only else io.TextIOWrapper(output, encoding="utf-8")
    captured = io.BytesIO()
    flushed = threading.Event()
    original_flush = dst.flush

    def flush() -> None:
        original_flush()
        flushed.set()

    monkeypatch.setattr(dst, "flush", flush)
    thread = threading.Thread(target=actions._tee_pipe, args=(src, dst, captured), daemon=True)
    thread.start()
    try:
        for chunk in (b"Downloading 10%\r", b"Downloading 20%"):
            flushed.clear()
            writer.write(chunk)
            assert flushed.wait(5), "Output was buffered while the pipe was still open"
        expected = b"Downloading 10%\rDownloading 20%"
        assert captured.getvalue() == expected
        if text_only:
            assert isinstance(dst, io.StringIO)
            assert dst.getvalue() == expected.decode()
        else:
            assert output.getvalue() == expected
    finally:
        writer.close()
        thread.join(timeout=5)
        dst.close()
    assert not thread.is_alive()
    assert src.closed
    assert not captured.closed


def test_tee_pipe_captures_large_binary_output() -> None:
    payload = bytes(range(256)) * 1024
    src = io.BytesIO(payload)
    output = io.BytesIO()
    captured = io.BytesIO()
    with io.TextIOWrapper(output, encoding="utf-8") as dst:
        actions._tee_pipe(src, dst, captured)
        assert output.getvalue() == payload
    assert captured.getvalue() == payload
    assert src.closed


def test_tee_pipe_decodes_split_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = "\u4e0b\u8f7d\r\n".encode("utf-8")
    src = io.BytesIO(payload)
    read1 = src.read1
    monkeypatch.setattr(src, "read1", lambda size: read1(1))
    monkeypatch.setattr(actions, "_get_locale_encoding", lambda: "gbk")
    dst = io.StringIO()
    captured = io.BytesIO()

    actions._tee_pipe(src, dst, captured)

    assert dst.getvalue() == payload.decode("utf-8")
    assert captured.getvalue() == payload


@pytest.mark.parametrize("missing", [False, True])
def test_tee_pipe_drains_without_usable_destination(missing: bool) -> None:
    dst = None if missing else io.StringIO()
    if dst is not None:
        dst.close()
    payload = b"installation failed\n" * 10000
    src = io.BytesIO(payload)
    captured = io.BytesIO()

    actions._tee_pipe(src, dst, captured)

    assert captured.getvalue() == payload
    assert src.closed


@pytest.mark.parametrize("returncode", [0, 7])
def test_install_requirements_streams_and_reports_stderr(returncode: int, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = "Downloading 10%\rDownloading 20%\ninstaller diagnostic \u4e2d\u6587\n"
    script = f"import sys; sys.stderr.buffer.write({payload.encode()!r}); sys.stderr.flush(); sys.exit({returncode})"
    monkeypatch.setenv("PYTHONIOENCODING", "gbk")
    monkeypatch.setattr(actions, "package_manager", lambda: ("uv", [sys.executable, "-u", "-c", script], {}))
    dst = io.StringIO()
    monkeypatch.setattr(sys, "stderr", dst)

    if returncode:
        with pytest.raises(RuntimeError) as exc:
            actions.install_requirements(["example-package>=1"])
        assert payload in str(exc.value)
        assert "exit code 7" in str(exc.value)
        assert "example-package>=1" in str(exc.value)
        assert "Failed to execute" not in str(exc.value)
    else:
        actions.install_requirements(["example-package>=1"])

    assert payload in dst.getvalue()


@pytest.mark.parametrize("encoding", ["utf-8", "gbk"])
def test_decode_stderr_tries_strict_fallbacks(encoding: str, monkeypatch: pytest.MonkeyPatch) -> None:
    text = "\u4e2d\u6587"
    monkeypatch.setattr(actions, "_get_locale_encoding", lambda: "gbk")
    assert actions._decode_stderr(text.encode(encoding)) == text


def test_decode_stderr_keeps_explicit_encoding() -> None:
    raw = b"\xc2\xa3"
    assert actions._decode_stderr(raw, "cp1252") == "\u00c2\u00a3"
    assert actions._decode_stderr(b"\xff", "utf-8") == "\ufffd"


def test_decode_stderr_replaces_only_after_fallbacks_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(actions, "_get_locale_encoding", lambda: "ascii")
    assert actions._decode_stderr(b"\xff") == "\ufffd"


@pytest.mark.parametrize(
    ("source", "destination", "expected"),
    [
        ("utf-8", "gbk", "\u4e2d\u6587\r"),
        ("gbk", "utf-8", "\u4e2d\u6587\r"),
        ("utf-8", "ascii", r"\u4e2d\u6587" + "\r"),
    ],
)
def test_tee_pipe_transcodes_only_for_destination(
    source: str, destination: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = "\u4e2d\u6587\r".encode(source)
    src = io.BytesIO(payload)
    read1 = src.read1
    monkeypatch.setattr(src, "read1", lambda size: read1(1))
    captured = io.BytesIO()
    output = io.BytesIO()

    with io.TextIOWrapper(output, encoding=destination) as dst:
        actions._tee_pipe(src, dst, captured, source)
        assert output.getvalue().decode(destination) == expected
    assert captured.getvalue() == payload


@pytest.mark.parametrize("configured", [None, "", ":replace", "gbk:replace"])
def test_python_output_env_preserves_explicit_codec(configured: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    if configured is None:
        monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    else:
        monkeypatch.setenv("PYTHONIOENCODING", configured)
    env, encoding = actions._python_output_env()
    assert encoding == ("gbk" if configured == "gbk:replace" else "utf-8")
    assert env["PYTHONIOENCODING"] == (configured if configured == "gbk:replace" else "utf-8" + (configured or ""))
    assert os.environ.get("PYTHONIOENCODING") == configured


@pytest.mark.parametrize("configured", [None, "gbk:replace"])
@pytest.mark.parametrize("pm_cmd", [[sys.executable, "-m", "pip"], ["custom-pip"]])
def test_install_pip_uses_source_encoding(
    configured: str | None, pm_cmd: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    if configured is None:
        monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    else:
        monkeypatch.setenv("PYTHONIOENCODING", configured)
    payload = "Downloading \u4e2d\u6587\n"
    script = f"import sys; sys.stderr.write({ascii(payload)}); sys.stderr.flush(); sys.exit(7)"
    popen = subprocess.Popen

    def run_child(cmd: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        assert cmd == [*pm_cmd, "install", "example-package"]
        assert kwargs["env"]["PYTHONIOENCODING"] == (configured or "utf-8")
        return popen([sys.executable, "-u", "-c", script], **kwargs)

    monkeypatch.setattr(actions, "package_manager", lambda: ("pip", pm_cmd, {}))
    monkeypatch.setattr(actions.subprocess, "Popen", run_child)
    dst = io.StringIO()
    monkeypatch.setattr(sys, "stderr", dst)

    with pytest.raises(RuntimeError) as exc:
        actions.install_requirements(["example-package"])

    assert payload in str(exc.value).replace("\r\n", "\n")
    assert payload in dst.getvalue().replace("\r\n", "\n")


@pytest.mark.parametrize("configured", [None, "gbk:replace"])
def test_get_pip_version_decodes_only_stdout(configured: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    if configured is None:
        monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    else:
        monkeypatch.setenv("PYTHONIOENCODING", configured)
    text = "pip 25 from C:/\u4e2d\u6587/site-packages\n"
    encoding = "gbk" if configured else "utf-8"
    run = Mock(return_value=subprocess.CompletedProcess([], 0, text.encode(encoding), b"\xff"))
    monkeypatch.setattr(actions.subprocess, "run", run)

    assert actions.get_pip_version() == text.strip()
    assert not run.call_args.kwargs.get("text")
    assert run.call_args.kwargs["env"]["PYTHONIOENCODING"] == (configured or "utf-8")


def test_get_uv_version_decodes_only_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(return_value=subprocess.CompletedProcess([], 0, b"uv 0.8.0\n", b"\xff"))
    monkeypatch.setattr(actions.subprocess, "run", run)
    assert actions.get_uv_version("uv") == "uv 0.8.0"
    assert not run.call_args.kwargs.get("text")


def test_package_manager_prefers_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(actions, "find_uv", lambda: "custom-uv")
    monkeypatch.setattr(actions, "get_uv_version", lambda path: "uv 0.8.0")
    pip_version = Mock()
    bootstrap = Mock()
    monkeypatch.setattr(actions, "get_pip_version", pip_version)
    monkeypatch.setattr(actions.ensurepip, "bootstrap", bootstrap)

    assert actions.package_manager() == ("uv", ["custom-uv", "pip"], {"UV_TORCH_BACKEND": "auto"})
    pip_version.assert_not_called()
    bootstrap.assert_not_called()


@pytest.mark.parametrize("pip_available", [False, True])
def test_package_manager_falls_back_to_pip(pip_available: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(actions, "find_uv", lambda: None)
    monkeypatch.setattr(actions, "get_pip_version", lambda: "pip 25")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if pip_available else None)
    bootstrap = Mock()
    monkeypatch.setattr(actions.ensurepip, "bootstrap", bootstrap)

    assert actions.package_manager() == ("pip", [sys.executable, "-m", "pip"], {})
    assert bootstrap.call_count == (0 if pip_available else 1)
