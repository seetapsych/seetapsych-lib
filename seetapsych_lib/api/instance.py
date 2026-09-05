# -*- coding: utf-8 -*-

"""Instantiated package runtime handle.

A :class:`Instance` is produced by :meth:`seetapsych_lib.api.Package.create`
and represents one live, device-bound package ready for per-frame
inference. Runners own a list of :class:`Instance` objects and drive their
lifetime through :meth:`inference` / :meth:`reset` / :meth:`dispose`.
"""

from abc import ABC, abstractmethod
from typing import Any

__all__ = [
    "Instance",
]


class Instance(ABC):
    """Abstract handle for an instantiated algorithm package.

    Encapsulates the lifetime of a single loaded package: per-frame
    inference, per-segment state reset, and resource disposal.
    """

    @abstractmethod
    def inference(self, *, data: dict[str, Any], report: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Run inference on a single frame and return attribute updates.

        The incoming ``report`` dictionary is shared across the entire
        pipeline and already carries system-injected metadata such as
        ``"time"`` (Unix timestamp) and ``"frame_tick"``. Implementations
        may read fields produced by upstream packages and should return a
        (usually partial) mapping of the attributes this package provides.

        Args:
            data: Mapping of modal name to payload (e.g.
                ``{"default": numpy.ndarray}``).
            report: Accumulated report from prior packages in the pipeline.
            **kwargs: Reserved for future runner-level extensions.

        Returns:
            A dictionary of attributes produced by this package, to be
            merged into the overall pipeline report.
        """
        ...

    def reset(self):
        """Reset transient state between independent data segments.

        Use this hook to clear rolling buffers, trackers, or any per-session
        state so the next segment is processed from a clean slate.
        """
        return None

    def dispose(self):
        """Release resources held by this instance.

        Called by the runner when the instance will no longer be used;
        implementations should free GPU memory, close file handles, etc.
        """
        return None
