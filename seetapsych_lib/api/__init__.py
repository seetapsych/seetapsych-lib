# -*- coding: utf-8 -*-

"""Public-facing API surface for seetapsych-lib.

Application code and downstream packages should depend only on symbols
re-exported here rather than importing sub-modules directly, to stay
compatible with future internal refactors.

Exported contracts
------------------
Device          — compute backend descriptor (CPU / CUDA / index)
Error           — base class for all library-originated exceptions
MissingModelError — model cache / selection failure raised by Package.create
Instance        — live per-package runtime handle (inference / reset / dispose)
Model           — cached-artifact contract (existence check + fetch)
UsageModel      — :class:`Model` plus a ``usage`` slot key for multi-model pkgs
Package         — factory that binds models+params+device into an :class:`Instance`
"""

from .device import Device as Device
from .error import Error as Error
from .error import MissingModelError as MissingModelError
from .instance import Instance as Instance
from .model import Model as Model
from .model import UsageModel as UsageModel
from .package import Package as Package

__all__ = [
    "Device",
    "Error",
    "MissingModelError",
    "Instance",
    "Model",
    "UsageModel",
    "Package",
]
