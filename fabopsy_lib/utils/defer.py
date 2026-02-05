# -*- coding: utf-8 -*-

from typing import Callable, Any


__all__ = [
    'Defer',
    'defer',
]


class Defer(object):
    def __init__(self, f: Callable[[], Any]):
        self.__callback = f

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__callback()


def defer(f: Callable[[], Any]) -> Defer:
    return Defer(f)


def test():
    pass


if __name__ == '__main__':
    test()
