# -*- coding: utf-8 -*-

from abc import ABC, abstractmethod
from typing import Any

from .device import Device
from .instance import Instance
from .model import UsageModel

__all__ = [
    'Package',
]


class Package(ABC):
    @abstractmethod
    def create(self, *, models: list[UsageModel], parameters: dict[str, Any], device: Device | None,
               **kwargs) -> Instance:
        ...
