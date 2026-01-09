# -*- coding: utf-8 -*-

import sys
import importlib
import subprocess
import ensurepip
import urllib.parse
from importlib.metadata import version, PackageNotFoundError
from typing import Any

from packaging.requirements import Requirement

from fabopsy_lib.schema.module import *
from fabopsy_lib.utils.logger import logger


def unsatisfied_requirements(module: SchemaModule) -> list[str]:
    unsatisfied: list[str] = []
    for req_str in module.module.requirements:
        try:
            req = Requirement(req_str)
            pkg_name = req.name
            installed_ver = version(pkg_name)
            if not req.specifier.contains(installed_ver):
                unsatisfied.append(req_str)
        except PackageNotFoundError:
            unsatisfied.append(req_str)
        except Exception as e:
            msg = f'Unable to check satisfaction {req_str}: {e}'
            logger.error(msg)
            raise RuntimeError(msg) from e
    return unsatisfied


def install_requirements(module: SchemaModule, *, index_url: str = None, trusted_host: str | bool = None):
    unsatisfied = unsatisfied_requirements(module)
    if not unsatisfied:
        return

    try:
        import pip
    except ImportError:
        logger.info('Install pip via ensurepip')
        ensurepip.bootstrap()

    cmd = [sys.executable, '-m', 'pip', 'install'] + unsatisfied
    if index_url:
        cmd += ['--index-url', index_url]
    if trusted_host:
        if isinstance(trusted_host, bool):
            if index_url:
                parsed = urllib.parse.urlparse(index_url)
                trusted_host = parsed.hostname
                cmd += ['--trusted-host', trusted_host]
        else:
            cmd += ['--trusted-host', trusted_host]

    logger.info(f'Install requirements in subprocess:\n{" ".join(cmd)}')

    try:
        result = subprocess.run(
            cmd,
            stdout=None,    # print to current console
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )

        if result.returncode != 0:
            stderr = str(result.stderr)
            sys.stderr.write(stderr + "\n\n")
            sys.stderr.flush()

            msg = f'Failed to install requirements {unsatisfied}:\n{stderr}'
            logger.error(msg)
            raise RuntimeError(msg)
    except FileNotFoundError:
        msg = f'Python executable not found: {sys.executable}'
        logger.error(msg)
        raise RuntimeError(msg)
    except Exception as e:
        msg = f'Failed to execute pip install {unsatisfied}: {e}'
        logger.error(msg)
        raise RuntimeError(msg) from e


def call_entry(entry: SchemaEntry) -> Any:
    method = entry.method
    if entry.package:
        method = '.'.join([entry.package, method])
    if '.' not in method:
        raise RuntimeError('Global function calls are not supported')
    lib_name, func_name = method.rsplit('.', 1)

    try:
        lib = importlib.import_module(lib_name)
    except ImportError as e:
        logger.error(f'Can not import module {lib_name}: {e}')
        raise

    try:
        func = getattr(lib, func_name)
    except AttributeError as e:
        msg = f'Can not find {func_name} in module {lib_name}'
        logger.error(msg)
        raise AttributeError(msg) from e

    if not callable(func):
        msg = f'{method} is not callable'
        logger.error(msg)
        raise RuntimeError(msg)

    args = entry.args or []
    kwargs = entry.kwargs or {}

    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(f'Failed to call method {method} with args={args}, kwargs={kwargs}')
        raise


def hello(*args, **kwargs):
    print('helloworld', args, kwargs)


def test():
    call_entry(SchemaEntry(package='fabopsy_lib.runtime.actions', method='hello',
                           args=[1, '2', False], kwargs={'a': 1}))
    requirements = [
        'cowsay',
        'packaging>=25.0'
    ]
    module = SchemaModule(module={'requirements': requirements}, packages=[])

    print(unsatisfied_requirements(module))
    install_requirements(module)


if __name__ == '__main__':
    test()
