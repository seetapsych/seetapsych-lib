# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from typing import Any

__all__ = [
    'sanitize_json',
    'dumps_sanitized',
]

_JSON_PRIMITIVE = (type(None), bool, int, float, str)


def _is_json_primitive(value: Any) -> bool:
    return isinstance(value, _JSON_PRIMITIVE)


def _format_type_name(value: Any) -> str:
    cls = type(value)
    module = cls.__module__
    name = cls.__qualname__
    if module and module != 'builtins':
        return f'{module}.{name}'
    return name


def _format_non_serializable(value: Any) -> str:
    base = _format_type_name(value)
    try:
        import numpy
        if isinstance(value, numpy.ndarray):
            base = f'{base}(shape={list(value.shape)}, dtype={value.dtype})'
    except Exception:
        pass
    return f'{base} (members only accessible via code)'


def sanitize_json(value: Any) -> Any:
    """Recursively replace non-JSON-serializable objects with type-descriptor strings.

    Primitives (None, bool, int, float, str) pass through unchanged.
    dict/list/tuple are traversed. numpy scalars are unwrapped via ``.item()``.
    numpy arrays and any other non-serializable objects become short type
    strings ending with ``(members only accessible via code)``.
    """
    if _is_json_primitive(value):
        return value
    if isinstance(value, dict):
        return {str(k): sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_json(v) for v in value]
    try:
        import numpy
        if isinstance(value, numpy.generic):
            return value.item()
        if isinstance(value, numpy.ndarray):
            return _format_non_serializable(value)
    except Exception:
        pass
    try:
        return sanitize_json(vars(value))
    except Exception:
        return _format_non_serializable(value)


def dumps_sanitized(value: Any, **kwargs: Any) -> str:
    """``json.dumps`` wrapper that auto-sanitizes *value* via :func:`sanitize_json`."""
    return json.dumps(sanitize_json(value), **kwargs)
