# -*- coding: utf-8 -*-

from abc import ABC, abstractmethod
from typing import Any

from .device import Device
from .instance import Instance
from .model import Model

__all__ = [
    'Package',
]


class Package(ABC):
    @abstractmethod
    def create(self, models: list[Model], attributes: dict[str, Any], device: Device) -> Instance:
        ...

