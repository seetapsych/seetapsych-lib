# -*- coding: utf-8 -*-

import queue
import threading
import time
import traceback
import multiprocessing as mp
from enum import Enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any, Literal
from multiprocessing import synchronize as sc

from fabopsy_lib.utils.logger import logger


__all__ = [
    'Executor',
    'ParallelExecutor',
]


class Executor(ABC):
    """
    The parallel executor in sub process. Witch created in host process and `init` and `run` in sub process.
    """
    @abstractmethod
    def init(self):
        ...

    @abstractmethod
    def run(self, *args, **kwargs):
        ...

    def action(self, data):
        pass


@dataclass
class NodeSpec:
    name: str
    inputs: list[mp.Queue]
    outputs: list[mp.Queue]
    executor: Executor
    health: mp.Queue
    stop: sc.Event


@dataclass
class HealthEvent:
    level: Literal['INFO', 'WARNING', 'ERROR']
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

    def run_action(data):
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
                logger.warning(f'Received inconsistent sync ids {sync_ids}')
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
                output_payload = spec.executor.run(*payloads)
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

    def run(self, *args, **kwargs):
        return args


class ParallelExecutor(object):
    def __init__(self):
        self.__stop_event = mp.Event()
        self.__health_queue = mp.Queue()

        self.__id = 1   # 0 for input, -1 for output
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

        self.__final_queue = mp.Queue()
        self.__final_output: NodeSpec = NodeSpec(
            name='__output__',
            inputs=self.__output_queues,
            outputs=[self.__final_queue],
            executor=GatherExecutor(),
            health=self.__health_queue,
            stop=self.__stop_event,
        )
        self.__nodes[-1] = self.__final_output

        self.__sync_id = 1

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
            q = mp.Queue()
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

    def _clear(self):
        self.__stop_event.clear()

        self.__processes.clear()
        self.__watch_process_threads.clear()
        self.__monitor_threads.clear()

    def start(self):
        if self.__started:
            raise RuntimeError('cannot start a running parallel executor')

        self._compile()

        # the output node has already in self.__nodes
        for i, spec in self.__nodes.items():
            p = mp.Process(
                target=process_node_main,
                name=f'fabopsy:{spec.name}',
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

        # use probe check initialize ready
        try:
            if not self.probe():
                raise RuntimeError('run probe failed after start')
        except RuntimeError:
            self.dispose()
            self._clear()
            raise

    def probe(self) -> bool:
        sync_id = self.__sync_id
        self.__sync_id += 1

        input_msg = Message(
            type=MessageType.PROBE,
            sync_id=sync_id,
            payload=None,
            source='__input__',
        )
        for q in self.__input_queues:
            q.put(input_msg)

        try:
            output_msg: Message = self.__final_queue.get()
        except queue.Empty:
            raise RuntimeError('queue has been closed unexpectedly')

        if output_msg.type != MessageType.PROBE:
            raise RuntimeError(f'probe test failed with message: {output_msg}')

        return output_msg.sync_id == sync_id

    def execute(self, payload: Any, timeout = None) -> list[Any]:
        sync_id = self.__sync_id
        self.__sync_id += 1

        input_msg = Message(
            type=MessageType.DATA,
            sync_id=sync_id,
            payload=payload,
            source='__input__',
        )

        for q in self.__input_queues:
            q.put(input_msg)

        try:
            output_msg: Message = self.__final_queue.get(timeout=timeout)
        except queue.Empty:
            return []

        if output_msg.type == MessageType.DATA:
            return output_msg.payload

        if output_msg.type == MessageType.STOP:
            raise RuntimeError('executor stopped')

        if output_msg.type == MessageType.ERROR:
            raise RuntimeError(f'received error from node {output_msg.source} {output_msg.payload}')

        raise RuntimeError(f'received unexpected message: {output_msg}')

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
        """
        send stop message
        :return:
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

    def terminate(self):
        for p in self.__processes.values():
            p.terminate()

    def kill(self):
        for p in self.__processes.values():
            p.kill()

    def join(self, timeout=None):
        for p in self.__processes.values():
            p.join(timeout)

    def dispose(self, wait_seconds=None):
        """
        send stop message, and wait some time before kill them
        :param wait_timeout:
        :return:
        """
        if wait_seconds is None:
            wait_seconds = 1

        def wait():
            wait_until = time.time() + wait_seconds
            for p in self.__processes.values():
                now = time.time()
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


if __name__ == '__main__':
    main()
