# -*- coding: utf-8 -*-

import copy
import time
from collections import defaultdict
from typing import Any

from seetapsych_lib import api
from seetapsych_lib.runtime.actions import load_package
from seetapsych_lib.runtime.model import build_model
from seetapsych_lib.runtime.pipeline import Pipeline
from seetapsych_lib.utils.cuda import list_nvidia_devices
from seetapsych_lib.utils.logger import logger

__all__ = [
    "Runner",
    "PipelineHasProblem",
    "PipelineUnsatisfied",
    "MissingInputModal",
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


class Runner:
    """Sequential pipeline executor.

    Instantiates each package from a resolved :class:`Pipeline`, caches the
    required models, and runs inference over input frames in order.
    """

    def __init__(
        self,
        pipeline: Pipeline,
        device: api.Device | str | None = None,
        *,
        cache_dir: str | None = None,
        profile: bool = False,
    ):
        """Initialize a Runner.

        The device is auto-detected by default: NVIDIA GPU if available,
        otherwise CPU. ``"auto"`` (or a Device with type ``"auto"``) triggers
        the same behaviour.

        Args:
            pipeline: A solved and satisfied Pipeline configuration.
            device: Target execution device. Accepts:

                * :class:`api.Device` — an explicit device descriptor.
                * A bare backend string — ``"cpu"``, ``"cuda"``, ``"gpu"``
                  (aliased to ``"cuda"``).
                * A colon-indexed string to pick a specific physical card:
                  ``"cuda:0"``, ``"cuda:1"``, ``"cuda:2"`` … the suffix is
                  parsed as the zero-based device index.
                * ``"auto"`` or ``None`` — auto-select from available GPUs,
                  fall back to CPU when no GPU is detected.
            cache_dir: Override the model cache directory.
            profile: When True, record per-package inference timings and
                expose them via :meth:`time_summary`.

        Raises:
            PipelineHasProblem: If ``pipeline`` still has unresolved
                dependency problems (call :meth:`Pipeline.solve` first).
            PipelineUnsatisfied: If runtime prerequisites (requirements,
                imports, cached models) are missing (call
                :meth:`Pipeline.install_requirements` /
                :meth:`Pipeline.cache_models` first).
        """
        if isinstance(device, str):
            device = api.Device(device)

        if device is None or not device.type or device.type.lower() == "auto":
            nvidia_devices = list_nvidia_devices()
            if nvidia_devices:
                device_info = "\n".join([f"    - {d}" for d in nvidia_devices])
                logger.info(f"Detected {len(nvidia_devices)} NVIDIA GPU(s).\n{device_info}")
                device = api.Device("cuda")
            else:
                logger.info("No NVIDIA GPU or compatible driver detected.")
                device = api.Device("cpu")

        self.__start_frame_tick = 1

        self.__device = device
        self.__cache_dir = cache_dir
        self.__pipeline = pipeline.config.model_copy(deep=True)
        self.__instances: list[api.Instance] = []
        self.__inputs = pipeline.inputs
        self.__frame_tick = self.__start_frame_tick

        # is pipeline no problem and satisfied?
        problem = pipeline.problem()
        if problem:
            raise PipelineHasProblem(problem)

        satisfied, unsatisfaction = pipeline.satisfied()
        if not satisfied:
            raise PipelineUnsatisfied(unsatisfaction)

        # build pipeline instance
        for package in pipeline.config.packages:
            loaded_package = load_package(package)

            # get models and parameters
            config_models = pipeline.config.models.get(package.uid, [])
            config_parameters = pipeline.config.parameters.get(package.uid, [])

            models: list[api.UsageModel] = []
            for model_config in config_models:
                models.append(build_model(model_config, cache_dir=cache_dir))

            parameters: dict[str, Any] = {}
            for param in package.parameters:
                parameters[param.name] = param.value
            for param in config_parameters:
                parameters[param.name] = param.value

            # central cache models
            for model in models:
                model.cache()

            instance = loaded_package.create(models=models, parameters=parameters, device=device)
            self.__instances.append(instance)

        self.__profile = profile
        self.__time_summary = TimeSummary()

    @property
    def inputs(self) -> list[str]:
        """Return the required input modal names for :meth:`run`."""
        return self.__inputs

    def run(self, data: dict[str, Any] | Any, timestamp: float | None = None) -> dict[str, Any]:
        """Run inference on a single input frame.

        Args:
            data: Either a single payload for the ``"default"`` modal, or a
                dict mapping modal names to their payloads.
            timestamp: Optional wall-clock timestamp for the frame. Defaults
                to :func:`time.time` when omitted.

        Returns:
            The accumulated attribute report dictionary, including the
            injected ``"time"`` and ``"frame_tick"`` metadata fields.

        Raises:
            MissingInputModal: If ``data`` is missing any required modal
                (see :attr:`inputs`).
        """
        if not self.__instances:
            return {}

        # get timestamp
        if timestamp is None:
            timestamp = time.time()

        # check input modals
        if not isinstance(data, dict):
            data = {"default": data}

        missing_modals = [modal for modal in self.__inputs if modal not in data]
        if missing_modals:
            raise MissingInputModal(missing_modals)

        reports = []
        updates = []
        report = {
            "time": timestamp,
            "frame_tick": self.__frame_tick,
        }

        # inference each instance
        for package, instance in zip(self.__pipeline.packages, self.__instances, strict=True):
            start_time_seconds = time.perf_counter()
            update = instance.inference(data=data, report=report)
            time_seconds = time.perf_counter() - start_time_seconds

            if update:
                report.update(update)

            updates.append(copy.deepcopy(update))
            reports.append(copy.deepcopy(report))

            if self.__profile:
                self.__time_summary.add(package.name, time_seconds)

        self.__frame_tick += 1

        return report

    def reset(self):
        """Reset per-frame state and all package instances.

        Reverts the internal frame tick and calls ``reset()`` on every
        created package instance (clears any per-session state such as
        running trackers or smoothing buffers).
        """
        self.__frame_tick = self.__start_frame_tick
        for instance in self.__instances:
            instance.reset()

    def dispose(self):
        """Release resources held by all package instances."""
        for instance in self.__instances:
            instance.dispose()
        self.__instances.clear()

    def time_summary(self) -> dict[str, float]:
        """Return per-package average inference times.

        Returns:
            Mapping of package name to average elapsed seconds, rounded to
            three decimal places. Meaningful only when profiling was enabled
            via the constructor ``profile`` flag.
        """
        return self.__time_summary.summary()


def test():
    pass


if __name__ == "__main__":
    test()
