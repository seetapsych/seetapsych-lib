# -*- coding: utf-8 -*-
"""
Test cases for ParallelExecutor.

Run directly:
    python test_parallel_executor_upgraded.py

Cases:
1. multi-node compute graph
2. executor init() failure
3. executor run() failure

Each case calls dispose() and verifies that child processes are stopped.
"""

from __future__ import annotations

import multiprocessing as mp
import threading
import time
import traceback
from typing import Callable, Any


from fabopsy_lib.runtime.parallel.executor import *


# -----------------------------------------------------------------------------
# Test executors
# -----------------------------------------------------------------------------
# These classes must be defined at module top-level so they can be pickled by
# multiprocessing when the start method is spawn.

class AddExecutor(Executor):
    def __init__(self, delta: int):
        self.delta = delta

    def init(self):
        pass

    def run(self, *args, **kwargs):
        # One-input node: x -> x + delta
        return args[0] + self.delta


class MulExecutor(Executor):
    def __init__(self, factor: int):
        self.factor = factor

    def init(self):
        pass

    def run(self, *args, **kwargs):
        # One-input node: x -> x * factor
        return args[0] * self.factor


class SumExecutor(Executor):
    def init(self):
        pass

    def run(self, *args, **kwargs):
        # Multi-input node. The current executor implementation passes inputs
        # through a set, so argument order is intentionally not assumed here.
        return sum(args)


class InitFailedExecutor(Executor):
    def init(self):
        raise RuntimeError("expected init failure")

    def run(self, *args, **kwargs):
        return args[0]


class RunFailedExecutor(Executor):
    def init(self):
        pass

    def run(self, *args, **kwargs):
        raise RuntimeError("expected run failure")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def get_processes(runner: ParallelExecutor) -> dict[int, mp.Process]:
    """Access private process dict for test-only lifecycle assertions."""
    return getattr(runner, "_ParallelExecutor__processes")


def process_snapshot(runner: ParallelExecutor) -> dict[int, tuple[str, int | None, bool, int | None]]:
    """Return {node_id: (name, pid, alive, exitcode)} for easier debugging."""
    return {
        node_id: (p.name, p.pid, p.is_alive(), p.exitcode)
        for node_id, p in get_processes(runner).items()
    }


def assert_all_processes_stopped(runner: ParallelExecutor, case_name: str) -> None:
    """Fail the test if any child process is still alive after dispose()."""
    alive = []
    for node_id, process in get_processes(runner).items():
        if process.is_alive():
            alive.append((node_id, process.name, process.pid, process.exitcode))

    if alive:
        raise AssertionError(f"{case_name}: processes still alive after dispose: {alive}")


def dispose_and_check(runner: ParallelExecutor, case_name: str, wait_seconds: float = 0.3) -> None:
    """Always release resources and verify process lifecycle."""
    runner.dispose(wait_seconds=wait_seconds)
    assert_all_processes_stopped(runner, case_name)


def run_case(case_name: str, fn: Callable[[], None]) -> bool:
    print(f"\n===== RUN {case_name} =====", flush=True)
    try:
        fn()
        print(f"===== PASS {case_name} =====", flush=True)
        return True
    except Exception:
        print(f"===== FAIL {case_name} =====", flush=True)
        traceback.print_exc()
        return False


def call_with_timeout(fn: Callable[[], Any], timeout: float) -> tuple[bool, Any, list[BaseException]]:
    """Run a blocking call in a thread and return whether it finished."""
    result: list[Any] = []
    errors: list[BaseException] = []

    def wrapper() -> None:
        try:
            result.append(fn())
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        return False, None, errors
    return True, result[0] if result else None, errors


# -----------------------------------------------------------------------------
# Cases
# -----------------------------------------------------------------------------

def case_multi_node_graph() -> None:
    """
    Graph topology:

        input -> add_1 ----\
                           sum -> add_100 -> output
        input -> mul_2 ----/

    For input x:
        add_1 = x + 1
        mul_2 = x * 2
        sum = (x + 1) + (x * 2) = 3x + 1
        add_100 = 3x + 101

    Expected for x=10: 131
    """
    runner = ParallelExecutor()
    try:
        add_1 = runner.register("add_1", AddExecutor(1))
        mul_2 = runner.register("mul_2", MulExecutor(2))
        sum_node = runner.register("sum", SumExecutor(), inputs=[add_1, mul_2])
        runner.register("add_100", AddExecutor(100), inputs=[sum_node])

        runner.start()

        for value in [2, 10, 20]:
            result = runner.execute(value, timeout=3)
            expected = (3 * value + 101,)

            # GatherExecutor returns args, so one final output becomes a tuple.
            if tuple(result) != expected:
                raise AssertionError(
                    f"unexpected result for value={value}: got {result!r}, expected {expected!r}; "
                    f"processes={process_snapshot(runner)}"
                )
    finally:
        dispose_and_check(runner, "case_multi_node_graph")


def case_init_failure() -> None:
    runner = ParallelExecutor()
    try:
        runner.register("init_failed", InitFailedExecutor())

        finished, _, errors = call_with_timeout(runner.start, timeout=3.0)

        if not finished:
            runner.dispose(wait_seconds=0.2)
            raise AssertionError("start() blocked after init failure")

        if not errors:
            raise AssertionError("start() should fail when executor.init() raises")
    finally:
        dispose_and_check(runner, "case_init_failure")


def case_run_failure() -> None:
    runner = ParallelExecutor()
    try:
        runner.register("run_failed", RunFailedExecutor())
        runner.start()

        try:
            result = runner.execute(10, timeout=2)
        except RuntimeError as exc:
            # The health monitor may consume the run failure first and enqueue STOP
            # to final_queue, so execute() can raise "executor stopped".
            if "executor stopped" not in str(exc):
                raise
        else:
            # If STOP does not win the race, execute() may time out and return [].
            if result != []:
                raise AssertionError(f"expected timeout result [], got {result!r}")

        time.sleep(0.5)
        exitcodes = {
            node_id: process.exitcode
            for node_id, process in get_processes(runner).items()
        }
        if 2 not in exitcodes.values():
            raise AssertionError(f"expected one process exitcode=2, got {exitcodes}")
    finally:
        dispose_and_check(runner, "case_run_failure")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    # spawn is closer to Windows behavior and catches pickling/import problems.
    mp.set_start_method("spawn", force=True)

    cases = [
        ("multi_node_graph", case_multi_node_graph),
        ("init_failure", case_init_failure),
        ("run_failure", case_run_failure),
    ]

    ok = True
    for name, fn in cases:
        ok = run_case(name, fn) and ok

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
