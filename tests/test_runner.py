# -*- coding: utf-8 -*-

"""End-to-end tests for :class:`Runner` and :class:`ParallelRunner`.

Loads a trimmed copy of the library-shipped example module via
:class:`Factory.load_local_module` (builtin and default sources disabled,
only the test-only module is registered) so the suite exercises the real
runtime pipeline without requiring any algorithm download or external pip
dependencies.  A lightweight synthetic frame is passed as the ``"default"``
input; both runners are expected to return the attribute ``"example/output"``
with the echo payload defined in ``seetapsych_lib.example.example``.
"""

from __future__ import annotations

import io

# ---------------------------------------------------------------------------
# Speed hacks: replace the example module's ``time`` binding with a proxy that
# no-ops ``sleep`` while delegating everything else to the real ``time``.  This
# avoids modifying the global standard-library ``time.sleep`` (which pytest and
# the runtime rely on for actual waiting).
# ---------------------------------------------------------------------------
import time as _real_time
from typing import Any

import numpy
import pytest

import seetapsych_lib.example.example as _example_mod
from seetapsych_lib.runtime.base_runner import (
    BaseParallelRunner,
    BaseRunner,
    MissingInputModal,
    PipelineHasProblem,
    TimeSummary,
)
from seetapsych_lib.runtime.factory import Factory
from seetapsych_lib.runtime.parallel_runner import ParallelRunner
from seetapsych_lib.runtime.pipeline import Pipeline
from seetapsych_lib.runtime.runner import Runner


class _TimeProxy:
    def __getattr__(self, _item: str) -> Any:
        return getattr(_real_time, _item)

    @staticmethod
    def sleep(_seconds: float) -> None:  # pragma: no cover - no-op
        return None


_example_mod.time = _TimeProxy()  # type: ignore[assignment]
del _example_mod

# ---------------------------------------------------------------------------
# Module fixture: the example YAML with requirements (cowsay) stripped so the
# test runs on bare environments. The entry methods still point at the same
# ``seetapsych_lib.example.example`` implementations.
# ---------------------------------------------------------------------------

_EXAMPLE_MODULE_YAML = """
version: "1.0"

module:
  name: "Example Module (test)"
  version: "0.0.1"
  description: "This is a test example module"
  keywords:
    - "Test"
    - "Example"
  requirements: []

packages:
  - name: "Example Package (test)"
    version: "0.0.1"
    description: "This is a test example package. Used for runner tests."
    keywords:
      - "Test"
      - "Example"
    usage_models: []
    inputs: []
    provides:
      - "example/output"
    requires: []
    entry:
      method: "seetapsych_lib.example.example.load_package"
    parameters:
      - name: "min_face"
        type: "integer"
        value: 80
      - name: "threshold"
        type: "number"
        value: 0.8
      - name: "object_name"
        type: "string"
        value: "face"
      - name: "scale"
        type: "selection"
        value: "big"
        selection: ["big", "small"]
    models:
      - name: "Example Model (test)"
        version: "0.0.1"
        description: "In-memory example model, never persisted."
        keywords:
          - "Test"
          - "Example"
        usage: ""
        recommended: true
        entry:
          method: "seetapsych_lib.example.example.load_model"
"""


def _build_factory() -> Factory:
    """Create a Factory registering only the test example module."""
    factory = Factory(disable_builtin=True, disable_default=True, enable_example=False)
    # NOTE: ``utils.loader.load`` treats ``bytes`` inputs as file paths (it
    # decodes the bytes and passes them to ``open``).  Wrapping the content in
    # ``BytesIO`` forces the "stream" branch which actually reads the content.
    stream = io.BytesIO(_EXAMPLE_MODULE_YAML.encode("utf-8"))
    ok = factory.load_local_module(stream, extension="yml")
    assert ok, "failed to load the test example module"
    return factory


def _build_pipeline() -> Pipeline:
    """Build, solve, and cache a pipeline requesting the example attribute."""
    factory = _build_factory()
    pipeline = Pipeline(factory, attributes=["example/output"])
    pipeline.solve()
    # ``satisfied()`` in the runner checks model existence via ``exists()``;
    # the example model has no real file so we eagerly call ``cache()`` once
    # to flip its internal "cached" flag before any runner inspects it.
    pipeline.cache_models()
    return pipeline


def _dummy_frame() -> numpy.ndarray:
    """Return a tiny synthetic frame used as the ``default`` input."""
    return numpy.zeros((4, 6, 3), dtype=numpy.uint8)


@pytest.fixture(scope="session")
def factory() -> Factory:
    return _build_factory()


@pytest.fixture(scope="session")
def solved_pipeline() -> Pipeline:
    return _build_pipeline()


@pytest.fixture(scope="session")
def parallel_runner_profiled(solved_pipeline: Pipeline) -> ParallelRunner:
    """Session-scoped profiled ``ParallelRunner`` shared across tests."""
    runner = ParallelRunner(solved_pipeline, device="cpu", profile=True)
    yield runner
    runner.dispose()


@pytest.fixture(scope="session")
def parallel_runner_silent(solved_pipeline: Pipeline) -> ParallelRunner:
    """Session-scoped non-profiled ``ParallelRunner`` shared across tests."""
    runner = ParallelRunner(solved_pipeline, device="cpu", profile=False)
    yield runner
    runner.dispose()


# ---------------------------------------------------------------------------
# Shared behavioural assertions
# ---------------------------------------------------------------------------


def _assert_example_report(report: dict[str, Any], frame: numpy.ndarray, frame_tick: int) -> None:
    """Validate the shape of a report produced by the example package."""
    assert isinstance(report, dict)
    assert "timestamp" in report
    assert isinstance(report["timestamp"], float)
    assert report["frame_tick"] == frame_tick
    assert "example_output" in report
    out = report["example_output"]
    assert out["shape"] == list(frame.shape)
    assert out["output"] == [1, 2, 3]
    assert out["values"] == [None, 12, 12.4, "fff", False]


# ---------------------------------------------------------------------------
# Factory + Pipeline setup tests
# ---------------------------------------------------------------------------


def test_factory_test_module_only_loaded() -> None:
    """The restricted factory must not pull any builtin or default modules."""
    factory = _build_factory()
    sources = factory.loaded_sources()
    assert not sources.get("builtin", []), "builtin modules must not be loaded"
    assert not sources.get("default", []), "default modules must not be loaded"
    assert factory.query_attribute_providers("example/output"), "example/output must be provided"


def test_unsolved_pipeline_raises_on_runner() -> None:
    """Constructing a Runner with an unsolved pipeline raises PipelineHasProblem."""
    factory = _build_factory()
    pipeline = Pipeline(factory, attributes=["example/output"])  # NOTE: no solve()
    with pytest.raises(PipelineHasProblem):
        Runner(pipeline, device="cpu", profile=True)


def test_solved_pipeline_is_satisfied() -> None:
    """The test pipeline must report ready-to-run after solve() + cache_models()."""
    pipeline = _build_pipeline()
    ready, _report = pipeline.satisfied()
    assert ready, f"pipeline unexpectedly unsatisfied: {_report}"


# ---------------------------------------------------------------------------
# Runner (sequential) tests
# ---------------------------------------------------------------------------


class TestRunner:
    def test_inherits_base_runner(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=True)
        try:
            assert isinstance(runner, BaseRunner)
        finally:
            runner.dispose()

    def test_inputs_property_matches_default_modal(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=True)
        try:
            assert runner.inputs == ["default"]
        finally:
            runner.dispose()

    def test_run_single_frame(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=True)
        try:
            frame = _dummy_frame()
            report = runner.run(frame)
            _assert_example_report(report, frame, frame_tick=1)
        finally:
            runner.dispose()

    def test_run_multi_frame_tick_increments(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=True)
        try:
            for i in range(1, 4):
                report = runner.run(_dummy_frame())
                assert report["frame_tick"] == i
        finally:
            runner.dispose()

    def test_run_missing_modal_raises(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=True)
        try:
            with pytest.raises(MissingInputModal):
                runner.run({"wrong_modal": _dummy_frame()})
        finally:
            runner.dispose()

    def test_run_accepts_dict_default_key(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=True)
        try:
            frame = _dummy_frame()
            report = runner.run({"default": frame})
            _assert_example_report(report, frame, frame_tick=1)
        finally:
            runner.dispose()

    def test_run_respects_custom_timestamp(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=True)
        try:
            ts = 1234567890.5
            report = runner.run(_dummy_frame(), timestamp=ts)
            assert report["timestamp"] == ts
        finally:
            runner.dispose()

    def test_run_accepts_kwargs_extension(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=True)
        try:
            frame = _dummy_frame()
            report = runner.run(frame, custom_hint="ignored", trace_id=42)
            _assert_example_report(report, frame, frame_tick=1)
        finally:
            runner.dispose()

    def test_reset_reverts_frame_tick(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=True)
        try:
            runner.run(_dummy_frame())
            runner.run(_dummy_frame())
            runner.reset()
            report = runner.run(_dummy_frame())
            assert report["frame_tick"] == 1
        finally:
            runner.dispose()

    def test_time_summary_records_package(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=True)
        try:
            runner.run(_dummy_frame())
            summary = runner.time_summary()
            assert "Example Package (test)" in summary
            assert summary["Example Package (test)"] >= 0.0
        finally:
            runner.dispose()

    def test_time_summary_returns_empty_when_profile_disabled(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=False)
        try:
            runner.run(_dummy_frame())
            assert runner.time_summary() == {}
        finally:
            runner.dispose()

    def test_dispose_idempotent(self, solved_pipeline: Pipeline) -> None:
        runner = Runner(solved_pipeline, device="cpu", profile=True)
        runner.dispose()
        runner.dispose()  # must not raise


# ---------------------------------------------------------------------------
# ParallelRunner tests
# ---------------------------------------------------------------------------


class TestParallelRunner:
    def test_inherits_base_parallel_runner(self, parallel_runner_profiled: ParallelRunner) -> None:
        assert isinstance(parallel_runner_profiled, BaseParallelRunner)
        assert isinstance(parallel_runner_profiled, BaseRunner)

    def test_inputs_property(self, parallel_runner_profiled: ParallelRunner) -> None:
        assert parallel_runner_profiled.inputs == ["default"]

    def test_run_async_single_frame(self, parallel_runner_profiled: ParallelRunner) -> None:
        parallel_runner_profiled.reset()
        frame = _dummy_frame()
        future = parallel_runner_profiled.run_async(frame)
        report = future.get()
        _assert_example_report(report, frame, frame_tick=1)

    def test_run_single_frame(self, parallel_runner_profiled: ParallelRunner) -> None:
        parallel_runner_profiled.reset()
        frame = _dummy_frame()
        report = parallel_runner_profiled.run(frame)
        _assert_example_report(report, frame, frame_tick=1)

    def test_run_accepts_timeout_kwonly(self, parallel_runner_profiled: ParallelRunner) -> None:
        """``timeout`` must be keyword-only so ``**kwargs`` stays extensible."""
        parallel_runner_profiled.reset()
        frame = _dummy_frame()
        report = parallel_runner_profiled.run(frame, None, timeout=10.0)
        _assert_example_report(report, frame, frame_tick=1)

    def test_run_multi_frame_tick_increments(self, parallel_runner_profiled: ParallelRunner) -> None:
        parallel_runner_profiled.reset()
        for i in range(1, 4):
            report = parallel_runner_profiled.run(_dummy_frame())
            assert report["frame_tick"] == i

    def test_run_async_accepts_kwargs_extension(self, parallel_runner_profiled: ParallelRunner) -> None:
        parallel_runner_profiled.reset()
        frame = _dummy_frame()
        report = parallel_runner_profiled.run_async(frame, trace_id="abc").get()
        _assert_example_report(report, frame, frame_tick=1)

    def test_run_missing_modal_raises(self, parallel_runner_profiled: ParallelRunner) -> None:
        parallel_runner_profiled.reset()
        with pytest.raises(MissingInputModal):
            parallel_runner_profiled.run({"wrong_modal": _dummy_frame()})

    def test_run_async_missing_modal_raises(self, parallel_runner_profiled: ParallelRunner) -> None:
        parallel_runner_profiled.reset()
        with pytest.raises(MissingInputModal):
            parallel_runner_profiled.run_async({"wrong_modal": _dummy_frame()})

    def test_run_respects_custom_timestamp(self, parallel_runner_profiled: ParallelRunner) -> None:
        parallel_runner_profiled.reset()
        ts = 9876543210.5
        report = parallel_runner_profiled.run(_dummy_frame(), timestamp=ts)
        assert report["timestamp"] == ts

    def test_reset_reverts_frame_tick(self, parallel_runner_profiled: ParallelRunner) -> None:
        parallel_runner_profiled.reset()
        parallel_runner_profiled.run(_dummy_frame())
        parallel_runner_profiled.run(_dummy_frame())
        parallel_runner_profiled.reset()
        report = parallel_runner_profiled.run(_dummy_frame())
        assert report["frame_tick"] == 1

    def test_time_summary_and_dispose(
        self,
        parallel_runner_profiled: ParallelRunner,
        parallel_runner_silent: ParallelRunner,
    ) -> None:
        parallel_runner_profiled.reset()
        parallel_runner_profiled.run(_dummy_frame())
        summary = parallel_runner_profiled.time_summary()
        assert isinstance(summary, dict)
        assert "Example Package (test)" in summary
        # dispose must clear time_summary on the runner (it marks disposed)
        parallel_runner_silent.reset()
        parallel_runner_silent.run(_dummy_frame())
        assert parallel_runner_silent.time_summary() == {}


# ---------------------------------------------------------------------------
# Shared types re-export tests
# ---------------------------------------------------------------------------


def test_shared_types_importable_from_both_modules() -> None:
    from seetapsych_lib.runtime.base_runner import (
        MissingInputModal as MIM_b,
    )
    from seetapsych_lib.runtime.base_runner import (
        PipelineHasProblem as PHP_b,
    )
    from seetapsych_lib.runtime.base_runner import (
        PipelineUnsatisfied as PU_b,
    )
    from seetapsych_lib.runtime.base_runner import (
        TimeSummary as TS_b,
    )
    from seetapsych_lib.runtime.runner import (
        MissingInputModal as MIM_r,
    )
    from seetapsych_lib.runtime.runner import (
        PipelineHasProblem as PHP_r,
    )
    from seetapsych_lib.runtime.runner import (
        PipelineUnsatisfied as PU_r,
    )
    from seetapsych_lib.runtime.runner import (
        TimeSummary as TS_r,
    )

    assert PHP_r is PHP_b
    assert PU_r is PU_b
    assert MIM_r is MIM_b
    assert TS_r is TS_b


def test_time_summary_behaviour() -> None:
    ts = TimeSummary()
    ts.add("detect", 0.1)
    ts.add("detect", 0.3)
    ts.add("landmark", 0.5)
    s = ts.summary()
    assert s == {"detect": round(0.2, 3), "landmark": round(0.5, 3)}
    ts.clear()
    assert ts.summary() == {}
