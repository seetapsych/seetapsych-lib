# -*- coding: utf-8 -*-

from abc import ABC, abstractmethod

__all__ = [
    'Model',
    'UsageModel',
]

class Model(ABC):
    @abstractmethod
    def cache(self, cache_dir: str | None = None) -> str:
        """
        Cache model from host or use directly local file path
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
        return ''


if __name__ == '__main__':
    pass
