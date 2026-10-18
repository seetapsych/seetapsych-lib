"""Offline tests for setup index overrides."""

import sys
from unittest.mock import Mock

import pytest

from seetapsych_lib import schema
from seetapsych_lib.manager import cli


@pytest.mark.parametrize(
    ("options", "index_url", "extra_index_urls"),
    [
        ([], None, None),
        (["--index-url", "https://primary.example/simple"], "https://primary.example/simple", None),
        (["--extra-index-url", "https://extra.example/simple"], None, ["https://extra.example/simple"]),
        (
            [
                "--index-url",
                "https://primary.example/simple",
                "--extra-index-url",
                "https://first.example/simple",
                "--extra-index-url",
                "https://second.example/simple",
            ],
            "https://primary.example/simple",
            ["https://first.example/simple", "https://second.example/simple"],
        ),
    ],
)
def test_setup_forwards_index_options(
    options: list[str],
    index_url: str | None,
    extra_index_urls: list[str] | None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    modules = [
        schema.Module(module=schema.ModuleSpec(uid=uid, requirements=["example-package>=1"]))
        for uid in ("test-index-first", "test-index-second")
    ]
    monkeypatch.setattr(cli, "_iter_default_modules", lambda: [(module, []) for module in modules])
    install = Mock()
    monkeypatch.setattr(cli, "install_module_requirements", install)
    monkeypatch.setattr(sys, "argv", ["seetapsych-manager", "setup", *options])

    cli.main()

    assert install.call_count == len(modules)
    for call, module in zip(install.call_args_list, modules, strict=True):
        assert call.args == (module.module,)
        assert call.kwargs == {"index_url": index_url, "extra_index_urls": extra_index_urls}
    assert "Setup summary:" in capsys.readouterr().out
