"""Spawn context and worker startup regression tests without model dependencies."""

import multiprocessing as mp
import threading
from multiprocessing.context import BaseContext
from typing import Any
from unittest.mock import Mock

import pytest

from seetapsych_lib.runtime.parallel.executor import Executor, ParallelExecutor


class EchoExecutor(Executor):
    """Report the actual worker start method and preserve the submitted payload."""

    def init(self) -> None:
        """Initialize worker-local state."""

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Return the worker's start method and its first input."""
        return mp.get_start_method(), args[0]


class UnpicklableExecutor(EchoExecutor):
    """Represent an executor incorrectly holding a host-only native resource."""

    def __init__(self) -> None:
        """Create a lock that cannot be serialized to a spawned interpreter."""
        self.lock = threading.Lock()


class InitFailedExecutor(EchoExecutor):
    """Fail after the interpreter has successfully spawned."""

    def init(self) -> None:
        """Raise an initialization failure for lifecycle verification."""
        raise RuntimeError("expected initialization failure")


def test_default_context_is_local_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default construction requests spawn without modifying global settings."""
    original_context = mp.get_context
    context = Mock(wraps=original_context("spawn"))
    get_context = Mock(return_value=context)
    set_start_method = Mock(side_effect=AssertionError("global start method changed"))
    monkeypatch.setattr(mp, "get_context", get_context)
    monkeypatch.setattr(mp, "set_start_method", set_start_method)
    runner = ParallelExecutor()
    try:
        runner.register("echo", EchoExecutor())
        runner.start()
        assert runner.execute({"value": [1, 2, 3]}, timeout=10) == (("spawn", {"value": [1, 2, 3]}),)
        get_context.assert_called_once_with("spawn")
        set_start_method.assert_not_called()
        assert context.Event.call_count == 1
        assert context.Queue.call_count == 5
        assert context.Process.call_count == 2
    finally:
        runner.dispose()


@pytest.mark.parametrize("method", mp.get_all_start_methods())
def test_explicit_context(method: str) -> None:
    """All available caller-supplied contexts use matching worker resources."""
    context: BaseContext = mp.get_context(method)
    runner = ParallelExecutor(mp_context=context)
    try:
        runner.register("echo", EchoExecutor())
        runner.start()
        assert runner.execute(12, timeout=10) == ((method, 12),)
        with pytest.raises(RuntimeError, match="cannot restart"):
            runner.start()
    finally:
        runner.dispose()
        runner.dispose()


@pytest.mark.parametrize("failure", ["pickle", "process_start", "init"])
def test_start_failure_stops_all_started_workers(failure: str) -> None:
    """Startup failure releases previously started processes and host threads."""
    spawn_context = mp.get_context("spawn")
    context = Mock(wraps=spawn_context)
    processes: list[Any] = []

    def create_process(**kwargs: Any) -> Any:
        process = spawn_context.Process(**kwargs)
        if failure == "process_start" and len(processes) == 1:
            process.start = Mock(side_effect=OSError("expected process startup failure"))
        processes.append(process)
        return process

    context.Process.side_effect = create_process
    runner = ParallelExecutor(mp_context=context)
    runner.register("echo", EchoExecutor())
    worker = InitFailedExecutor() if failure == "init" else UnpicklableExecutor()
    runner.register("failure", worker)
    try:
        expected_error = {"pickle": TypeError, "process_start": OSError, "init": RuntimeError}[failure]
        with pytest.raises(expected_error):
            runner.start()
        started = [process for process in processes if not process._closed and process.pid is not None]
        assert started
        assert all(not process.is_alive() for process in started)
        assert all(process.exitcode is not None for process in started)
        with pytest.raises(RuntimeError, match="cannot restart"):
            runner.start()
    finally:
        runner.dispose()


def test_failed_startup_closes_queues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unconsumed queue feeders cannot block failed-startup cleanup."""
    context = Mock(wraps=mp.get_context("spawn"))
    queues: list[Any] = []
    create_queue = context.Queue
    spawn_context = mp.get_context("spawn")

    def tracked_queue() -> Any:
        q = spawn_context.Queue()
        queues.append(q)
        return q

    create_queue.side_effect = tracked_queue
    monkeypatch.setattr(mp, "get_context", Mock(return_value=context))
    runner = ParallelExecutor()
    runner.register("failure", UnpicklableExecutor())
    with pytest.raises(TypeError):
        runner.start()
    assert queues
    assert all(q._closed for q in queues)
    runner.dispose()
