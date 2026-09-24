"""Offline checks for decoding device enumeration output."""

import codecs
from unittest.mock import Mock

import pytest

from seetapsych_lib.utils import cuda


@pytest.mark.parametrize(
    ("encoding", "prefix"),
    [
        ("utf-16", b""),
        ("utf-16-le", b""),
        ("utf-16-be", codecs.BOM_UTF16_BE),
        ("utf-8-sig", b""),
        ("gbk", b""),
    ],
)
def test_wmic_fallback_preserves_device_names(encoding: str, prefix: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    device = "NVIDIA GeForce \u4e2d\u6587"
    output = prefix + f"Name\r\r\n{device}\r\r\n".encode(encoding)
    monkeypatch.setattr(cuda.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cuda.locale, "getpreferredencoding", lambda do_setlocale: "gbk")
    monkeypatch.setattr(cuda.pynvml, "nvmlInit", Mock(side_effect=RuntimeError("NVML unavailable")))
    command = Mock(side_effect=[FileNotFoundError("nvidia-smi unavailable"), output])
    monkeypatch.setattr(cuda.subprocess, "check_output", command)

    assert cuda.list_nvidia_devices() == [device]
    assert command.call_count == 2


def test_wmic_fallback_uses_system_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "Name\r\nNVIDIA Caf\u00e9\r\n"
    monkeypatch.setattr(cuda.locale, "getpreferredencoding", lambda do_setlocale: "cp1252")
    assert cuda._decode_wmic_output(text.encode("cp1252")) == text


def test_wmic_fallback_does_not_drop_invalid_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cuda.locale, "getpreferredencoding", lambda do_setlocale: "ascii")
    assert cuda._decode_wmic_output(b"Name\nNVIDIA \xff\n") == "Name\nNVIDIA \ufffd\n"
