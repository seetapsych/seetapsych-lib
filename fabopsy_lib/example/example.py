# -*- coding: utf-8 -*-

import json
import time
from typing import Any

import numpy

from fabopsy_lib import api


class ExampleInstance(api.Instance):
    def __init__(self, model_path: str, device: api.Device):
        time.sleep(1)

        self.__model_path = model_path
        self.__device = device

    def inference(self, *, data: dict[str, Any], report: dict[str, Any], **kwargs) -> dict[str, Any]:
        # print(f'Data: {data}')

        time.sleep(0.01)

        default_input = data['default']
        image = numpy.ascontiguousarray(default_input)

        print(f'Input default: {type(image)} {image.shape}')

        return {
            'example_output': {
                'values': [None, 12, 12.4, 'fff', False],
                'shape': list(image.shape),
                'output': [1, 2, 3],
                'model': self.__model_path,
                'device': None if self.__device is None else str(self.__device),
            },
        }


class Package(api.Package):
    def create(self, *, models: list[api.Model], parameters: dict[str, Any], device: api.Device | None,
               **kwargs) -> api.Instance:
        assert len(models) >= 1, api.MissingModelError('At least one model required')

        if device is None:
            device = api.Device('cpu')

        json_parameters = json.dumps(parameters, indent=2, ensure_ascii=False)
        print(f'Parameters: {json_parameters}')

        model_path = models[0].cache()
        return ExampleInstance(model_path, device)


def load_package() -> api.Package:
    return Package()


example_model_cached = False


class ExampleModel(api.Model):
    def __init__(self, path: str):
        self.__path = path

    def exists(self) -> bool:
        global example_model_cached

        return example_model_cached

    def cache(self) -> str:
        global example_model_cached

        if self.exists():
            return self.__path

        time.sleep(1)

        example_model_cached = True
        return self.__path


def load_model() -> api.Model:
    return ExampleModel('non-exists-model.bin')
