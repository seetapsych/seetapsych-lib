# -*- coding: utf-8 -*-

import copy
import time
from typing import Any

from fabopsy_lib import api
from fabopsy_lib.runtime.actions import load_package
from fabopsy_lib.runtime.model import build_model
from fabopsy_lib.runtime.pipeline import Pipeline
from fabopsy_lib.utils.cuda import list_nvidia_devices
from fabopsy_lib.utils.logger import logger


__all__ = [
    'Runner',
]


class PipelineHasProblem(Exception):
    pass


class PipelineUnsatisfied(Exception):
    pass


class MissingInputModal(Exception):
    pass


class Runner(object):
    def __init__(self, pipeline: Pipeline, device: api.Device = None, *, cache_dir: str = None):
        if device is None or not device.type:
            nvidia_devices = list_nvidia_devices()
            if nvidia_devices:
                device_info = '\n'.join([f'    - {d}' for d in nvidia_devices])
                logger.info(f'Detected {len(nvidia_devices)} NVIDIA GPU(s).\n{device_info}')
                device = api.Device('cuda')
            else:
                logger.info('No NVIDIA GPU or compatible driver detected.')
                device = api.Device('cpu')

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

    @property
    def inputs(self) -> list[str]:
        return self.__inputs

    def run(self, data: dict[str, Any] | Any, timestamp: float = None) -> dict[str, Any]:
        if not self.__instances:
            return {}

        # get timestamp
        if timestamp is None:
            timestamp = time.time()

        # check input modals
        if not isinstance(data, dict):
            data = {'default': data}

        missing_modals = [modal for modal in self.__inputs if modal not in data]
        if missing_modals:
            raise MissingInputModal(missing_modals)

        reports = []
        updates = []
        report = {
            'time': timestamp,
            'frame_tick': self.__frame_tick,
        }

        # inference each instance
        for instance in self.__instances:
            update = instance.inference(data=data, report=report)

            if update:
                report.update(update)

            updates.append(copy.deepcopy(update))
            reports.append(copy.deepcopy(report))

        self.__frame_tick += 1

        return report

    def reset(self):
        self.__frame_tick = self.__start_frame_tick
        for instance in self.__instances:
            instance.reset()

    def dispose(self):
        for instance in self.__instances:
            instance.dispose()
        self.__instances.clear()


def test():
    pass


if __name__ == '__main__':
    test()
