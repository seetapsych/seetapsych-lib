# -*- coding: utf-8 -*-

import multiprocessing as mp
import queue
import threading
import time
import traceback
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from multiprocessing import synchronize as sc
from typing import Any, Callable, Literal, Optional, cast

from seetapsych_lib.runtime.parallel.future import Future, WritableFuture
from seetapsych_lib.utils.logger import logger

__all__ = [
    "Executor",
    "ParallelExecutor",
]


class Executor(ABC):
    """
    The parallel executor in sub process. Created in host process,
    `init` and `run` are executed in sub process.
    """

    @abstractmethod
    def init(self): ...

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> Any: ...

    def action(self, data: Any):
        """Optional hook for control-plane actions (e.g. reset state) during graph execution. Default no-op."""
        del data


@dataclass
class NodeSpec:
    name: str
    inputs: list[mp.Queue]
    outputs: list[mp.Queue]
    executor: Executor
    health: mp.Queue
    stop: sc.Event
    time: Optional[mp.Queue] = None


@dataclass
class HealthEvent:
    level: Literal["INFO", "WARNING", "ERROR"]
    source: str
    message: str
    detail: Optional[str] = None
    should_stop: bool = False


class MessageType(str, Enum):
    ACTION = "ACTION"
    DATA = "DATA"
    PROBE = "PROBE"
    STOP = "STOP"
    ERROR = "ERROR"


@dataclass
class Message:
    type: MessageType
    sync_id: Optional[int] = None
    payload: Any = None
    source: Optional[str] = None


@dataclass
class TimeEvent:
    tag: str
    time_seconds: float


class TimeSummary:
    def __init__(self):
        self.__lock = threading.Lock()
        self.__summary: dict[str, list[float | int]] = defaultdict(lambda: [int(0), float(0)])

    def add(self, tag: str, time_seconds: float):
        with self.__lock:
            value = self.__summary[tag]
            value[0] += 1
            value[1] += time_seconds

    def clear(self):
        with self.__lock:
            self.__summary.clear()

    def summary(self) -> dict[str, float]:
        with self.__lock:
            return {tag: round(value[1] / value[0], 3) for tag, value in self.__summary.items()}


def process_node_main(spec: NodeSpec):
    # start
    spec.health.put(
        HealthEvent(
            level="INFO",
            source=spec.name,
            message="node process started",
        )
    )

    # init
    try:
        spec.executor.init()
        spec.health.put(
            HealthEvent(
                level="INFO",
                source=spec.name,
                message="node process initialized",
            )
        )
    except Exception:
        spec.health.put(
            HealthEvent(
                level="ERROR",
                source=spec.name,
                message="node process crashed while initializing",
                detail=traceback.format_exc(),
                should_stop=True,
            )
        )
        exit(1)

    def run_action(data: Any):
        try:
            spec.executor.action(data)
        except Exception:
            spec.health.put(
                HealthEvent(
                    level="WARNING",
                    source=spec.name,
                    message="run executor action failed",
                    detail=traceback.format_exc(),
                )
            )

    # run
    try:
        while not spec.stop.is_set():
            input_messages: list[Message] = []

            # Read one message from each input queue.
            # This assumes upstream queues preserve order, so frame sync should normally match.
            for q in spec.inputs:
                while not spec.stop.is_set():
                    try:
                        msg = q.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if msg.type == MessageType.ACTION:
                        run_action(msg.payload)
                        continue
                    if msg.type == MessageType.STOP:
                        break
                    input_messages.append(msg)
                    break

            if spec.stop.is_set() or len(input_messages) != len(spec.inputs):
                # stop event received
                break

            msg_types = {msg.type for msg in input_messages}

            # STOP has the highest priority.
            if MessageType.STOP in msg_types:
                break

            sync_ids = {msg.sync_id for msg in input_messages}
            if len(sync_ids) != 1:
                logger.warning(f"Received inconsistent sync ids {sync_ids}")
            sync_id = input_messages[0].sync_id

            # run in probe mode
            if MessageType.PROBE in msg_types:
                assert len(msg_types) == 1

                msg = Message(
                    type=MessageType.PROBE,
                    sync_id=sync_id,
                    source=spec.name,
                )
                for q in spec.outputs:
                    q.put(msg)
                continue

            # got error in previous nodes
            if MessageType.ERROR in msg_types:
                error_payload = [msg.payload for msg in input_messages if msg.type == MessageType.ERROR]
                while isinstance(error_payload, list) and len(error_payload) == 1:
                    error_payload = error_payload[0]
                output = Message(
                    type=MessageType.ERROR,
                    sync_id=sync_id,
                    payload=error_payload,
                    source=spec.name,
                )
                for q in spec.outputs:
                    q.put(output)
                continue

            # run executor
            payloads = [msg.payload for msg in input_messages]
            try:
                output_type = MessageType.DATA
                start_time_seconds = time.perf_counter()
                output_payload = spec.executor.run(*payloads)
                time_seconds = time.perf_counter() - start_time_seconds
            except Exception:
                output_type = MessageType.ERROR
                output_payload = traceback.format_exc()
            output = Message(
                type=output_type,
                sync_id=sync_id,
                payload=output_payload,
                source=spec.name,
            )
            for q in spec.outputs:
                q.put(output)
            if spec.time is not None:
                spec.time.put(TimeEvent(tag=spec.name, time_seconds=time_seconds))

        spec.health.put(
            HealthEvent(
                level="INFO",
                source=spec.name,
                message="node process exited normally",
            )
        )
        exit(0)
    except Exception:
        spec.health.put(
            HealthEvent(
                level="ERROR",
                source=spec.name,
                message="node process crashed while running",
                detail=traceback.format_exc(),
                should_stop=True,
            )
        )
        exit(2)


class GatherExecutor(Executor):
    def init(self):
        pass

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return args


class ParallelExecutor:
    def __init__(self, profile: bool = False):
        self.__stop_event = mp.Event()
        self.__health_queue: "mp.Queue[Any]" = mp.Queue()
        self.__time_queue: "mp.Queue[Any]" = mp.Queue()

        self.__id = 1  # 0 for input, -1 for output
        self.__nodes: dict[int, NodeSpec] = {}
        self.__links: list[tuple[int, int]] = []

        self.__compiled = False
        self.__queues: dict[tuple[int, int], mp.Queue] = {}
        self.__input_queues: list[mp.Queue] = []
        self.__output_queues: list[mp.Queue] = []
        self.__action_queues: dict[int, mp.Queue] = {}

        self.__started = False
        self.__processes: dict[int, mp.Process] = {}
        self.__watch_process_threads: list[threading.Thread] = []
        self.__monitor_threads: list[threading.Thread] = []

        self.__final_queue: "mp.Queue[Any]" = mp.Queue()
        self.__final_output: NodeSpec = NodeSpec(
            name="__output__",
            inputs=self.__output_queues,
            outputs=[self.__final_queue],
            executor=GatherExecutor(),
            health=self.__health_queue,
            stop=self.__stop_event,
        )
        self.__nodes[-1] = self.__final_output

        self.__sync_id = 1

        # for async futures
        self.__futures: dict[int, WritableFuture] = {}
        self.__futures_lock = threading.Lock()
        self.__dispatch_threads: list[threading.Thread] = []

        # for time summary
        self.__profile = profile
        self.__time_summary = TimeSummary()

    def register(self, name: str, executor: Executor, inputs: Optional[list[int]] = None) -> int:
        if not inputs:
            inputs = [0]

        spec = NodeSpec(
            name=name,
            inputs=[],
            outputs=[],
            executor=executor,
            health=self.__health_queue,
            stop=self.__stop_event,
            time=self.__time_queue if self.__profile else None,
        )

        node_id = self.__id
        self.__id += 1

        self.__nodes[node_id] = spec
        for input_id in inputs:
            self.__links.append((input_id, node_id))

        return node_id

    def _compile(self):
        if self.__compiled:
            return

        # create queue for link
        for link in self.__links:
            q: "mp.Queue[Any]" = mp.Queue()
            self.__queues[link] = q

            if link[0] == 0:
                self.__input_queues.append(q)
            else:
                self.__nodes[link[0]].outputs.append(q)

            if link[1] > 0:
                self.__nodes[link[1]].inputs.append(q)
                # each node bind action queue
                if link[1] not in self.__action_queues:
                    self.__action_queues[link[1]] = q

        # find outputs
        output_ids = [i for (i, n) in self.__nodes.items() if i > 0 and not n.outputs]
        for output_id in output_ids:
            link = (output_id, -1)
            q = mp.Queue()
            self.__links.append(link)
            self.__queues[link] = q
            self.__output_queues.append(q)
            self.__nodes[link[0]].outputs.append(q)

        self.__compiled = True

    def _thread_watch_process(self, spec: NodeSpec, process: mp.Process):
        process.join()

        exitcode = process.exitcode

        if exitcode not in (0, None):
            self.__health_queue.put(
                HealthEvent(
                    level="ERROR",
                    source=spec.name,
                    message=f"process exited abnormally, exitcode={exitcode}",
                    should_stop=True,
                )
            )
        else:
            self.__health_queue.put(
                HealthEvent(
                    level="INFO",
                    source=spec.name,
                    message="process exited normally",
                )
            )

    def _thread_watch_health(self):
        # has running process
        while any([p.is_alive() for p in self.__processes.values()]):
            try:
                event: HealthEvent = self.__health_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if event is None:
                break

            log_message = f"[ParallelExecutor][{event.level}][{event.source}] {event.message}"
            if event.detail:
                log_message += f"\n{event.detail}"

            match event.level:
                case "ERROR":
                    logger.error(log_message)
                case "WARNING":
                    logger.warning(log_message)
                case "INFO":
                    logger.info(log_message)

            if event.should_stop:
                logger.warning("[ParallelExecutor] fatal event received, stopping executor")
                self.stop()
                break

    def _thread_watch_time(self):
        # has running process
        while not self.__stop_event.is_set():
            try:
                event: TimeEvent = self.__time_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if event is None:
                break

            self.__time_summary.add(event.tag, event.time_seconds)

    def _thread_dispatch_output(self):
        while not self.__stop_event.is_set():
            try:
                msg: Message = self.__final_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if msg.type == MessageType.STOP:
                break

            with self.__futures_lock:
                future = self.__futures.pop(cast(int, msg.sync_id), None)

                # clear cancelled feature
                items = list(self.__futures.items())
                for k, v in items:
                    if v.cancelled():
                        self.__futures.pop(k)

            if future is None:
                logger.warning(f"received output for unknown or cancelled sync_id={msg.sync_id}")
                continue

            if msg.type == MessageType.PROBE:
                future.set_result(msg.payload)
            elif msg.type == MessageType.DATA:
                future.set_result(msg.payload)
            elif msg.type == MessageType.ERROR:
                future.set_error(RuntimeError(f"received error from node {msg.source}: {msg.payload}"))
            else:
                future.set_error(RuntimeError(f"received unexpected message: {msg}"))

        # finalize not finished futures
        with self.__futures_lock:
            for future in self.__futures.values():
                future.set_error(RuntimeError("executor stopped"))
            self.__futures.clear()

    def _clear(self):
        self.__stop_event.clear()

        self.__processes.clear()
        self.__watch_process_threads.clear()
        self.__monitor_threads.clear()
        self.__dispatch_threads.clear()

        self.__time_summary.clear()

    def time_summary(self) -> dict[str, float]:
        return self.__time_summary.summary()

    def start(self):
        if self.__started:
            raise RuntimeError("cannot start a running parallel executor")

        self._compile()

        # the output node has already in self.__nodes
        for i, spec in self.__nodes.items():
            p = mp.Process(
                target=process_node_main,
                name=f"seetapsych:{spec.name}",
                args=(spec,),
                daemon=False,
            )
            p.start()
            self.__processes[i] = p

        # watch process exit
        for i, p in self.__processes.items():
            spec = self.__nodes[i]
            thread = threading.Thread(
                target=self._thread_watch_process,
                args=(spec, p),
                daemon=True,
            )
            thread.start()
            self.__watch_process_threads.append(thread)

        # watch health
        thread_health = threading.Thread(
            target=self._thread_watch_health,
            args=(),
            daemon=True,
        )
        thread_health.start()
        self.__monitor_threads.append(thread_health)

        # watch time
        thread_time = threading.Thread(
            target=self._thread_watch_time,
            args=(),
            daemon=True,
        )
        thread_time.start()
        self.__monitor_threads.append(thread_time)

        # dispatch
        thread_dispatch = threading.Thread(
            target=self._thread_dispatch_output,
            args=(),
            daemon=True,
        )
        thread_dispatch.start()
        self.__dispatch_threads.append(thread_dispatch)

        # use probe check initialize ready
        try:
            if not self.probe():
                raise RuntimeError("run probe failed after start")
        except RuntimeError:
            self.dispose()
            self._clear()
            raise

    def probe(self) -> bool:
        sync_id = self.__sync_id
        self.__sync_id += 1

        future: WritableFuture[Any] = WritableFuture()

        input_msg = Message(
            type=MessageType.PROBE,
            sync_id=sync_id,
            payload=None,
            source="__input__",
        )

        with self.__futures_lock:
            self.__futures[sync_id] = future

        for q in self.__input_queues:
            q.put(input_msg)

        return future.wait() and future.error is None

    def submit(self, payload: Any, cascade: Callable[[Any], Any] | None = None) -> Future[Any]:
        sync_id = self.__sync_id
        self.__sync_id += 1

        future = WritableFuture(cascade=cascade)

        input_msg = Message(
            type=MessageType.DATA,
            sync_id=sync_id,
            payload=payload,
            source="__input__",
        )

        with self.__futures_lock:
            self.__futures[sync_id] = future

        for q in self.__input_queues:
            q.put(input_msg)

        return future

    def execute(self, pyload: Any, timeout: float | None = None) -> list[Any]:
        future = self.submit(pyload)
        return cast(list[Any], future.get(timeout=timeout))

    def action(self, data: Any):
        action_msg = Message(
            type=MessageType.ACTION,
            sync_id=0,
            payload=data,
            source="host",
        )

        for q in self.__action_queues.values():
            q.put(action_msg)

    def stop(self):
        """Send graceful shutdown signal to all worker processes.

        Enqueues a :data:`MessageType.STOP` message on every worker input
        queue, the final aggregator queue, and closes auxiliary queues so threads
        exit cleanly after draining their pending work.
        """
        self.__stop_event.set()

        stop_msg = Message(
            type=MessageType.STOP,
            sync_id=0,
            payload=None,
            source="host",
        )

        for q in self.__queues.values():
            q.put(stop_msg)
        self.__final_queue.put(stop_msg)

        self.__health_queue.put(None)
        self.__time_queue.put(None)

    def terminate(self):
        """Send ``SIGTERM`` (or platform equivalent) to all worker processes."""
        for p in self.__processes.values():
            p.terminate()

    def kill(self):
        """Send ``SIGKILL`` (or platform equivalent) to all worker processes."""
        for p in self.__processes.values():
            p.kill()

    def join(self, timeout: float | None = None):
        """Wait for all worker processes to exit.

        Args:
            timeout: Maximum seconds to wait per process; ``None`` blocks
                indefinitely.
        """
        for p in self.__processes.values():
            p.join(timeout)

    def dispose(self, wait_seconds: float | None = None):
        """Gracefully shut down the executor, then force-kill lingering workers.

        Sequence:
            1. Call :meth:`stop` to send graceful stop.
            2. Wait up to ``wait_seconds`` for workers to join.
            3. Call :meth:`terminate` on survivors.
            4. Join again briefly.

        Args:
            wait_seconds: Grace period for workers to drain before
                ``terminate`` is issued. Defaults to ``1`` second.
        """
        if wait_seconds is None:
            wait_seconds = 1

        def wait():
            wait_until = time.perf_counter() + wait_seconds
            for p in self.__processes.values():
                now = time.perf_counter()
                if now >= wait_until:
                    break
                p.join(wait_until - now)

        self.stop()

        # first join wait process end
        wait()

        dead = True
        for p in self.__processes.values():
            if p.is_alive():
                dead = False
                p.terminate()

        if dead:
            return

        # then join wait process receive signal and handle it
        wait()

        for p in self.__processes.values():
            if p.is_alive():
                p.kill()

        # finally join wait process killed
        for p in self.__processes.values():
            p.join()

        self._clear()


def main():
    pass


if __name__ == "__main__":
    main()
