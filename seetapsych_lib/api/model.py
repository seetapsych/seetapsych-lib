# -*- coding: utf-8 -*-

"""Model loading interfaces.

Provides the abstract contracts for algorithm model artifacts.
:class:`Model` is the base interface that every concrete model wrapper must
implement (existence check + cache-and-return-path). :class:`UsageModel`
extends it with a ``usage`` slot key so multi-model packages such as
detector+recognition pairs can match :class:`seetapsych_lib.schema.module.Package`
declarations against the concrete models supplied by the user at runtime.
"""

from abc import ABC, abstractmethod
from typing import Any

__all__ = [
    "Model",
    "UsageModel",
]


class Model(ABC):
    """Abstract interface for a loadable/cacheable model artifact."""

    @property
    def metadata(self) -> dict[str, Any]:
        """Return arbitrary model metadata.

        Returns:
            A free-form metadata dictionary. Empty by default.
        """
        return {}

    @abstractmethod
    def exists(self) -> bool:
        """Check whether the model is already present locally.

        Returns:
            True if the model files are available on disk.
        """
        ...

    @abstractmethod
    def cache(self) -> str:
        """Ensure the model is cached locally and return its path.

        Downloads the model from its remote source only when
        :meth:`exists` returns False. Implementations are responsible for
        keeping the exists/cache state consistent.

        Returns:
            Absolute filesystem path to the cached model directory or file.
        """
        ...


class UsageModel(Model, ABC):
    """A :class:`Model` tagged with a usage key for multi-model packages."""

    @property
    def usage(self) -> str:
        """Return the usage identifier for this model slot.

        Must match a usage declared in the module YAML configuration so the
        package can route each incoming usage request to the right model.

        Returns:
            Model usage string matching the module config. Empty by default.
        """
        return ""


if __name__ == "__main__":
    pass
