# -*- coding: utf-8 -*-

"""Package loader factory contract.

Each algorithm package registered via the module YAML must expose a concrete
:class:`Package` subclass. The runner calls :meth:`Package.create` to turn a
configuration of models + parameters into a live, device-bound
:class:`Instance` ready for per-frame inference.
"""

from abc import ABC, abstractmethod
from typing import Any

from .device import Device
from .instance import Instance
from .model import UsageModel

__all__ = [
    "Package",
]


class Package(ABC):
    """Factory for producing a device-bound :class:`Instance` from config.

    A :class:`Package` is a lightweight stateless descriptor. Resource
    allocation (GPU memory, file handles, trackers) must happen inside
    :meth:`create` so that the runner owns the resulting :class:`Instance`
    and can reliably call :meth:`Instance.dispose` at teardown.
    """

    @abstractmethod
    def create(
        self,
        *,
        models: list[UsageModel],
        parameters: dict[str, Any],
        device: Device | None,
        **kwargs: Any,
    ) -> Instance:
        """Instantiate an :class:`Instance` ready for per-frame inference.

        The method is expected to:

        1. Load each :class:`UsageModel` from its cached location, asserting
           that its ``usage`` tag matches a slot the package recognises.
        2. Merge ``parameters`` over the package defaults declared in the
           module YAML (see :class:`seetapsych_lib.schema.module.Parameter`).
        3. Route all GPU work to ``device`` (``None`` means the package may
           choose a sensible default, usually CPU).
        4. Return a ready-to-call :class:`Instance` whose
           :meth:`Instance.inference` obeys the package's ``requires`` /
           ``provides`` contract.

        Args:
            models: Model descriptors already cached by the runner. Each
                element's :attr:`UsageModel.usage` must match one of the
                owning package's ``usage_models`` slots.
            parameters: Flat ``{name: value}`` mapping after merging the
                module-level defaults with any Pipeline overrides.
            device: Target compute device. ``None`` allows the package to
                pick a backend itself.
            **kwargs: Reserved for future runner-level extensions such as
                tracing hooks or memory budget hints.

        Returns:
            A freshly constructed :class:`Instance` that has already
            acquired any heavyweight resources (weights, context handles,
            worker threads) it needs.

        Raises:
            seetapsych_lib.api.MissingModelError: If a ``models`` entry is
                missing from disk or does not declare a ``usage`` slot the
                package recognises.
            seetapsych_lib.api.Error: For any other package-specific setup
                failure (unsupported device, bad parameter value, etc.).
        """
        ...
