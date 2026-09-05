# -*- coding: utf-8 -*-

"""Compute device descriptors.

A :class:`Device` encodes a compute target (CPU / CUDA / other accelerator)
together with an optional device index. Runners use :class:`Device` to route
package inference calls to the appropriate backend.
"""

device_map: dict[str, str] = {
    "gpu": "cuda",
}
"""Human-friendly alias mapping applied in :class:`Device` constructor."""

single_devices: set[str] = {"cpu"}
"""Device types that do not support multi-index selection in ``__str__``."""


class Device(object):
    """Immutable descriptor for an algorithm execution target.

    Supported shorthand forms accepted by the constructor:

    * Bare type — ``"cpu"``, ``"cuda"``, ``"gpu"`` (aliased to ``"cuda"``).
    * Colon-form index — ``"cuda:0"``, ``"cuda:1"`` parsed as ``(type, index)``.

    ``None`` device values at the runner layer are typically interpreted as
    "auto-select", see :class:`seetapsych_lib.runtime.Runner` and
    :class:`seetapsych_lib.runtime.ParallelRunner`.
    """

    def __init__(self, device_type: str = "cpu", device_index: int | None = None):
        """Initialize a Device descriptor.

        The ``device_type`` string is case-normalised and accepts an optional
        ``:N`` suffix to override ``device_index`` when ``device_index`` is
        ``None``. Known typographical aliases such as ``"gpu"`` are remapped
        via :data:`device_map`.

        Args:
            device_type: Compute type name, e.g. ``"cpu"``, ``"cuda"``,
                ``"gpu"`` or ``"cuda:0"``. Empty string defaults to
                ``"cpu"``.
            device_index: Zero-based physical device ordinal for multi-GPU
                backends. Superceded by any ``:N`` suffix on ``device_type``
                when this argument is ``None``.
        """
        device_type = device_type.strip().lower()

        colon_index = device_type.find(":")
        if colon_index >= 0:
            first, second = device_type[:colon_index], device_type[colon_index + 1 :]
            device_type = first.strip()
            if device_index is None:
                device_index = int(second.strip())

        if not device_type:
            device_type = "cpu"
        if device_type in device_map:
            device_type = device_map[device_type]

        self.type: str = device_type
        """Normalised compute backend name, e.g. ``"cpu"`` or ``"cuda"``."""

        self.index: int | None = device_index
        """Zero-based physical device ordinal, or ``None`` if not pinned."""

    def __str__(self) -> str:
        """Return the canonical device string ``type`` or ``type:index``.

        Returns:
            Short identifier suitable for CLI and log messages. Multi-index
            backends (all except :data:`single_devices`) include the
            ``:index`` suffix whenever pinned.
        """
        if self.index is None or self.type in single_devices:
            return self.type
        else:
            return f"{self.type}:{self.index}"

    def __repr__(self) -> str:
        """Return unambiguous ``Device(type=..., index=...)`` repr.

        Returns:
            Evaluable-ish Python representation used for debugging and
            structured logging.
        """
        dumps = {
            "type": self.type,
            "index": self.index,
        }
        fields = ", ".join([f"{k}={repr(v)}" for k, v in dumps.items() if v is not None])
        return f"Device({fields})"
