# -*- coding: utf-8 -*-

from abc import ABC, abstractmethod

__all__ = [
    'Model',
]

class Model(ABC):
    @property
    @abstractmethod
    def usage(self) -> str:
        """
        This model usage. Must be provided while using multi models instance.
        :return: Model usage. Should be same with module config file.
        """
        ...

    @property
    @abstractmethod
    def cache(self) -> str:
        """
        Cache model from host or use directly local file path
        :return:
        """
        ...


if __name__ == '__main__':
    pass
