# -*- coding: utf-8 -*-

import copy
import time
from typing import Any

from fabopsy_lib import api
from fabopsy_lib.runtime.actions import load_package
from fabopsy_lib.runtime.model import build_model
from fabopsy_lib.runtime.pipeline import Pipeline


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
        self.__device = device
        self.__pipeline = pipeline.config.model_copy(deep=True)
        self.__instances: list[api.Instance] = []
        self.__inputs = pipeline.inputs

        # is pipeline no problem and satisfied?
        problem = pipeline.problem()
        if problem:
            raise PipelineHasProblem(problem)

        satisfied, unsatisfactory = pipeline.satisfied()
        if not satisfied:
            raise PipelineUnsatisfied(unsatisfactory)

        # build pipeline instance
        for package in pipeline.config.packages:
            loaded_package = load_package(package)

            # get models and parameters
            config_models = pipeline.config.models.get(package.uid, [])
            config_parameters = pipeline.config.parameters.get(package.uid, [])

            models: list[api.UsageModel] = []
            for model_config in config_models:
                models.append(build_model(model_config))

            parameters: dict[str, Any] = {}
            for param in package.parameters:
                parameters[param.name] = param.value
            for param in config_parameters:
                parameters[param.name] = param.value

            # central cache models
            for model in models:
                model.cache(cache_dir=cache_dir)

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
            data['default'] = data

        missing_modals = [modal for modal in self.__inputs if modal not in data]
        if missing_modals:
            raise MissingInputModal(missing_modals)

        reports = []
        report = {
            'time': timestamp,
        }

        # inference each
        for instance in self.__instances:
            update = instance.inference(data, report)
            if update:
                report.update(update)
            reports.append(copy.deepcopy(report))

        return report

    def reset(self):
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
