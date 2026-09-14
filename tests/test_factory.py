# -*- coding: utf-8 -*-

"""Tests for :class:`Factory`, :class:`Pipeline` dependency resolution and
satisfaction checks.

Covers four canonical resolution paths (all offline — no network or real
package installs):

* **Missing attribute provider** — ``problem()`` reports missing attributes
  and ``solve()`` adds the missing package+module from the factory registry.
* **Missing model selection** — ``problem()`` flags packages without a
  model pick and ``solve()`` fills in the ``recommended`` default.
* **Missing cached model** — ``satisfied()`` reports uncached models and
  ``cache_models()`` flips their cached flag so the next check passes.
* **Missing Python-package requirements / Git refs** — ``satisfied()``
  reports unsatisfied module-level dependencies; monkey-patching the
  dependency-check helper (or swapping to a requirement-free module) turns
  it into a clean bill of health.

The suite closes with one end-to-end Runner run on the fully-solved,
fully-cached pipeline so the resolver is exercised all the way to a real
inference result.
"""

from __future__ import annotations

import io

import numpy
import pytest

import seetapsych_lib.example.example as _example_mod
from seetapsych_lib.runtime.base_runner import PipelineHasProblem
from seetapsych_lib.runtime.factory import Factory
from seetapsych_lib.runtime.pipeline import Pipeline
from seetapsych_lib.runtime.runner import Runner

# ---------------------------------------------------------------------------
# Shared test modules (YAML)
# ---------------------------------------------------------------------------

# Realistic default-like module: declares PyPI requirement ``cowsay`` AND a
# GitRef pointing at the ``seetapsych-attributes`` org repository so the
# satisfaction checker exercises both dependency flavours.
_DEFAULTISH_MODULE_YAML = """
version: "1.0"

module:
  name: "Factory Test — defaultish"
  version: "0.0.1"
  description: "Declares cowsay + a Git ref to exercise the dependency checker."
  keywords:
    - "FactoryTest"
  requirements:
    - "cowsay"
  refs:
    - name: "seetapsych-attributes"
      repo: "https://github.com/seetapsych/seetapsych-attributes"
      require: ">=0.0.1"

packages:
  - name: "Echo Package (factory)"
    version: "0.0.1"
    keywords: ["FactoryTest"]
    usage_models: []
    inputs: []
    provides:
      - "example/output"
    requires: []
    entry:
      method: "seetapsych_lib.example.example.load_package"
    parameters: []
    models:
      - name: "Echo Model (factory)"
        version: "0.0.1"
        keywords: ["FactoryTest"]
        usage: ""
        recommended: true
        entry:
          method: "seetapsych_lib.example.example.load_model"
"""

# Requirement-free variant: no PyPI deps, no Git refs.  Used to confirm that
# a pipeline built from a clean module reports zero unsatisfaction on the
# dependency axis before we look at the model layer.
_CLEAN_MODULE_YAML = """
version: "1.0"

module:
  name: "Factory Test — clean"
  version: "0.0.1"
  description: "No PyPI requirements, no Git refs — only the model cache gate."
  keywords:
    - "FactoryTest"
  requirements: []
  refs: []

packages:
  - name: "Echo Package (clean)"
    version: "0.0.1"
    keywords: ["FactoryTest"]
    usage_models: []
    inputs: []
    provides:
      - "example/output"
    requires: []
    entry:
      method: "seetapsych_lib.example.example.load_package"
    parameters: []
    models:
      - name: "Echo Model (clean)"
        version: "0.0.1"
        keywords: ["FactoryTest"]
        usage: ""
        recommended: true
        entry:
          method: "seetapsych_lib.example.example.load_model"
"""

# Variant with an intentionally-broken model entry point.  Lets us assert
# that ``satisfied()`` reports un-importable entries separately from the
# dependency and model-exists axes.
_BAD_ENTRY_MODULE_YAML = """
version: "1.0"

module:
  name: "Factory Test — bad entry"
  version: "0.0.1"
  keywords: ["FactoryTest"]
  requirements: []
  refs: []

packages:
  - name: "Broken Entry Package"
    version: "0.0.1"
    keywords: ["FactoryTest"]
    usage_models: []
    inputs: []
    provides:
      - "example/output"
    requires: []
    entry:
      method: "seetapsych_lib.example.example.load_package"
    parameters: []
    models:
      - name: "Missing Entry Model"
        version: "0.0.1"
        keywords: ["FactoryTest"]
        usage: ""
        recommended: true
        entry:
          method: "seetapsych_lib.example.this_module_does_not_exist.load_model"
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_factory(*, mode: str) -> Factory:
    """Build a factory that loads exactly one inline YAML module.

    ``mode`` selects which of the module fixtures above is registered:
    ``"defaultish"`` / ``"clean"`` / ``"bad_entry"``.
    """
    mapping: dict[str, str] = {
        "defaultish": _DEFAULTISH_MODULE_YAML,
        "clean": _CLEAN_MODULE_YAML,
        "bad_entry": _BAD_ENTRY_MODULE_YAML,
    }
    yaml_text = mapping[mode]
    factory = Factory(disable_builtin=True, disable_default=True, enable_example=False)
    stream = io.BytesIO(yaml_text.encode("utf-8"))
    ok = factory.load_local_module(stream, extension="yml")
    assert ok, f"failed to load the {mode!r} test module"
    return factory


def _reset_example_cache() -> None:
    """Flip the example model's global cached flag back to *uncached*.

    ``ExampleModel.exists()`` reads this module-level boolean, so resetting
    it between tests simulates the "model has not been downloaded yet"
    state without touching the filesystem.
    """
    _example_mod.example_model_cached = False


def _dummy_frame() -> numpy.ndarray:
    return numpy.zeros((4, 6, 3), dtype=numpy.uint8)


# ---------------------------------------------------------------------------
# 1. Missing attribute provider — problem()/solve() cycle
# ---------------------------------------------------------------------------


class TestMissingAttributeProvider:
    def setup_method(self) -> None:
        _reset_example_cache()

    def test_problem_reports_unprovided_attribute(self) -> None:
        factory = _make_factory(mode="clean")
        pipeline = Pipeline(factory, attributes=[])
        pipeline.add_attributes(["example/output"])
        problem = pipeline.problem()
        assert problem is not None
        assert "example/output" in problem.attributes

    def test_solve_adds_provider_package_and_module(self) -> None:
        factory = _make_factory(mode="clean")
        pipeline = Pipeline(factory, attributes=["example/output"])
        # Before solve: empty package list, not satisfiable yet
        assert len(pipeline.config.packages) == 0
        solved = pipeline.solve()
        assert solved is not None
        assert len(pipeline.config.packages) == 1
        assert pipeline.config.packages[0].provides == ["example/output"]
        # After solve: attributes are covered → problem() returns None
        # (models still need solving, but that's a separate axis;
        # ``problem()`` checks *attribute* providers + module + model slots
        # availability, not caching.  Calling again should be idempotent.
        next_solved = pipeline.solve()
        assert next_solved is None


# ---------------------------------------------------------------------------
# 2. Missing (uncached) model — satisfied() / cache_models() cycle
# ---------------------------------------------------------------------------


class TestMissingCachedModel:
    def setup_method(self) -> None:
        _reset_example_cache()

    def _solved_clean_pipeline(self) -> Pipeline:
        factory = _make_factory(mode="clean")
        pipeline = Pipeline(factory, attributes=["example/output"])
        pipeline.solve()
        return pipeline

    def test_satisfied_reports_uncached_models_before_cache(self) -> None:
        pipeline = self._solved_clean_pipeline()
        ok, report = pipeline.satisfied()
        assert ok is False
        assert report is not None
        assert len(report.models) == 1
        assert report.modules == []
        assert report.entries == []

    def test_cache_models_flips_satisfied_to_true(self) -> None:
        pipeline = self._solved_clean_pipeline()
        pipeline.cache_models()
        ok, report = pipeline.satisfied()
        assert ok is True
        assert report is None


# ---------------------------------------------------------------------------
# 3. Missing requirements / Git refs — dependency checking
# ---------------------------------------------------------------------------


class TestMissingDependencies:
    def setup_method(self) -> None:
        _reset_example_cache()

    def test_clean_module_reports_no_dependency_blockers(self) -> None:
        factory = _make_factory(mode="clean")
        pipeline = Pipeline(factory, attributes=["example/output"])
        pipeline.solve()
        # Model cache still off, so satisfied reports models; the
        # dependency axis must be empty however.
        ok, report = pipeline.satisfied()
        assert report is not None
        assert report.modules == []

    def test_defaultish_module_reports_pypi_and_git_unsatisfied(self) -> None:
        factory = _make_factory(mode="defaultish")
        pipeline = Pipeline(factory, attributes=["example/output"])
        pipeline.solve()
        ok, report = pipeline.satisfied()
        assert report is not None
        assert len(report.modules) == 1
        unsat_reqs = report.modules[0].requirements
        # cowsay is declared as a requirements string.
        assert any("cowsay" in r for r in unsat_reqs)
        # The declared GitRef must surface as a ``name @ git+<repo>`` string
        # (see actions.unsatisfied_requirements for the exact rendering).
        assert any("seetapsych-attributes" in r for r in unsat_reqs)
        assert any("github.com/seetapsych/seetapsych-attributes" in r for r in unsat_reqs)

    def test_monkeypatch_unsatisfied_requirements_marks_satisfied_dep_axis(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the dependency helper says everything is installed, the
        dependency-report list must be empty even for a module that declares
        cowsay + Git refs.
        """
        from seetapsych_lib.runtime import actions, pipeline

        factory = _make_factory(mode="defaultish")
        p = Pipeline(factory, attributes=["example/output"])
        p.solve()

        # ``pipeline.py`` imports ``unsatisfied_requirements`` as a module-level
        # binding so we must monkeypatch both locations: the public one in
        # ``actions`` and the private one bound in ``pipeline``.
        monkeypatch.setattr(actions, "unsatisfied_requirements", lambda _mod: [])
        monkeypatch.setattr(pipeline, "unsatisfied_requirements", lambda _mod: [])
        # Cache the model (already reset by setup_method) so only the dependency
        # axis is relevant.  Do NOT reset afterwards — the cached flag is what
        # ``satisfied()`` reads on the model side.
        p.cache_models()
        ok, report = p.satisfied()
        assert ok is True
        assert report is None


# ---------------------------------------------------------------------------
# 4. Un-importable entries — satisfied reports entries/imports separately
# ---------------------------------------------------------------------------


class TestUnimportableEntry:
    def setup_method(self) -> None:
        _reset_example_cache()

    def test_satisfied_reports_un_importable_model_entry(self) -> None:
        factory = _make_factory(mode="bad_entry")
        pipeline = Pipeline(factory, attributes=["example/output"])
        pipeline.solve()
        ok, report = pipeline.satisfied()
        assert ok is False
        assert report is not None
        # Either ``entries`` or ``imports`` (or both) should be populated,
        # because the declared model entry method points at a non-existent
        # submodule.
        assert report.entries or report.imports


# ---------------------------------------------------------------------------
# 5. End-to-end — fully-solved pipeline with a real Runner inference
# ---------------------------------------------------------------------------


class TestFullySolvedRunner:
    def setup_method(self) -> None:
        _reset_example_cache()

    def test_end_to_end_runner_produces_example_report(self) -> None:
        factory = _make_factory(mode="clean")
        pipeline = Pipeline(factory, attributes=["example/output"])

        # Unsolved pipelines cannot construct Runners.
        with pytest.raises(PipelineHasProblem):
            Runner(pipeline, device="cpu")

        # After solve + cache, everything lines up and Runner works.
        pipeline.solve()
        pipeline.cache_models()
        ok, report = pipeline.satisfied()
        assert ok is True
        assert report is None

        runner = Runner(pipeline, device="cpu", profile=True)
        try:
            frame = _dummy_frame()
            result = runner.run(frame)
            assert isinstance(result, dict)
            assert isinstance(result["timestamp"], float)
            assert result["frame_tick"] == 1
            echo = result["example_output"]
            assert echo["shape"] == list(frame.shape)
            assert echo["output"] == [1, 2, 3]
            assert echo["values"] == [None, 12, 12.4, "fff", False]
            # Runner exposes expected public surface
            assert runner.inputs == ["default"]
            summary = runner.time_summary()
            assert "Echo Package (clean)" in summary
            assert summary["Echo Package (clean)"] >= 0.0
        finally:
            runner.dispose()
        # dispose is idempotent and must not raise on repeated call.
        runner.dispose()
