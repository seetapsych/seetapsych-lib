# -*- coding: utf-8 -*-

from typing import Optional, Any, Iterable, Sequence

import onnxruntime

from seetapsych_lib import api

__all__ = [
    'OnnxSession',
]

class OnnxSession(object):
    """
    OnnxSession is a helper class to easy use onnxruntime with cuda and cpu backend.
    Support device: cpu, cuda, cuda:0, cuda:1, ...
    """
    def __init__(self, onnx_file: str, device: api.Device = None, sess_options: onnxruntime.SessionOptions = None):
        available_providers = onnxruntime.get_available_providers()
        if 'CUDAExecutionProvider' in available_providers:
            device: Optional[api.Device]
            if device is None:
                providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            elif not device.type == 'cuda':
                providers = ['CPUExecutionProvider']
            else:
                device_id = device.index
                if device_id is None:
                    providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                else:
                    providers = [('CUDAExecutionProvider', {'device_id': device_id}), 'CPUExecutionProvider']
        else:
            providers = ['CPUExecutionProvider']

        self.__session = onnxruntime.InferenceSession(
            onnx_file, sess_options=sess_options, providers=providers)
        self.__onnx_file = onnx_file

        self.__input_names = [node.name for node in self.__session.get_inputs()]
        self.__output_names = [node.name for node in self.__session.get_outputs()]

    @property
    def session(self) -> onnxruntime.InferenceSession:
        return self.__session

    @property
    def input_names(self) -> list[str]:
        return self.__input_names

    @property
    def output_names(self) -> list[str]:
        return self.__output_names

    def __build_sequence_input(self, data: Iterable[Any]) -> dict[str, Any]:
        return {
            self.input_names[int(i)]: v for i, v in enumerate(data)
        }

    def forward(self, inputs: list[Any] | dict[str, Any],
                outputs: list[str] = None, run_options: onnxruntime.RunOptions = None) -> Sequence[Any]:
        input_feed: dict[str, Any]
        match inputs:
            case tuple(x):
                input_feed = self.__build_sequence_input(x)
            case list(x):
                input_feed = self.__build_sequence_input(x)
            case dict(x):
                missing_input_keys = set(self.input_names) - inputs.keys()
                if missing_input_keys:
                    raise RuntimeError(f'input required: {list(missing_input_keys)}')
                input_feed = x
            case _:
                raise RuntimeError('inputs should be tuple, list, or dict')

        output_names = outputs or self.output_names
        return self.__session.run(output_names, input_feed, run_options=run_options)


def main():
    pass


if __name__ == '__main__':
    main()
