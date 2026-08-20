# -*- coding: utf-8 -*-

import copy
import time
from dataclasses import dataclass
from typing import Any, Optional, Literal

from fabopsy_lib import api
from fabopsy_lib.runtime.actions import load_package
from fabopsy_lib.runtime.model import build_model
from fabopsy_lib.runtime.pipeline import Pipeline
from fabopsy_lib.utils.cuda import list_nvidia_devices
from fabopsy_lib.utils.logger import logger
from fabopsy_lib import schema
from fabopsy_lib.runtime.parallel.executor import Executor, ParallelExecutor
from fabopsy_lib.runtime.parallel.future import Future, WritableFuture
from fabopsy_lib.runtime.runner import PipelineHasProblem, PipelineUnsatisfied, MissingInputModal


__all__ = [
    'ParallelRunner',
]


class PackageNode(object):
    def __init__(self, packages: list[schema.Package], inputs: list['PackageNode'] = None):
        if inputs is None:
            inputs = []

        requires = []
        provides = []
        for p in packages:
            requires.extend(p.requires)
            provides.extend((set(p.provides) - set(p.requires)))

        self.__provides = sorted(list(set(provides)))
        self.__requires = sorted(list(set(requires)))
        self.__packages = packages
        self.__inputs = inputs

    def __hash__(self):
        return id(self)

    @property
    def provides(self) -> list[str]:
        return self.__provides

    @property
    def requires(self) -> list[str]:
        return self.__requires

    @property
    def package(self) -> schema.Package:
        return self.__packages[0]

    @property
    def packages(self) -> list[schema.Package]:
        return self.__packages

    @property
    def inputs(self) -> list['PackageNode']:
        return self.__inputs


def build_graph(packages: list[schema.Package]) -> list[PackageNode]:
    node_providers: dict[str, PackageNode] = {}
    nodes: list[PackageNode] = []
    # outputs: set[PackageNode] = set()
    # node_outputs: dict[PackageNode, list[PackageNode]] = defaultdict([])

    # basic build graph
    for p in packages:
        inputs: list[PackageNode] = []
        # find providers
        for attr in p.requires:
            inode = node_providers.get(attr, None)
            if inode is None:
                raise RuntimeError(f'Can not find attribute provider for {attr}')
            inputs.append(inode)
        inputs = list(set(inputs))
        node = PackageNode(packages=[p], inputs=inputs)

        # outputs.add(node)
        nodes.append(node)
        for attr in p.provides:
            node_providers[attr] = node
        # for inode in inputs:
        #     outputs.remove(inode)
        #     node_outputs[inode].append(node)

    return nodes


@dataclass
class ExchangeData:
    data: dict[str, Any]
    report: dict[str, Any]

@dataclass
class ExchangeAction:
    action: Literal['reset']


class PackageExecutor(Executor):
    def __init__(
            self,
            package: schema.Package,
            models: list[schema.Model],
            parameters: list[schema.Parameter],
            device: api.Device = None, *, cache_dir: str = None):
        self.__package = package
        self.__models = models
        self.__parameters = parameters

        self.__device = device
        self.__cache_dir = cache_dir

        self.__instance: Optional[api.Instance] = None

    def __hash__(self):
        return id(self)

    def init(self):
        package = self.__package
        models = self.__models
        parameters = self.__parameters
        device = self.__device
        cache_dir = self.__cache_dir

        loaded_package = load_package(package)

        # get models and parameters
        config_models = models
        config_parameters = parameters

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
        self.__instance = instance

    def action(self, data: ExchangeAction):
        assert self.__instance is not None

        match data.action:
            case 'reset':
                self.__instance.reset()

    def run(self, *args: ExchangeData) -> ExchangeData:
        assert self.__instance is not None

        data = args[0].data
        report = copy.copy(args[0].report)
        # merge report
        for u in args[1:]:
            report.update(u.report)
        output = self.__instance.inference(data=data, report=report)
        report.update(output)
        return ExchangeData(
            data=data,
            report=report,
        )


class ParallelRunner(object):
    def __init__(
            self,
            pipeline: Pipeline,
            device: api.Device | str | dict[str, api.Device | str] = None,
            *, cache_dir: str = None, profile: bool = False):
        self.__parallel_executor: ParallelExecutor | None = None

        global_device: Optional[api.Device] = None
        attribute_device_map: dict[str, api.Device] = {}
        device_pool: list[api.Device] = []

        if isinstance(device, str):
            device = api.Device(device)

        if device is None \
                or isinstance(device, dict) \
                or not device.type \
                or device.type.lower() == 'auto':
            # auto select device
            if isinstance(device, dict):
                for attr, dev in device.items():
                    if isinstance(dev, str):
                        dev = api.Device(dev)
                    attribute_device_map[attr] = dev
            # list nvidia devices
            nvidia_devices = list_nvidia_devices()
            if nvidia_devices:
                device_info = '\n'.join([f'    - {d}' for d in nvidia_devices])
                logger.info(f'Detected {len(nvidia_devices)} NVIDIA GPU(s).\n{device_info}')
                device_pool.extend([api.Device('cuda', i) for i in range(len(nvidia_devices))])
            else:
                logger.info('No NVIDIA GPU or compatible driver detected.')
                device_pool.extend([api.Device('cpu')])
        else:
            assert isinstance(device, api.Device)
            global_device = device

        if global_device is None:
            global_device = attribute_device_map.get('', None) \
                            or attribute_device_map.get('_', None)

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
                return api.Device('cpu')

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
        return self.__inputs

    def run_async(
            self,
            data: dict[str, Any] | Any,
            timestamp: float = None,
    ) -> Future[dict[str, Any]]:
        assert self.__parallel_executor is not None

        if not self.__graph:
            future = WritableFuture()
            future.set_result({})
            return future

        # get timestamp
        if timestamp is None:
            timestamp = time.time()

        # check input modals
        if not isinstance(data, dict):
            data = {'default': data}

        missing_modals = [modal for modal in self.__inputs if modal not in data]
        if missing_modals:
            raise MissingInputModal(missing_modals)

        report = {
            'time': timestamp,
            'frame_tick': self.__frame_tick,
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
            timestamp: float = None,
            timeout: float = None,
    ) -> dict[str, Any]:
        return self.run_async(data, timestamp).get(timeout=timeout)

    def reset(self):
        assert self.__parallel_executor is not None

        self.__frame_tick = self.__start_frame_tick

        exchange_action = ExchangeAction(action='reset')
        self.__parallel_executor.action(exchange_action)

    def dispose(self):
        if self.__parallel_executor is not None:
            self.__parallel_executor.dispose()

    def __del__(self):
        self.dispose()

    def time_summary(self) -> dict[str, float]:
        return self.__parallel_executor.time_summary()


def test():
    pass


if __name__ == '__main__':
    test()
