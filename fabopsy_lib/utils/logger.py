# -*- coding: utf-8 -*-

import logging

__all__ = [
    'logger',
]

logger = logging.getLogger('FabopsyLib')
level = logging.INFO

logger.setLevel(level)

formatter = logging.Formatter(
    '[%(asctime)s][%(levelname)s][%(name)s]: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.NOTSET)
console_handler.setFormatter(formatter)

logger.addHandler(console_handler)
