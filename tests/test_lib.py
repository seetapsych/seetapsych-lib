import importlib
import os
from pathlib import Path

import pytest
import yaml

import seetapsych_lib as pkg
from seetapsych_lib.schema.module import Module


def test_version() -> None:
    print(f"Package: {pkg.__name__}")
    print(f"Version: {pkg.__version__}")
    assert isinstance(pkg.__version__, str)
    assert len(pkg.__version__) > 0


def _collect_module_ymls() -> list[Path]:
    modules_dir = Path(os.path.dirname(__file__)).parent / "seetapsych_lib" / "modules"
    if not modules_dir.is_dir():
        return []
    return sorted(modules_dir.glob("**/*.yml")) + sorted(modules_dir.glob("**/*.yaml"))


def _import_entry_method(entry: object) -> object:
    from seetapsych_lib.schema.module import Entry

    assert isinstance(entry, Entry)
    method: str = entry.method
    if entry.package:
        method = ".".join([entry.package, method])
    assert "." in method, f"Entry method must be qualified: {method}"
    lib_name, func_name = method.rsplit(".", 1)
    lib = importlib.import_module(lib_name)
    func = getattr(lib, func_name)
    assert callable(func), f"{method} is not callable"
    return func


_MODULE_YMLS = _collect_module_ymls()


@pytest.mark.parametrize("yml_path", _MODULE_YMLS, ids=lambda p: p.name)
def test_module_schema_and_entries(yml_path: Path) -> None:
    with open(yml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    module = Module.model_validate(data)
    assert module.version == "1.0"
    for pkg_ in module.packages:
        assert pkg_.entry is not None, f"Package {pkg_.name} has no entry"
        func = _import_entry_method(pkg_.entry)
        assert callable(func), f"Package entry {pkg_.entry.method} is not callable"
        for model in pkg_.models:
            if model.entry is not None:
                func = _import_entry_method(model.entry)
                assert callable(func), f"Model entry {model.entry.method} is not callable"
