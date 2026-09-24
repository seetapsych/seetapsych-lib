# -*- coding: utf-8 -*-

import codecs
import copy
import ensurepip
import importlib
import io
import locale
import os
import shutil
import subprocess
import sys
import threading
import urllib.parse
from importlib.metadata import PackageNotFoundError, version
from typing import IO, Any, Callable, cast

from packaging.requirements import Requirement

from seetapsych_lib import api, schema
from seetapsych_lib.utils.logger import logger

__all__ = [
    "unsatisfied_requirements",
    "install_requirements",
    "install_module_requirements",
    "import_entry",
    "call_entry",
    "load_package",
]


def _get_locale_encoding() -> str:
    try:
        enc = getattr(locale, "getencoding", None)
        if enc is not None:
            return cast(Callable[[], str], enc)()
        return locale.getpreferredencoding(False)
    except AttributeError:
        return locale.getpreferredencoding(False)


def _decode_stderr(raw: bytes, encoding: str | None = None) -> str:
    """Decode captured diagnostics without discarding undecodable bytes.

    Args:
        raw: Complete captured output.
        encoding: Known source encoding. When absent, try UTF-8 and the locale
            strictly before replacing invalid UTF-8 sequences.

    Returns:
        Decoded diagnostic text.
    """
    if encoding is not None:
        return raw.decode(encoding, errors="replace")
    for enc in ("utf-8", _get_locale_encoding()):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _python_output_env() -> tuple[dict[str, str], str]:
    """Prepare a Python child's environment with a known pipe encoding.

    Returns:
        Environment copy and source encoding. Explicit PYTHONIOENCODING codecs
        are preserved; an unspecified codec defaults to UTF-8 in the child only.
    """
    env = os.environ.copy()
    encoding, separator, errors = env.get("PYTHONIOENCODING", "").partition(":")
    if not encoding:
        encoding = "utf-8"
        env["PYTHONIOENCODING"] = encoding + separator + errors
    return env, encoding


def safe_which(cmd: str | os.PathLike[Any], path: str | os.PathLike[Any] | None = None) -> str | None:
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

    Args:
        uv_path: Path to the uv executable.

    Returns:
        Version string if successful, otherwise None.
    """
    try:
        result = subprocess.run([uv_path, "--version"], capture_output=True, check=True)
        return result.stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return None


def get_pip_version() -> str | None:
    """
    Get the version of pip by calling 'python -m pip --version'.

    Returns:
        Version string if successful, otherwise None.
    """
    try:
        env, encoding = _python_output_env()
        result = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, env=env, check=True)
        return result.stdout.decode(encoding, errors="replace").strip()
    except Exception:
        return None


def _marker_applies(req: Requirement) -> bool:
    if req.marker is None:
        return True
    try:
        return req.marker.evaluate()
    except Exception as e:
        msg = f"Unable to evaluate marker for {req}: {e}"
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
            msg = f"Unable to check satisfaction {req_str}: {e}"
            logger.error(msg)
            raise RuntimeError(msg) from e

    for ref in module.refs:
        req_str = f"{ref.name}{ref.require}" if ref.require else ref.name
        req_git = f"{ref.name} @ git+{ref.repo}"
        if ref.revision:
            req_git += f"@{ref.revision}"
        if ref.subdir:
            req_git += f"#subdirectory={ref.subdir}"

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
            msg = f"Unable to check satisfaction {req_str}: {e}"
            logger.error(msg)
            raise RuntimeError(msg) from e

    return unsatisfied


def package_manager() -> tuple[str, list[str], dict[str, str]]:
    """Select uv or pip, bootstrapping pip when neither is available.

    Returns:
        Manager name, command prefix, and default environment variables.
        The name identifies the manager independently of its executable or flags.
    """
    # check uv
    uv_exe = find_uv()
    if uv_exe:
        uv_version = get_uv_version(uv_exe)
        logger.info(f"Using package manager: {uv_version}")
        return "uv", [uv_exe, "pip"], {"UV_TORCH_BACKEND": "auto"}

    # check pip
    from importlib.util import find_spec

    if find_spec("pip") is None:
        logger.info("Install pip via ensurepip")
        ensurepip.bootstrap()

    logger.info(f"Using package manager: {get_pip_version()}")
    return "pip", [sys.executable, "-m", "pip"], {}


def _filter_applicable_requirements(requirements: list[str]) -> list[str]:
    applicable: list[str] = []
    for req_str in requirements:
        try:
            req = Requirement(req_str)
            if _marker_applies(req):
                applicable.append(_strip_marker(req_str))
        except Exception as e:
            msg = f"Unable to parse requirement {req_str}: {e}"
            logger.error(msg)
            raise RuntimeError(msg) from e
    return applicable


def _tee_pipe(src: io.BufferedIOBase, dst: IO[str] | None, buf: io.BytesIO, encoding: str = "utf-8") -> None:
    """Forward available stderr chunks while retaining all bytes for diagnostics.

    Args:
        src: Buffered binary pipe, closed when reading finishes.
        dst: Live output stream. Missing or closed streams allow capture only.
        buf: Capture buffer, left open for the caller.
        encoding: Source encoding, independent of the destination's encoding.
    """
    dst_buf = getattr(dst, "buffer", None)
    dst_encoding = getattr(dst, "encoding", None)
    decoder = None
    encoder = None
    transcode = dst_encoding is not None and codecs.lookup(dst_encoding).name != codecs.lookup(encoding).name
    if dst is not None and (dst_buf is None or transcode):
        decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
        if dst_buf is not None and dst_encoding is not None:
            encoder = codecs.getincrementalencoder(dst_encoding)(errors="backslashreplace")
    with src:
        while True:
            # read1 does not wait to fill the chunk or require a newline.
            chunk = src.read1(65536)
            buf.write(chunk)
            if dst is not None:
                try:
                    if decoder is not None:
                        text = decoder.decode(chunk, final=not chunk)
                        if encoder is not None and dst_buf is not None:
                            dst_buf.write(encoder.encode(text, final=not chunk))
                        else:
                            dst.write(text)
                    elif dst_buf is not None:
                        dst_buf.write(chunk)
                    dst.flush()
                except (OSError, ValueError):
                    # Keep draining the pipe even if the output destination closes.
                    dst = None
            if not chunk:
                break


def install_requirements(
    requirements: list[str], *, index_url: str | None = None, trusted_host: str | bool | None = None
) -> None:
    """Install applicable requirements with live output and captured stderr.

    Args:
        requirements: PEP 508 requirement strings; inapplicable markers are skipped.
        index_url: Optional package index URL.
        trusted_host: Host to trust, or True to use the index URL's hostname.

    Raises:
        RuntimeError: Installation fails. Nonzero exits include captured stderr
            and the exit code; stdout is inherited and is not captured.
    """
    if not requirements:
        return

    applicable_reqs = _filter_applicable_requirements(requirements)
    if not applicable_reqs:
        logger.info(f"All requirements filtered out by environment markers, nothing to install: {requirements}")
        return

    pm_name, pm_cmd, pm_default_env = package_manager()
    cmd: list[str] = [*pm_cmd, "install"] + applicable_reqs
    if index_url:
        cmd += ["--index-url", index_url]
    if trusted_host:
        if isinstance(trusted_host, bool):
            if index_url:
                parsed = urllib.parse.urlparse(index_url)
                hn = parsed.hostname
                if hn:
                    cmd += ["--trusted-host", hn]
        else:
            cmd += ["--trusted-host", trusted_host]

    stderr_encoding = "utf-8"
    applied_env: list[str] = []
    if pm_name == "pip":
        # Align pip's output encoding with our decoder to avoid platform-dependent garbling.
        proc_env, stderr_encoding = _python_output_env()
        if proc_env.get("PYTHONIOENCODING") != os.environ.get("PYTHONIOENCODING"):
            applied_env.append(f"PYTHONIOENCODING={proc_env['PYTHONIOENCODING']}")
    else:
        proc_env = os.environ.copy()
    for key, value in pm_default_env.items():
        existing = proc_env.get(key, "")
        if not existing:
            proc_env[key] = value
            applied_env.append(f"{key}={value}")

    for item in applied_env:
        logger.info(f"Set environment variable for install: {item}")

    env_prefix = (" ".join(applied_env) + " ") if applied_env else ""
    logger.info(f"Install requirements in subprocess:\n{env_prefix}{' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=None,
            stderr=subprocess.PIPE,
            env=proc_env,
        )

        stderr_buf = io.BytesIO()
        tee_thread = threading.Thread(
            target=_tee_pipe, args=(proc.stderr, sys.stderr, stderr_buf, stderr_encoding), daemon=True
        )
        tee_thread.start()

        returncode = proc.wait()
        tee_thread.join()

    except FileNotFoundError as e:
        msg = f"Python executable not found: {sys.executable}"
        logger.error(msg)
        raise RuntimeError(msg) from e
    except Exception as e:
        msg = f"Failed to execute {pm_name} install {' '.join(requirements)}: {e}"
        logger.error(msg)
        raise RuntimeError(msg) from e

    if returncode != 0:
        stderr = _decode_stderr(stderr_buf.getvalue(), stderr_encoding)
        msg = f"Failed to install requirements {' '.join(requirements)} (exit code {returncode}):\n{stderr}"
        logger.error(msg)
        raise RuntimeError(msg)


def install_module_requirements(
    module: schema.ModuleSpec, *, index_url: str | None = None, trusted_host: str | bool | None = None
):
    unsatisfied = unsatisfied_requirements(module)
    install_requirements(unsatisfied)


def _resolve_entry_callable(
    entry: schema.Entry,
) -> tuple[Callable[..., Any] | None, str | None]:
    """
    Resolve an entry spec to its callable target.

    Returns:
        (callable, None): Import and lookup succeeded.
        (None, str): Import failed; str is the missing package name if known.
        (None, None): Method format invalid, attribute missing, or target not callable.
    """
    method = entry.method
    if entry.package:
        method = ".".join([entry.package, method])
    if "." not in method:
        return None, None
    lib_name, func_name = method.rsplit(".", 1)

    try:
        lib = importlib.import_module(lib_name)
    except ImportError as e:
        return None, e.name

    try:
        func = getattr(lib, func_name)
    except AttributeError:
        return None, None

    if not callable(func):
        return None, None

    return func, None


def import_entry(entry: schema.Entry | None) -> tuple[Callable | None, str | None]:
    """Import the callable referenced by a config entry.

    Args:
        entry: Module/path entry describing the callable. ``None`` is
            accepted and passed through as ``(None, None)``.

    Returns:
        A 2-tuple ``(callable, failed_package)``. On success the callable is
        returned with ``failed_package=None``. On failure the callable is
        ``None`` and ``failed_package`` contains the first Python module
        name whose import failed (if import failure was the cause).
    """
    if entry is None:
        return entry, None

    return _resolve_entry_callable(entry)


def call_entry(entry: schema.Entry, optional_kwargs: dict[str, Any] | None = None) -> Any:
    method = entry.method
    if entry.package:
        method = ".".join([entry.package, method])

    func, pname = _resolve_entry_callable(entry)
    if func is None:
        if "." not in method:
            raise RuntimeError("Global function calls are not supported")
        if pname is not None:
            e = ImportError(f"Can not import module for {method}")
            e.name = pname
            logger.error(f"Can not import module for {method}: {pname}")
            raise e
        lib_name, _ = method.rsplit(".", 1)
        msg = f"Can not find or call {method} in module {lib_name}"
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
    except Exception:
        logger.error(f"Failed to call method {method} with args={args}, kwargs={kwargs}")
        raise


def load_package(package: schema.Package) -> api.Package:
    result: api.Package = call_entry(package.entry)
    return result


def hello(*args: Any, **kwargs: Any):
    print("helloworld", args, kwargs)


def test():
    call_entry(
        schema.Entry(
            package="seetapsych_lib.runtime.actions",
            method="hello",
            args=[1, "2", False],
            kwargs={"a": 1},
        )
    )
    requirements = ["cowsay", "packaging>=25.0"]
    module_spec = schema.ModuleSpec(
        uid="test-action-module",
        name="Test Action Module",
        version="",
        description="",
        keywords=[],
        requirements=requirements,
        refs=[],
    )

    print(unsatisfied_requirements(module_spec))
    install_module_requirements(module_spec)


if __name__ == "__main__":
    test()
