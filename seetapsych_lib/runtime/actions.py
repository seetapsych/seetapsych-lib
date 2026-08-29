# -*- coding: utf-8 -*-

import os
import sys
import copy
import io
import locale
import shutil
import importlib
import subprocess
import threading
import ensurepip
import urllib.parse
from importlib.metadata import version, PackageNotFoundError
from typing import Any, Callable, Union

from packaging.requirements import Requirement

from seetapsych_lib import api
from seetapsych_lib import schema
from seetapsych_lib.utils.logger import logger


__all__ = [
    'unsatisfied_requirements',
    'install_requirements',
    'install_module_requirements',
    'import_entry',
    'call_entry',
    'load_package',
]


def _get_locale_encoding() -> str:
    try:
        return locale.getencoding()
    except AttributeError:
        return locale.getpreferredencoding(False)


def _decode_stderr(raw: bytes) -> str:
    if raw is None:
        return ""
    for enc in (_get_locale_encoding(), "utf-8"):
        try:
            return raw.decode(encoding=enc, errors="replace")
        except Exception:
            continue
    return ""


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


def _marker_applies(req: Requirement) -> bool:
    if req.marker is None:
        return True
    try:
        return req.marker.evaluate()
    except Exception as e:
        msg = f'Unable to evaluate marker for {req}: {e}'
        logger.error(msg)
        raise RuntimeError(msg) from e


def _strip_marker(req_str: str) -> str:
    try:
        req = Requirement(req_str)
        req.marker = None
        return str(req)
    except Exception:
        return req_str


def unsatisfied_requirements(module: schema.ModuleSpec) -> list[str]:
    unsatisfied: list[str] = []

    for req_str in module.requirements:
        try:
            req = Requirement(req_str)
            if not _marker_applies(req):
                continue
            pkg_name = req.name
            installed_ver = version(pkg_name)
            if not req.specifier.contains(installed_ver):
                unsatisfied.append(_strip_marker(req_str))
        except PackageNotFoundError:
            unsatisfied.append(_strip_marker(req_str))
        except Exception as e:
            msg = f'Unable to check satisfaction {req_str}: {e}'
            logger.error(msg)
            raise RuntimeError(msg) from e

    for ref in module.refs:
        req_str = f'{ref.name}{ref.require}' if ref.require else ref.name
        req_git = f'{ref.name} @ git+{ref.repo}'
        if ref.revision:
            req_git += f'@{ref.revision}'
        if ref.subdir:
            req_git += f'#subdirectory={ref.subdir}'

        try:
            req = Requirement(req_str)
            if not _marker_applies(req):
                continue
            pkg_name = req.name
            installed_ver = version(pkg_name)
            if not req.specifier.contains(installed_ver):
                unsatisfied.append(req_git)
        except PackageNotFoundError:
            unsatisfied.append(req_git)
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


def _filter_applicable_requirements(requirements: list[str]) -> list[str]:
    applicable: list[str] = []
    for req_str in requirements:
        try:
            req = Requirement(req_str)
            if _marker_applies(req):
                applicable.append(_strip_marker(req_str))
        except Exception as e:
            msg = f'Unable to parse requirement {req_str}: {e}'
            logger.error(msg)
            raise RuntimeError(msg) from e
    return applicable


def _tee_pipe(src: io.RawIOBase, dst: io.TextIOBase, buf: io.BytesIO):
    dst_buf = dst.buffer
    dst_flush = dst.flush
    while True:
        chunk = src.read(65536)
        if not chunk:
            break
        dst_buf.write(chunk)
        buf.write(chunk)
        dst_flush()
    src.close()


def install_requirements(requirements: list[str], *, index_url: str = None, trusted_host: str | bool = None):
    if not requirements:
        return

    applicable_reqs = _filter_applicable_requirements(requirements)
    if not applicable_reqs:
        logger.info(f'All requirements filtered out by environment markers, nothing to install: {requirements}')
        return

    cmd = [*package_manager(), 'install'] + applicable_reqs
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
        proc = subprocess.Popen(
            cmd,
            stdout=None,
            stderr=subprocess.PIPE,
        )

        stderr_buf = io.BytesIO()
        tee_thread = threading.Thread(
            target=_tee_pipe,
            args=(proc.stderr, sys.stderr, stderr_buf),
            daemon=True
        )
        tee_thread.start()

        returncode = proc.wait()
        tee_thread.join()

        if returncode != 0:
            stderr_bytes = stderr_buf.getvalue()
            stderr = _decode_stderr(stderr_bytes)
            msg = f'Failed to install requirements {" ".join(requirements)} (exit code {returncode}):\n{stderr}'
            logger.error(msg)
            raise RuntimeError(msg)
    except FileNotFoundError:
        msg = f'Python executable not found: {sys.executable}'
        logger.error(msg)
        raise RuntimeError(msg)
    except Exception as e:
        msg = f'Failed to execute uv pip or pip install {" ".join(requirements)}: {e}'
        logger.error(msg)
        raise RuntimeError(msg) from e


def install_module_requirements(module: schema.ModuleSpec, *, index_url: str = None, trusted_host: str | bool = None):
    unsatisfied = unsatisfied_requirements(module)
    install_requirements(unsatisfied)


def import_entry(entry: schema.Entry | None) -> tuple[Callable | None,  str | None]:
    """
    :param entry:
    :return: entry function and failed import package name if that's the reason
    """
    if entry is None:
        return entry, None

    method = entry.method
    if entry.package:
        method = '.'.join([entry.package, method])
    if '.' not in method:
        return None, None
    lib_name, func_name = method.rsplit('.', 1)

    try:
        lib = importlib.import_module(lib_name)
    except ImportError as e:
        return None, e.name

    try:
        func = getattr(lib, func_name)
    except AttributeError as e:
        return None, None

    if not callable(func):
        return None, None

    return func, None


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
        package='seetapsych_lib.runtime.actions', method='hello',
        args=[1, '2', False], kwargs={'a': 1}))
    requirements = [
        'cowsay',
        'packaging>=25.0'
    ]
    module = schema.Module(module={'requirements': requirements}, packages=[])

    print(unsatisfied_requirements(module))
    install_module_requirements(module)


if __name__ == '__main__':
    test()
