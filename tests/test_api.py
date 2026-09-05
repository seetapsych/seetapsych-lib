# -*- coding: utf-8 -*-

"""Contract-level tests for the public ``seetapsych_lib.api`` surface.

These tests intentionally avoid exercising *any* concrete package so the
suite is stable across library versions — they only pin the abstract API
contracts (class shapes, constructor signatures, attribute types,
exception hierarchies, and device string parsing). Any breaking change to
the public API should cause at least one test here to fail, alerting the
downstream consumer to a rebase/upgrade requirement.
"""

from pathlib import Path
from typing import Any

import pytest

import seetapsych_lib.api as api
from seetapsych_lib.api import (
    Device,
    Error,
    Instance,
    MissingModelError,
    Model,
    Package,
    UsageModel,
)

# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------

_EXPECTED_ALL = {
    "Device",
    "Error",
    "MissingModelError",
    "Instance",
    "Model",
    "UsageModel",
    "Package",
}


def test_api_exports_are_stable() -> None:
    """The ``__all__`` list must stay byte-identical across patch/minor releases."""
    assert set(api.__all__) == _EXPECTED_ALL, f"Unexpected api.__all__ diff: {set(api.__all__) ^ _EXPECTED_ALL}"
    for name in _EXPECTED_ALL:
        obj = getattr(api, name)
        assert obj is not None, f"{name!r} is not reachable via seetapsych_lib.api"


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_error_base_inherits_from_exception() -> None:
    """The common API base error must remain a plain :class:`Exception` subclass."""
    assert issubclass(Error, Exception)


def test_missing_model_error_inherits_from_api_error() -> None:
    """MissingModelError must be catchable via the public ``api.Error`` clause."""
    assert issubclass(MissingModelError, Error)
    with pytest.raises(Error):
        raise MissingModelError("dummy")


def test_errors_are_throwable_with_message() -> None:
    """Error subclasses must accept a free-form string message."""
    msg = "cache entry is missing"
    try:
        raise MissingModelError(msg)
    except MissingModelError as exc:
        assert msg in str(exc)
        return
    pytest.fail("MissingModelError was not raised")


# ---------------------------------------------------------------------------
# Device descriptor
# ---------------------------------------------------------------------------


class TestDevice:
    """Pin every supported construction shape of the :class:`Device` descriptor."""

    def test_default_constructor_is_cpu(self) -> None:
        d = Device()
        assert d.type == "cpu"
        assert d.index is None

    def test_explicit_cpu_string(self) -> None:
        d = Device("CPU")
        assert d.type == "cpu"
        assert d.index is None

    def test_bare_cuda_string(self) -> None:
        d = Device("cuda")
        assert d.type == "cuda"
        assert d.index is None

    def test_gpu_alias_is_mapped_to_cuda(self) -> None:
        d = Device("gpu")
        assert d.type == "cuda"

    def test_colon_index_suffix_splits_type_and_index(self) -> None:
        d = Device("cuda:1")
        assert d.type == "cuda"
        assert d.index == 1

    @pytest.mark.parametrize(
        ("spec", "expected_type", "expected_index"),
        [
            ("cuda:0", "cuda", 0),
            ("CUDA:3", "cuda", 3),
            (" cuda:2 ", "cuda", 2),
            ("cuda : 2", "cuda", 2),
            ("  CUDA  :  7  ", "cuda", 7),
        ],
    )
    def test_various_colon_forms(self, spec: str, expected_type: str, expected_index: int) -> None:
        """Outer whitespace / case / colon-adjacent spaces are all tolerated."""
        d = Device(spec)
        assert d.type == expected_type
        assert d.index == expected_index

    def test_constructor_index_arg_is_used_when_no_colon_suffix(self) -> None:
        d = Device("cuda", device_index=4)
        assert d.index == 4

    def test_colon_suffix_overrides_none_index_argument(self) -> None:
        d = Device("cuda:2", device_index=None)
        assert d.index == 2

    def test_index_argument_beats_colon_suffix_when_explicit(self) -> None:
        """An explicit ``device_index`` argument always wins over the colon suffix."""
        d = Device("cuda:2", device_index=5)
        assert d.index == 5

    def test_empty_string_defaults_to_cpu(self) -> None:
        d = Device("   ")
        assert d.type == "cpu"

    def test_str_roundtrip_cpu(self) -> None:
        assert str(Device("cpu")) == "cpu"

    def test_str_roundtrip_cuda0(self) -> None:
        assert str(Device("cuda:0")) == "cuda:0"

    def test_str_cpu_never_has_index_suffix(self) -> None:
        d = Device("cpu", device_index=0)
        assert str(d) == "cpu"

    def test_repr_contains_type_and_index(self) -> None:
        r = repr(Device("cuda:2"))
        assert "type='cuda'" in r
        assert "index=2" in r

    def test_repr_cpu_has_no_index_field(self) -> None:
        r = repr(Device("cpu"))
        assert "index" not in r


# ---------------------------------------------------------------------------
# Abstract model contracts
# ---------------------------------------------------------------------------


class _ConcreteModel(Model):
    def __init__(self, path: str | None = None, meta: dict[str, Any] | None = None):
        self._path = path
        self._meta = dict(meta) if meta else {}

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._meta)

    def exists(self) -> bool:
        return self._path is not None and Path(self._path).exists()

    def cache(self) -> str:
        if self._path is None:
            raise MissingModelError("No cache path set on dummy model")
        return self._path


class _ConcreteUsageModel(UsageModel):
    def __init__(self, usage_tag: str, path: str = "/tmp/dummy"):
        self._usage = usage_tag
        self._path = path

    @property
    def usage(self) -> str:
        return self._usage

    @property
    def metadata(self) -> dict[str, Any]:
        return {"usage": self._usage}

    def exists(self) -> bool:
        return True

    def cache(self) -> str:
        return self._path


def test_model_is_abstract_and_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        Model()  # type: ignore[abstract]


def test_usage_model_is_abstract_and_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        UsageModel()  # type: ignore[abstract]


def test_concrete_model_obeys_contract() -> None:
    m = _ConcreteModel(path=None, meta={"key": 1})
    assert m.metadata == {"key": 1}
    assert m.exists() is False
    with pytest.raises(MissingModelError):
        m.cache()


def test_model_metadata_is_mutable_copy_not_internal_ref() -> None:
    m = _ConcreteModel(meta={"counter": 0})
    copy = m.metadata
    copy["counter"] += 100
    assert m.metadata["counter"] == 0


def test_usage_model_extends_model_with_usage_property() -> None:
    um = _ConcreteUsageModel(usage_tag="detector", path="/x")
    assert issubclass(type(um), Model)
    assert um.usage == "detector"
    assert um.cache() == "/x"


# ---------------------------------------------------------------------------
# Abstract Instance contract
# ---------------------------------------------------------------------------


class _ConcreteInstance(Instance):
    def __init__(self, tag: str = "tag"):
        self._tag = tag
        self._reset_calls = 0
        self._disposed = False

    def inference(self, **inputs: Any) -> Any:
        if self._disposed:
            raise Error("Already disposed")
        return {k: v for k, v in inputs.items()}

    def reset(self) -> None:
        self._reset_calls += 1

    def dispose(self) -> None:
        self._disposed = True


def test_instance_is_abstract() -> None:
    with pytest.raises(TypeError):
        Instance()  # type: ignore[abstract]


def test_instance_lifetime_methods() -> None:
    inst = _ConcreteInstance()
    out = inst.inference(image="frame-1", threshold=0.5)
    assert out == {"image": "frame-1", "threshold": 0.5}

    inst.reset()
    inst.reset()
    assert inst._reset_calls == 2

    inst.dispose()
    with pytest.raises(Error):
        inst.inference(image="frame-2")


# ---------------------------------------------------------------------------
# Abstract Package factory contract
# ---------------------------------------------------------------------------


class _ConcretePackage(Package):
    def create(
        self,
        *,
        models: list[UsageModel],
        parameters: dict[str, Any],
        device: Device | None,
        **kwargs: Any,
    ) -> Instance:
        tags = [m.usage for m in models]
        _ = parameters
        _ = device
        _ = kwargs
        return _ConcreteInstance(tag="+".join(tags))


def test_package_is_abstract() -> None:
    with pytest.raises(TypeError):
        Package()  # type: ignore[abstract]


def test_package_create_signature_and_return_type() -> None:
    pkg = _ConcretePackage()
    models: list[UsageModel] = [
        _ConcreteUsageModel(usage_tag="a"),
        _ConcreteUsageModel(usage_tag="b"),
    ]
    inst = pkg.create(models=models, parameters={"k": "v"}, device=Device("cuda:1"))
    assert isinstance(inst, Instance)
    assert isinstance(inst, _ConcreteInstance)


def test_package_create_accepts_none_device() -> None:
    pkg = _ConcretePackage()
    inst = pkg.create(models=[], parameters={}, device=None)
    assert isinstance(inst, Instance)


def test_package_create_allows_extra_kwargs_forwarding_slot() -> None:
    """Package.create must accept ``**kwargs`` without error per the API docstring."""
    pkg = _ConcretePackage()
    inst = pkg.create(
        models=[],
        parameters={},
        device=Device(),
        memory_budget_mb=1024,
    )
    assert isinstance(inst, Instance)
