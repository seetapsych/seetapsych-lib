# -*- coding: utf-8 -*-

from typing import Iterable, TypeVar

T = TypeVar('T')

def unique_list(a: Iterable[T]) -> list[T]:
    return list(dict.fromkeys(a))
