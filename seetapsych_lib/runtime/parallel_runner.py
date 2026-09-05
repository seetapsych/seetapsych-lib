# -*- coding: utf-8 -*-

import copy
import time
from dataclasses import dataclass
from typing import Any, Literal

from seetapsych_lib import api, schema
from seetapsych_lib.runtime.actions import load_package
from seetapsych_lib.runtime.model import build_model
from seetapsych_lib.runtime.parallel.executor import Executor, ParallelExecutor
from seetapsych_lib.runtime.parallel.future import Future, WritableFuture
from seetapsych_lib.runtime.pipeline import Pipeline
from seetapsych_lib.runtime.runner import MissingInputModal, PipelineHasProblem, PipelineUnsatisfied
from seetapsych_lib.utils.cuda import list_nvidia_devices
from seetapsych_lib.utils.logger import logger

__all__ = [
    "ParallelRunner",
]


class PackageNode:
    """Node in the package dependency graph.

    Aggregates one or more packages that share the same dependency level,
    exposing the union of provided/required attributes and incoming edges.
    """

    def __init__(self, packages: list[schema.Package], inputs: list["PackageNode"] | None = None):
        """Initialize a package graph node.

        Args:
            packages: Packages grouped under this node (typically one).
            inputs: Predecessor nodes providing the required attributes.
        """
        if inputs is None:
            inputs = []

        requires: list[str] = []
        provides: list[str] = []
        for p in packages:
            requires.extend(p.requires)
            provides.extend((set(p.provides) - set(p.requires)))

        self.__provides = sorted(list(set(provides)))
        self.__requires = sorted(list(set(requires)))
        self.__packages = packages
        self.__inputs = inputs

    def __hash__(self) -> int:
        """Hash by object identity (graph nodes are unique)."""
        return id(self)

    @property
    def provides(self) -> list[str]:
        """Return sorted, deduplicated attribute names provided by this node."""
        return self.__provides

    @property
    def requires(self) -> list[str]:
        """Return sorted, deduplicated attribute names required by this node."""
        return self.__requires

    @property
    def package(self) -> schema.Package:
        """Return the first package stored in this node (for single-package nodes)."""
        return self.__packages[0]

    @property
    def packages(self) -> list[schema.Package]:
        """Return all packages stored in this node."""
        return self.__packages

    @property
    def inputs(self) -> list["PackageNode"]:
        """Return predecessor nodes in the dependency graph."""
        return self.__inputs


def build_graph(packages: list[schema.Package]) -> list[PackageNode]:
    """Build a dependency graph from an ordered package list.

    Each package becomes a :class:`PackageNode` whose incoming edges are the
    nodes providing its required attributes.

    Args:
        packages: Topologically ordered packages from a resolved pipeline.

    Returns:
        A list of :class:`PackageNode` in the same order as ``packages``.

    Raises:
        RuntimeError: If a required attribute has no provider among the
            previously processed packages.
    """
    node_providers: dict[str, PackageNode] = {}
    nodes: list[PackageNode] = []

    for p in packages:
        inputs: list[PackageNode] = []
        for attr in p.requires:
            inode = node_providers.get(attr, None)
            if inode is None:
                raise RuntimeError(f"Can not find attribute provider for {attr}")
            inputs.append(inode)
        inputs = list(set(inputs))
        node = PackageNode(packages=[p], inputs=inputs)

        nodes.append(node)
        for attr in p.provides:
            node_providers[attr] = node

    return nodes


@dataclass
class ExchangeData:
    """Payload passed between nodes in the parallel execution graph.

    Attributes:
        data: Input modals (shared reference across nodes).
        report: Accumulated attribute report for the current frame.
    """

    data: dict[str, Any]
    report: dict[str, Any]


@dataclass
class ExchangeAction:
    """Control message broadcast to all parallel executors.

    Attributes:
        action: Action type; currently only ``"reset"`` is defined.
    """

    action: Literal["reset"]


class PackageExecutor(Executor):
    """Per-package worker for parallel pipeline execution.

    Implements the :class:`Executor` protocol required by
    :class:`ParallelExecutor`. Handles lazy package instantiation, control
    actions (reset), and inference with report merging from multiple inputs.
    """

    def __init__(
        self,
        package: schema.Package,
        models: list[schema.Model],
        parameters: list[schema.Parameter],
        device: api.Device | None = None,
        *,
        cache_dir: str | None = None,
    ):
        """Initialize a package executor.

        The actual package instance is created lazily in :meth:`init`.

        Args:
            package: Package spec to instantiate.
            models: Selected model specs for this package.
            parameters: Parameter overrides for this package.
            device: Target device for model inference. Accepts a
                :class:`api.Device`, a bare backend string (``"cpu"``,
                ``"cuda"``, ``"gpu"``), a colon-indexed string to pick a
                specific card (e.g. ``"cuda:1"``), or ``None`` to fall back
                to the runner-level device selection.
            cache_dir: Override model cache directory.
        """
        self.__package = package
        self.__models = models
        self.__parameters = parameters

        self.__device = device
        self.__cache_dir = cache_dir

        self.__instance: api.Instance | None = None

    def __hash__(self) -> int:
        """Hash by object identity."""
        return id(self)

    def init(self):
        """Instantiate the package, build and cache models, allocate device resources."""
        package = self.__package
        _cfg_models = self.__models
        _cfg_parameters = self.__parameters
        device = self.__device
        cache_dir = self.__cache_dir

        loaded_package = load_package(package)

        config_models = _cfg_models
        config_parameters = _cfg_parameters

        usage_models: list[api.UsageModel] = []
        for model_config in config_models:
            usage_models.append(build_model(model_config, cache_dir=cache_dir))

        parameter_dict: dict[str, Any] = {}
        for param in package.parameters:
            parameter_dict[param.name] = param.value
        for param in config_parameters:
            parameter_dict[param.name] = param.value

        for model in usage_models:
            model.cache()

        instance = loaded_package.create(models=usage_models, parameters=parameter_dict, device=device)
        self.__instance = instance

    def action(self, data: ExchangeAction):
        """Handle a control action broadcast from the runner.

        Args:
            data: Action descriptor.

        Raises:
            RuntimeError: If :meth:`init` has not been called yet.
        """
        if self.__instance is None:
            raise RuntimeError("PackageExecutor not initialized: call init() before action()")

        match data.action:
            case "reset":
                self.__instance.reset()

    def run(self, *args: ExchangeData) -> ExchangeData:
        """Run inference on a frame, merging reports from all input nodes.

        Args:
            *args: One or more :class:`ExchangeData` inputs from predecessor
                nodes. The first input supplies the shared ``data`` payload;
                subsequent inputs contribute their report entries on top.

        Returns:
            A new :class:`ExchangeData` with the merged report updated by
            this package's inference output.

        Raises:
            RuntimeError: If :meth:`init` has not been called yet.
        """
        if self.__instance is None:
            raise RuntimeError("PackageExecutor not initialized: call init() before run()")

        data = args[0].data
        report = copy.copy(args[0].report)
        for u in args[1:]:
            report.update(u.report)
        output = self.__instance.inference(data=data, report=report)
        report.update(output)
        return ExchangeData(
            data=data,
            report=report,
        )


class ParallelRunner:
    """Parallel pipeline executor based on a dependency-aware thread pool.

    Builds a DAG of the pipeline packages, dispatches each node to a
    :class:`PackageExecutor` scheduled by a :class:`ParallelExecutor`, and
    merges reports when nodes have multiple predecessors. Supports per-attribute
    device pinning via a device map.
    """

    def __init__(
        self,
        pipeline: Pipeline,
        device: api.Device | str | dict[str, api.Device | str] | None = None,
        *,
        cache_dir: str | None = None,
        profile: bool = False,
    ):
        """Initialize a ParallelRunner.

        Device resolution order:
            1. Per-attribute entry in the ``device`` dict (if a dict is given).
            2. Global ``device`` override.
            3. Round-robin from the detected GPU/CPU pool.

        The empty-key ``""`` or underscore ``"_"`` entry in a device dict is
        treated as the fallback global device.

        Args:
            pipeline: A solved and satisfied Pipeline configuration.
            device: Execution device specification. In every position below,
                a device may be given as a :class:`api.Device`, a bare
                backend string (``"cpu"``, ``"cuda"``, ``"gpu"``), or a
                colon-indexed string to select a specific physical card
                (e.g. ``"cuda:0"``, ``"cuda:1"``). Accepted shapes:

                * :class:`api.Device` or ``str`` — global device applied to
                  every package.
                * ``dict`` mapping attribute name (or ``""`` / ``"_"`` for
                  default) to a device for per-attribute pinning.
                * ``None`` or ``"auto"`` — round-robin from available GPUs,
                  fall back to CPU when no GPU is detected.
            cache_dir: Override the model cache directory.
            profile: When True, record per-executor timings exposed via
                :meth:`time_summary`.

        Raises:
            PipelineHasProblem: If ``pipeline`` still has unresolved
                dependency problems.
            PipelineUnsatisfied: If runtime prerequisites are missing.
        """
        self.__parallel_executor: ParallelExecutor | None = None

        global_device: api.Device | None = None
        attribute_device_map: dict[str, api.Device] = {}
        device_pool: list[api.Device] = []

        if isinstance(device, str):
            device = api.Device(device)

        if device is None or isinstance(device, dict) or not device.type or device.type.lower() == "auto":
            # auto select device
            if isinstance(device, dict):
                for attr, dev in device.items():
                    if isinstance(dev, str):
                        dev = api.Device(dev)
                    attribute_device_map[attr] = dev
            # list nvidia devices
            nvidia_devices = list_nvidia_devices()
            if nvidia_devices:
                device_info = "\n".join([f"    - {d}" for d in nvidia_devices])
                logger.info(f"Detected {len(nvidia_devices)} NVIDIA GPU(s).\n{device_info}")
                device_pool.extend([api.Device("cuda", i) for i in range(len(nvidia_devices))])
            else:
                logger.info("No NVIDIA GPU or compatible driver detected.")
                device_pool.extend([api.Device("cpu")])
        else:
            assert isinstance(device, api.Device)
            global_device = device

        if global_device is None:
            global_device = attribute_device_map.get("", None) or attribute_device_map.get("_", None)

        select_index = 0

        def select_device(p: schema.Package) -> api.Device:
            # check attribute map
            for a in p.provides:
                d = attribute_device_map.get(a, None)
                if d is not None:
                    return d

            # check global
            if global_device is not None:
                return global_device

            # device pool is empty
            if not device_pool:
                return api.Device("cpu")

            # random select from pool
            nonlocal select_index
            d = device_pool[select_index]

            select_index += 1
            select_index %= len(device_pool)

            return d

        self.__start_frame_tick = 1

        self.__device = device
        self.__cache_dir = cache_dir
        self.__pipeline = pipeline.config.model_copy(deep=True)
        self.__inputs = pipeline.inputs
        self.__frame_tick = self.__start_frame_tick

        # is pipeline no problem and satisfied?
        problem = pipeline.problem()
        if problem:
            raise PipelineHasProblem(problem)

        satisfied, unsatisfaction = pipeline.satisfied()
        if not satisfied:
            raise PipelineUnsatisfied(unsatisfaction)

        parallel_executor = ParallelExecutor(profile=profile)

        package_nodes = build_graph(pipeline.config.packages)
        node_executor_ids: dict[PackageNode, int] = {}
        for node in package_nodes:
            package = node.package

            models = pipeline.config.models.get(package.uid, [])
            parameters = pipeline.config.parameters.get(package.uid, [])

            dev = select_device(package)
            logger.info(f'Dispatching "{package.name}" to "{dev}"')
            executor = PackageExecutor(package, models, parameters, device=dev, cache_dir=cache_dir)

            input_ids = [node_executor_ids[i] for i in node.inputs]

            node_id = parallel_executor.register(package.name, executor, input_ids)

            node_executor_ids[node] = node_id

        parallel_executor.start()
        self.__parallel_executor = parallel_executor
        self.__graph = package_nodes

    @property
    def inputs(self) -> list[str]:
        """Return the required input modal names for :meth:`run` / :meth:`run_async`."""
        return self.__inputs

    def run_async(
        self,
        data: dict[str, Any] | Any,
        timestamp: float | None = None,
    ) -> Future[dict[str, Any]]:
        """Submit a frame for parallel inference and return a future.

        This method returns immediately without blocking; call
        :meth:`Future.get` on the returned object (or use :meth:`run`) to
        wait for the result.

        Args:
            data: Either a single payload for the ``"default"`` modal, or a
                dict mapping modal names to their payloads.
            timestamp: Optional wall-clock timestamp for the frame. Defaults
                to :func:`time.time` when omitted.

        Returns:
            A :class:`Future` resolving to the accumulated attribute report.

        Raises:
            RuntimeError: If the runner has been disposed or was not properly
                initialized.
            MissingInputModal: If ``data`` is missing any required modal.
        """
        if self.__parallel_executor is None:
            raise RuntimeError("ParallelRunner not initialized")

        if not self.__graph:
            future_result: WritableFuture[dict[str, Any]] = WritableFuture()
            future_result.set_result({})
            return future_result

        # get timestamp
        if timestamp is None:
            timestamp = time.time()

        # check input modals
        if not isinstance(data, dict):
            data = {"default": data}

        missing_modals = [modal for modal in self.__inputs if modal not in data]
        if missing_modals:
            raise MissingInputModal(missing_modals)

        report = {
            "time": timestamp,
            "frame_tick": self.__frame_tick,
        }
        self.__frame_tick += 1

        exchange_data = ExchangeData(
            data=data,
            report=report,
        )

        def merge_data(output_data: list[ExchangeData]) -> dict[str, Any]:
            local_report = copy.copy(report)
            for ex in output_data:
                local_report.update(ex.report)
            return local_report

        future = self.__parallel_executor.submit(exchange_data, cascade=merge_data)

        return future

    def run(
        self,
        data: dict[str, Any] | Any,
        timestamp: float | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run inference on a single frame and wait for the result.

        Convenience wrapper equivalent to
        ``run_async(data, timestamp).get(timeout=timeout)``.

        Args:
            data: Either a single payload or a modal-to-payload dict.
            timestamp: Optional wall-clock timestamp for the frame.
            timeout: Maximum seconds to wait. ``None`` blocks indefinitely.

        Returns:
            The accumulated attribute report dictionary.

        Raises:
            RuntimeError: If the runner is disposed or uninitialized.
            MissingInputModal: If required input modals are missing.
            TimeoutError: If the result is not ready within ``timeout``.
        """
        return self.run_async(data, timestamp).get(timeout=timeout)

    def reset(self):
        """Reset frame counter and broadcast ``reset`` to all package executors.

        Raises:
            RuntimeError: If the runner has been disposed or was not properly
                initialized.
        """
        if self.__parallel_executor is None:
            raise RuntimeError("ParallelRunner not initialized")

        self.__frame_tick = self.__start_frame_tick

        exchange_action = ExchangeAction(action="reset")
        self.__parallel_executor.action(exchange_action)

    def dispose(self):
        """Stop the parallel executor and release all worker resources."""
        if self.__parallel_executor is not None:
            self.__parallel_executor.dispose()

    def __del__(self):
        """Destructor ensuring :meth:`dispose` is called."""
        self.dispose()

    def time_summary(self) -> dict[str, float]:
        """Return per-executor average inference times.

        Returns:
            Mapping of executor tag to average elapsed seconds. An empty
            dict is returned when profiling is disabled or the runner has
            been disposed.
        """
        if self.__parallel_executor is not None:
            return self.__parallel_executor.time_summary()
        return {}


def test():
    pass


if __name__ == "__main__":
    test()
