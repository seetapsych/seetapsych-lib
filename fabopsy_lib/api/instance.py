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

    def reset(self):
        """
        Reset the status after completing a segment of data processing,
          to proceed with the next segment of data processing.
        """
        pass

    def dispose(self):
        """
        It will be called when the instance is confirmed to be no longer in use, for timely resource release.
        """
        pass
