# -*- coding: utf-8 -*-

from abc import ABC, abstractmethod
from typing import Any

__all__ = [
    "Model",
    "UsageModel",
]


class Model(ABC):
    @property
    def metadata(self) -> dict[str, Any]:
        """
        Get model's metadata.
        :return:
        """
        return {}

    @abstractmethod
    def exists(self) -> bool:
        """
        Check whether the model already exists.
        :return:
        """
        ...

    @abstractmethod
    def cache(self) -> str:
        """
        Cache model from host or use directly local file path.
        If `self.exists` returns true, the cached path should be directly
        returned without extra download. The consistency of cache state
        detection should be ensured by the implementation.
        :return:
        """
        ...


class UsageModel(Model, ABC):
    @property
    def usage(self) -> str:
        """
        This model usage. Must be provided while using multi models instance.
        :return: Model usage. Should be same with module config file.
        """
        return ""


if __name__ == "__main__":
    pass
