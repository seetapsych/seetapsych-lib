# -*- coding: utf-8 -*-

import os
import logging

__all__ = [
    'logger',
]


def default_log_level() -> int:
    env_log_level = os.environ.get('FABOPSY_LOG_LEVEL', '')
    if not env_log_level:
        return logging.INFO

    map_log_level = {
        'CRITICAL': logging.CRITICAL,
        'FATAL': logging.FATAL,
        'ERROR': logging.ERROR,
        'WARNING': logging.WARNING,
        'WARN': logging.WARN,
        'INFO': logging.INFO,
        'DEBUG': logging.DEBUG,
        'NOTSET': logging.NOTSET,
    }

    log_level: int | None = map_log_level.get(env_log_level.strip().upper(), None)
    if log_level is not None:
        return log_level

    try:
        return int(env_log_level)
    except ValueError:
        pass

    return logging.INFO


logger = logging.getLogger('FabopsyLib')
level = default_log_level()

logger.setLevel(level)

formatter = logging.Formatter(
    '[%(asctime)s][%(levelname)s][%(name)s]: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.NOTSET)
console_handler.setFormatter(formatter)

logger.addHandler(console_handler)
