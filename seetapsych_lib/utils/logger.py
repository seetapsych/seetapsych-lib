# -*- coding: utf-8 -*-

import os
import logging

__all__ = [
    'logger',
    'set_level',
]


def default_log_level() -> int:
    env_log_level = os.environ.get('SEETAPSYCH_LOG_LEVEL', '')
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


logger = logging.getLogger('SeetaPsychLib')
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


def set_level(lv: str | int | None):
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

    match lv:
        case str(x):
            level_value: int | None = map_log_level.get(x.strip().upper(), None)
            if level_value is not None:
                logger.setLevel(level_value)
        case int(x):
            logger.setLevel(x)
