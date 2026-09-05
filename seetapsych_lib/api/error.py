# -*- coding: utf-8 -*-

"""Public exception hierarchy for the seetapsych-lib API layer.

Library-level code can raise these exceptions directly in application code.
All custom API exceptions are subclasses of :class:`Error`, which in turn
inherits from the built-in :class:`Exception` so callers may use a single
``except Exception`` clause when they do not care about granularity.
"""


class Error(Exception):
    """Base class for every seetapsych-lib raised exception.

    Catch this type to handle all library-originated errors together with
    ``except seetapsych_lib.api.Error``. Subclass it for domain-specific
    error categories that do not belong to a specific runner/schema layer.
    """


class MissingModelError(Error):
    """Raised when a package loader requires a cached model but cannot find it.

    Typical triggers include:
        * The model cache directory is empty or points at the wrong location.
        * The model configuration lists a ``usage`` key that no available
          :class:`seetapsych_lib.api.UsageModel` advertises.
        * The cloud/download/entry model descriptor is misconfigured.
    """
