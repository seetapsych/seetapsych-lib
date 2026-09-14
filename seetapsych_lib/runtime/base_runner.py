# -*- coding: utf-8 -*-

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

from seetapsych_lib.runtime.parallel.future import Future

__all__ = [
    "BaseRunner",
    "BaseParallelRunner",
    "PipelineHasProblem",
    "PipelineUnsatisfied",
    "MissingInputModal",
    "TimeSummary",
]


class PipelineHasProblem(Exception):
    """Raised when the pipeline still has unresolved dependency problems."""


class PipelineUnsatisfied(Exception):
    """Raised when the pipeline has unsatisfied runtime prerequisites."""


class MissingInputModal(Exception):
    """Raised when a required input modal is not provided to ``run()``."""


class TimeSummary:
    """Simple running average of wall-clock times grouped by tag.

    Each stored entry tracks (count, total_seconds); the reported average is
    rounded to three decimals.
    """

    def __init__(self):
        self.__summary: dict[str, list[float | int]] = defaultdict(lambda: [int(0), float(0)])

    def add(self, tag: str, time_seconds: float):
        """Record a new timing sample.

        Args:
            tag: Identifier for the measured operation.
            time_seconds: Elapsed wall-clock time in seconds.
        """
        value = self.__summary[tag]
        value[0] += 1
        value[1] += time_seconds

    def clear(self):
        """Discard all recorded samples."""
        self.__summary.clear()

    def summary(self) -> dict[str, float]:
        """Return per-tag average times.

        Returns:
            Mapping of ``tag`` to average elapsed time in seconds, rounded
            to three decimal places.
        """
        return {tag: round(value[1] / value[0], 3) for tag, value in self.__summary.items()}


class BaseRunner(ABC):
    """Abstract interface for synchronous pipeline executors.

    Defines the minimal common contract every runner implementation must
    satisfy. Implementations range from the single-threaded
    :class:`seetapsych_lib.runtime.runner.Runner` to multi-node
    distributed runners. Only the public behavioural surface is specified here;
    construction- and lifecycle internals are deliberately left to concrete classes so each
    backend can manage devices, caches, and executors independently.
    """

    @property
    @abstractmethod
    def inputs(self) -> list[str]:
        """Return the required input modal names for :meth:`run`."""

    @abstractmethod
    def run(
        self,
        data: dict[str, Any] | Any,
        timestamp: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run inference on a single input frame.

        Args:
            data: Either a single payload for the ``"default"`` modal, or a
                dict mapping modal names to their payloads.
            timestamp: Optional wall-clock timestamp for the frame.
            **kwargs: Reserved for backend-specific extension parameters
                (e.g. priority hints, tracing flags, distributed routing).
                Ignored by implementations that do not recognise them.

        Returns:
            The accumulated attribute report dictionary.

        Raises:
            MissingInputModal: If ``data`` is missing any required modal
                (see :attr:`inputs`).
        """

    @abstractmethod
    def reset(self) -> None:
        """Reset per-frame state and all package instances."""

    @abstractmethod
    def dispose(self) -> None:
        """Release resources held by all package instances."""

    @abstractmethod
    def time_summary(self) -> dict[str, float]:
        """Return per-package average inference times.

        Returns:
            Mapping of package/executor tag to average elapsed seconds,
            rounded to three decimal places. Empty dict when profiling is
            disabled or no samples have been recorded.
        """


class BaseParallelRunner(BaseRunner):
    """Abstract interface for asynchronous / parallel pipeline executors.

    Extends :class:`BaseRunner` with a :meth:`run_async` contract that
    returns a :class:`Future`, plus an optional ``timeout`` parameter on
    the synchronous :meth:`run` convenience wrapper.
    """

    @abstractmethod
    def run_async(
        self,
        data: dict[str, Any] | Any,
        timestamp: float | None = None,
        **kwargs: Any,
    ) -> Future[dict[str, Any]]:
        """Submit a frame for inference and return a :class:`Future`.

        Returns immediately without blocking; call :meth:`Future.get` on the
        returned object (or use :meth:`run`) to wait for the result.

        Args:
            data: Either a single payload for the ``"default"`` modal, or a
                dict mapping modal names to their payloads.
            timestamp: Optional wall-clock timestamp for the frame.
            **kwargs: Reserved for backend-specific extension parameters.
                Ignored by implementations that do not recognise them.

        Returns:
            A :class:`Future` resolving to the accumulated attribute report.

        Raises:
            MissingInputModal: If ``data`` is missing any required modal.
        """

    @abstractmethod
    def run(
        self,
        data: dict[str, Any] | Any,
        timestamp: float | None = None,
        *,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run inference on a single frame and wait for the result.

        Typically implemented as ``run_async(data, timestamp, **kwargs).get(timeout=timeout)``.

        Args:
            data: Either a single payload or a modal-to-payload dict.
            timestamp: Optional wall-clock timestamp for the frame.
            timeout: Maximum seconds to wait. ``None`` blocks indefinitely.
                Keyword-only; cannot be passed positionally so that
                ``**kwargs`` remains available for future extension
                parameters between ``timestamp`` and ``timeout``.
            **kwargs: Reserved for backend-specific extension parameters.
                Forwarded to :meth:`run_async` by the default wrapper.

        Returns:
            The accumulated attribute report dictionary.

        Raises:
            MissingInputModal: If required input modals are missing.
            TimeoutError: If the result is not ready within ``timeout``.
        """
