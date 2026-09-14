# -*- coding: utf-8 -*-

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Callable, Generator, Generic, Iterable, Iterator, Literal, Protocol, TypeVar, overload

from seetapsych_lib.runtime.parallel.future import Future

__all__ = [
    "HasRunAsync",
    "Indexed",
    "OrderedAsyncProcessor",
    "stream_ordered",
]

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class HasRunAsync(Protocol, Generic[OutputT]):
    """Structural protocol for objects with a ``run_async`` method.

    Matches :class:`seetapsych_lib.runtime.parallel_runner.ParallelRunner`
    and any equivalent executor so helpers below are not tightly coupled to
    a single concrete runner class.
    """

    def run_async(
        self,
        data: dict[str, Any] | Any,
        timestamp: float | None = None,
    ) -> Future[OutputT]:
        """Submit work asynchronously and return a :class:`Future`."""
        ...


@dataclass
class Indexed(Generic[InputT, OutputT]):
    """Container for an input/output pair tagged with its submission index.

    Attributes:
        index: Zero-based submission order of the input.
        input: Original input payload (e.g. a video frame).
        output: Result returned by the runner for this input.
    """

    index: int
    input: InputT
    output: OutputT


class OrderedAsyncProcessor(Generic[InputT, OutputT]):
    """Order-preserving asynchronous dispatcher backed by a bounded inflight window.

    Submits up to ``max_inflight`` items ahead via ``runner.run_async``,
    consumes any ready futures in submission-arrival order, and emits
    results strictly in the original submission index. Internally uses a
    reorder buffer so out-of-order completion never bubbles up to callers
    while still minimizing head-of-line blocking for in-flight siblings.

    Typical usage paired with :func:`stream_ordered`::

        for result in stream_ordered(runner, frames):
            writer.write(draw(result.input, result.output))

    For manual control of submission and polling (camera streams,
    interactive loops, etc.), use the class methods directly::

        proc = OrderedAsyncProcessor[Frame, Report](runner, max_inflight=4)
        with proc:
            while cap.isOpened() and not proc.stop_requested:
                ok, frame = cap.read()
                if not ok:
                    break
                if proc.try_submit(frame) is None:
                    r = proc.drain_one(timeout=0.01)
                    if r is not None:
                        yield r
            for r in proc.drain_sorted():
                yield r
    """

    def __init__(
        self,
        runner: HasRunAsync[OutputT],
        *,
        max_inflight: int = 4,
        input_key: str = "default",
        make_payload: Callable[[InputT], dict[str, Any] | Any] | None = None,
    ) -> None:
        """Initialize the processor.

        Args:
            runner: Executor exposing :meth:`HasRunAsync.run_async`. Usually
                a :class:`ParallelRunner`.
            max_inflight: Maximum number of concurrently pending futures.
                Larger values hide pipeline latency at the cost of more
                memory for retained input frames. Defaults to ``4``, which
                is a safe starting point for typical GPU-accelerated
                pipelines.
            input_key: Modal name passed to ``run_async`` when
                ``make_payload`` is ``None``. Ignored when a custom payload
                builder is supplied.
            make_payload: Optional callable that converts an input value
                into the exact payload dict / single value expected by
                ``runner.run_async``. When ``None`` the processor wraps
                inputs as ``{input_key: input}``.
        """
        if max_inflight < 1:
            raise ValueError(f"max_inflight must be >= 1, got {max_inflight}")

        self._runner = runner
        self._max_inflight = max_inflight
        self._input_key = input_key
        self._make_payload = make_payload

        self._next_submit_index = 0
        self._next_emit_index = 0
        self._inflight: deque[tuple[int, InputT, Future[OutputT]]] = deque()
        self._ready: dict[int, tuple[InputT, OutputT]] = {}
        self._input_exhausted = False
        self._stop_requested = False
        self._closed = False

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "OrderedAsyncProcessor[InputT, OutputT]":
        if self._closed:
            raise RuntimeError("OrderedAsyncProcessor was already closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close(cancel=True)

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def _to_payload(self, value: InputT) -> dict[str, Any] | Any:
        if self._make_payload is not None:
            return self._make_payload(value)
        return {self._input_key: value}

    def submit(self, value: InputT, index: int | None = None) -> int:
        """Submit a single input for asynchronous execution.

        The caller must guarantee monotonic non-duplicate indexes when
        supplying an explicit ``index``; use ``None`` to let the processor
        assign sequential indexes starting at ``0``.

        Returns:
            The assigned submission index.

        Raises:
            RuntimeError: If the processor was closed, stop was requested,
                or inflight count is already at ``max_inflight``.
        """
        if self._closed:
            raise RuntimeError("OrderedAsyncProcessor is closed; cannot submit")
        if self._stop_requested:
            raise RuntimeError("OrderedAsyncProcessor stop was requested; cannot submit")
        if len(self._inflight) >= self._max_inflight:
            raise RuntimeError(
                f"inflight full ({len(self._inflight)} >= {self._max_inflight}); drain results before submitting more"
            )
        idx = self._next_submit_index if index is None else index
        self._next_submit_index = idx + 1
        fut = self._runner.run_async(self._to_payload(value))
        self._inflight.append((idx, value, fut))
        return idx

    def try_submit(self, value: InputT, index: int | None = None) -> int | None:
        """Non-blocking variant of :meth:`submit`.

        Returns the assigned index on success, or ``None`` when the
        inflight window is full, stop was requested, or the processor is
        closed. Suitable for poll loops that interleave submission with
        short drain steps (e.g. live camera).
        """
        if self._stop_requested or self._closed:
            return None
        if len(self._inflight) >= self._max_inflight:
            return None
        return self.submit(value, index)

    def submit_many(self, items: Iterable[InputT] | Iterable[tuple[int, InputT]]) -> int:
        """Submit items until inflight is full, stop is requested, or items are exhausted.

        Accepts either bare inputs (auto-indexed) or ``(index, input)``
        pairs. Use this method from a loop to "top up" the inflight window
        between drain steps.

        Returns:
            Number of items actually submitted on this call.
        """
        count = 0
        iterator = iter(items)  # type: ignore[arg-type]
        while len(self._inflight) < self._max_inflight and not self._stop_requested:
            try:
                item = next(iterator)
            except StopIteration:
                self._input_exhausted = True
                break
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], int):
                idx, value = item  # type: ignore[misc]
                self.submit(value, idx)
            else:
                self.submit(item)  # type: ignore[arg-type]
            count += 1
        return count

    # ------------------------------------------------------------------
    # Polling & draining
    # ------------------------------------------------------------------

    def poll_ready(self) -> None:
        """Sweep inflight futures and promote completed ones to the ready buffer.

        Never blocks. Callers that want a guaranteed result afterward
        should use :meth:`drain_one` instead.
        """
        still_flying: deque[tuple[int, InputT, Future[OutputT]]] = deque()
        while self._inflight:
            entry = self._inflight.popleft()
            idx, value, fut = entry
            if fut.done():
                output = fut.get()
                self._ready[idx] = (value, output)
            else:
                still_flying.append(entry)
        self._inflight = still_flying

    def drain_one(self, timeout: float | None = None) -> Indexed[InputT, OutputT] | None:
        """Wait for and return the next result in submission order.

        Returns the next :class:`Indexed` result or ``None`` when no more
        results are ever going to arrive (inflight empty, ready buffer
        empty, and no additional submissions will occur).

        Args:
            timeout: Seconds to wait for at least one future to finish.
                ``None`` blocks indefinitely. Ignored when a result is
                already buffered.
        """
        while True:
            emit_idx = self._next_emit_index
            if emit_idx in self._ready:
                value, output = self._ready.pop(emit_idx)
                self._next_emit_index = emit_idx + 1
                return Indexed(index=emit_idx, input=value, output=output)

            if not self._inflight:
                return None

            self.poll_ready()
            if self._next_emit_index in self._ready:
                continue

            oldest_fut = self._inflight[0][2]
            oldest_fut.wait(timeout)

    def drain_sorted(self) -> Iterator[Indexed[InputT, OutputT]]:
        """Iterator yielding all remaining results strictly in index order.

        Blocks until the inflight window and ready buffer are both empty.
        Safe to call inside ``finally`` to flush stragglers after an
        exception. If ``stop_requested`` was set the iterator still
        processes everything already submitted before the stop.
        """
        while True:
            self.poll_ready()
            if not self._ready and not self._inflight:
                return
            result = self.drain_one()
            if result is None:
                return
            yield result

    # ------------------------------------------------------------------
    # Stop / lifecycle
    # ------------------------------------------------------------------

    @property
    def inflight_count(self) -> int:
        """Number of futures currently pending."""
        return len(self._inflight)

    @property
    def ready_count(self) -> int:
        """Number of completed results waiting to be emitted in order."""
        return len(self._ready)

    @property
    def has_more(self) -> bool:
        """``True`` if inflight or ready buffer still contains work."""
        return bool(self._inflight) or bool(self._ready)

    @property
    def stop_requested(self) -> bool:
        """``True`` after :meth:`request_stop` was called.

        Submission methods will no longer accept new inputs, but all
        already-submitted work will still be processed normally.
        """
        return self._stop_requested

    def request_stop(self) -> None:
        """Request a graceful stop without losing already-submitted work.

        After this call:

        * :meth:`submit` / :meth:`try_submit` / :meth:`submit_many` stop
          accepting new items.
        * :meth:`drain_sorted` and :meth:`drain_one` continue producing
          results for all frames submitted before the stop.
        * The caller is responsible for draining remaining work (or calling
          :meth:`close` with ``cancel=True`` to drop it).

        This is the recommended primitive for handling camera-stop signals
        (user key, watchdog timeout, etc.) when data loss is not
        acceptable.
        """
        self._stop_requested = True
        self._input_exhausted = True

    def close(self, *, cancel: bool = True) -> None:
        """Release inflight bookkeeping and mark the processor closed.

        Args:
            cancel: When ``True`` (default), cancel every pending future
                immediately. This guarantees minimal teardown latency and
                full **code safety** (no leaked threads / pending Futures),
                at the cost of dropping results for frames that were still
                in flight. When ``False``, block until every inflight
                future has completed normally — this guarantees **data
                safety** (every submitted input produces an output), but
                may take up to ``max_inflight * per_frame_latency`` on
                teardown. The ready buffer is always cleared in either
                case.
        """
        if self._closed:
            return
        if cancel:
            for _, _, fut in self._inflight:
                if not fut.done():
                    fut.cancel()
            self._inflight.clear()
        else:
            for _, _, fut in list(self._inflight):
                fut.wait()
            self._inflight.clear()
        self._ready.clear()
        self._closed = True


@overload
def stream_ordered(
    runner: HasRunAsync[OutputT],
    inputs: Iterable[InputT],
    *,
    max_inflight: int = 4,
    input_key: str = "default",
    make_payload: Callable[[InputT], dict[str, Any] | Any] | None = None,
    cancel_on_error: bool = True,
    on_early_exit: Literal["cancel", "drain"] = "cancel",
) -> Generator[Indexed[InputT, OutputT], None, None]: ...


@overload
def stream_ordered(
    runner: HasRunAsync[OutputT],
    inputs: Iterable[tuple[int, InputT]],
    *,
    max_inflight: int = 4,
    input_key: str = "default",
    make_payload: Callable[[InputT], dict[str, Any] | Any] | None = None,
    cancel_on_error: bool = True,
    on_early_exit: Literal["cancel", "drain"] = "cancel",
    indexed: Literal[True],
) -> Generator[Indexed[InputT, OutputT], None, None]: ...


def stream_ordered(
    runner: HasRunAsync[OutputT],
    inputs: Iterable[Any],
    *,
    max_inflight: int = 4,
    input_key: str = "default",
    make_payload: Callable[[Any], dict[str, Any] | Any] | None = None,
    cancel_on_error: bool = True,
    on_early_exit: Literal["cancel", "drain"] = "cancel",
    indexed: bool = False,
) -> Generator[Indexed[Any, OutputT], None, None]:
    """Stream order-preserving async results from ``runner`` over ``inputs``.

    High-level convenience wrapper around :class:`OrderedAsyncProcessor`
    that handles submission, reorder buffering, teardown on exceptions,
    and final drain of stragglers. Works identically for finite sources
    (video files, image folders) and infinite sources (live cameras).

    File source example::

        def file_frames(cap: cv2.VideoCapture) -> Iterator[tuple[int, numpy.ndarray]]:
            idx = 0
            while cap.isOpened():
                ok, frame = cap.read()
                if not ok:
                    return
                yield idx, frame
                idx += 1

        cap = cv2.VideoCapture(video_path)
        for item in stream_ordered(runner, file_frames(cap), indexed=True):
            writer.write(draw(item.input, item.output))

    Live-camera example with stop-on-key (**data-safe**: pressing ``q``
    finishes every frame submitted before the keypress)::

        proc: OrderedAsyncProcessor | None = None
        try:
            proc = OrderedAsyncProcessor(runner, max_inflight=4)
            with proc:
                while cap.isOpened() and not proc.stop_requested:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if proc.try_submit(frame) is None:
                        r = proc.drain_one(timeout=0.005)
                        if r is not None:
                            vis = draw(r.input, r.output)
                            cv2.imshow("preview", vis)
                            if cv2.waitKey(1) & 0xFF == ord("q"):
                                proc.request_stop()  # data-safe stop
                    else:
                        cv2.waitKey(1)
                # drain stragglers after stop / EOS
                for r in proc.drain_sorted():
                    writer.write(draw(r.input, r.output))
        finally:
            cap.release()
            runner.dispose()

    Args:
        runner: Executor exposing ``run_async``.
        inputs: Iterable of input payloads, or ``(index, input)`` tuples
            when ``indexed=True``. Iteration is consumed lazily as the
            inflight window drains. For live sources this iterable may be
            infinite; combine with an external ``request_stop`` or break.
        max_inflight: Maximum number of concurrently pending futures.
            Forwarded directly to :class:`OrderedAsyncProcessor`.
        input_key: Modal name for simple single-key runners. Ignored when
            ``make_payload`` is provided.
        make_payload: Optional transformer mapping an input to the exact
            payload shape expected by ``runner.run_async``.
        cancel_on_error: When ``True`` (default) any exception raised by
            a future or during iteration cancels all remaining inflight
            work immediately (**code safety** priority). When ``False``
            the generator finishes every inflight future before
            re-raising, trading latency for **data safety**.
        on_early_exit: Controls behaviour when the generator is
            terminated via ``break`` / ``GeneratorExit`` *before*
            ``inputs`` was exhausted:

            * ``"cancel"`` (default) — equivalent to ``close(cancel=True)``:
              drop inflight immediately. Use this when the caller
              explicitly opted out via break and fastest teardown matters.
            * ``"drain"`` — equivalent to ``close(cancel=False)``: wait
              for all inflight to complete before returning. Use this to
              avoid data loss when ``break`` represents a normal stop
              condition (e.g. user pressed ``q`` inside the loop body).

            Exceptions always follow ``cancel_on_error`` regardless of
            this setting.
        indexed: Set to ``True`` when ``inputs`` yields
            ``(int_index, input_value)`` pairs. Useful when callers need
            to align outputs back to a source that already carries its
            own positional index.

    Yields:
        :class:`Indexed` tuples ``(index, input, output)`` strictly in
        submission order.
    """
    proc: OrderedAsyncProcessor[Any, OutputT] = OrderedAsyncProcessor(
        runner,
        max_inflight=max_inflight,
        input_key=input_key,
        make_payload=make_payload,
    )

    input_iter = iter(inputs)
    pending_source = True

    def _top_up() -> bool:
        nonlocal pending_source
        if not pending_source or proc.stop_requested:
            return False
        submitted = 0
        while proc.inflight_count < max_inflight and not proc.stop_requested:
            try:
                item = next(input_iter)
            except StopIteration:
                pending_source = False
                proc._input_exhausted = True  # noqa: SLF001  (intentional friend access)
                break
            if indexed:
                idx, value = item
                proc.submit(value, idx)
            else:
                proc.submit(item)
            submitted += 1
        return submitted > 0 or pending_source or proc.stop_requested

    generator_exited_early = False
    try:
        while True:
            had_work = _top_up()
            proc.poll_ready()
            if not proc.has_more and not had_work and (pending_source is False or proc.stop_requested):
                break
            result = proc.drain_one(timeout=None if proc.has_more else 0.0)
            if result is None:
                if proc.has_more or pending_source:
                    continue
                break
            yield result
    except GeneratorExit:
        generator_exited_early = True
        raise
    except BaseException:
        if cancel_on_error:
            proc.close(cancel=True)
        else:
            proc.close(cancel=False)
        raise
    else:
        # Normal exhaustion / stop → always drain to keep data-safe semantics
        proc.close(cancel=False)
    finally:
        if generator_exited_early:
            if on_early_exit == "drain":
                proc.close(cancel=False)
            else:
                proc.close(cancel=True)
        elif not proc._closed:  # noqa: SLF001
            proc.close(cancel=True)
