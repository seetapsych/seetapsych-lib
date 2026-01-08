# -*- coding: utf-8 -*-

from abc import ABC, abstractmethod
from typing import Any

__all__ = [
    'Instance',
]


class Instance(ABC):
    @abstractmethod
    def inference(self, data: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        """
        Call a frame of data.
        :param data: dict[str, numpy.ndarray]
        :param report: dict[str, Any]
        :return:
        The report has some predefined system parameters, such as "time" which represents a Unix timestamp.
        """
        ...
