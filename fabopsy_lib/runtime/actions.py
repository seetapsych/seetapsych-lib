# -*- coding: utf-8 -*-

import os
import sys
import copy
import shutil
import importlib
import subprocess
import ensurepip
import urllib.parse
from importlib.metadata import version, PackageNotFoundError
from typing import Any, Callable, Union

from packaging.requirements import Requirement

from fabopsy_lib import api
from fabopsy_lib import schema
from fabopsy_lib.utils.logger import logger


__all__ = [
    'unsatisfied_requirements',
    'install_requirements',
    'import_entry',
    'call_entry',
    'load_package',
]


def safe_which(
        cmd: Union[str, os.PathLike],
        path: Union[str, os.PathLike] = None
) -> str | None:
    """
    Safely wrap shutil.which to support both str and PathLike inputs.

    This avoids issues on Windows with Python < 3.12 where PathLike
    arguments may fail or return None.
    """
    cmd_str = os.fspath(cmd)  # Convert PathLike -> str safely
    path_str = os.fspath(path) if path is not None else None
    return shutil.which(cmd_str, path=path_str)


def find_uv() -> str | None:
    """
    Locate the 'uv' executable in a cross-platform and robust way.

    Steps:
    1. Search in PATH using shutil.which
    2. Handle Windows-specific executable suffixes
    3. Fallback to common installation directories
    """
    # Step 1: standard lookup
    uv_path = safe_which("uv")
    if uv_path:
        return uv_path

    # Step 2: Windows-specific fallback for executable extensions
    if os.name == "nt":
        for name in ["uv.exe", "uv.cmd", "uv.bat"]:
            uv_path = safe_which(name)
            if uv_path:
                return uv_path

    # Step 3: common install locations (Linux/macOS)
    common_paths = [
        os.path.expanduser("~/.local/bin/uv"),
        os.path.expanduser("~/bin/uv"),
        "/usr/local/bin/uv",
        "/opt/homebrew/bin/uv",  # macOS (Apple Silicon)
    ]

    for path in common_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    return None


def get_uv_version(uv_path: str) -> str | None:
    """
    Get the version of uv by calling 'uv --version'.

    Returns:
        Version string if successful, otherwise None.
    """
    try:
        result = subprocess.run(
            [uv_path, "--version"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception:
        return None


def get_pip_version() -> str | None:
    """
    Get the version of pip by calling 'python -m pip --version'.

    Returns:
        Version string if successful, otherwise None.
    """
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', "--version"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception:
        return None


def unsatisfied_requirements(module: schema.ModuleSpec) -> list[str]:
    unsatisfied: list[str] = []
    for req_str in module.requirements:
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


def package_manager() -> list[str]:
    # check uv
    uv_exe = find_uv()
    if uv_exe:
        uv_version = get_uv_version(uv_exe)
        logger.info(f"Using package manager: {uv_version}")
        return [uv_exe, "pip"]

    # check pip
    try:
        import pip
    except ImportError:
        logger.info('Install pip via ensurepip')
        ensurepip.bootstrap()

    logger.info(f"Using package manager: {get_pip_version()}")
    return [sys.executable, '-m', 'pip']


def install_requirements(module: schema.ModuleSpec, *, index_url: str = None, trusted_host: str | bool = None):
    unsatisfied = unsatisfied_requirements(module)
    if not unsatisfied:
        return

    cmd = [*package_manager(), 'install'] + unsatisfied
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


def import_entry(entry: schema.Entry | None) -> Callable | None:
    if entry is None:
        return entry

    method = entry.method
    if entry.package:
        method = '.'.join([entry.package, method])
    if '.' not in method:
        return None
    lib_name, func_name = method.rsplit('.', 1)

    try:
        lib = importlib.import_module(lib_name)
    except ImportError as e:
        return None

    try:
        func = getattr(lib, func_name)
    except AttributeError as e:
        return None

    if not callable(func):
        return None

    return func


def call_entry(entry: schema.Entry, optional_kwargs: dict[str, Any] = None) -> Any:
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
    kwargs = copy.copy(entry.kwargs) if entry.kwargs else {}

    if optional_kwargs:
        for key in optional_kwargs.keys():
            if key in kwargs:
                kwargs[key] = optional_kwargs[key]

    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(f'Failed to call method {method} with args={args}, kwargs={kwargs}')
        raise


def load_package(package: schema.Package) -> api.Package:
    return call_entry(package.entry)


def hello(*args, **kwargs):
    print('helloworld', args, kwargs)


def test():
    call_entry(schema.Entry(
        package='fabopsy_lib.runtime.actions', method='hello',
        args=[1, '2', False], kwargs={'a': 1}))
    requirements = [
        'cowsay',
        'packaging>=25.0'
    ]
    module = schema.Module(module={'requirements': requirements}, packages=[])

    print(unsatisfied_requirements(module))
    install_requirements(module)


if __name__ == '__main__':
    test()
