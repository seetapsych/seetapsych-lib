# -*- coding: utf-8 -*-

import glob
import os.path
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import IO, Any

from seetapsych_lib import schema
from seetapsych_lib.utils.dirs import appdirs
from seetapsych_lib.utils.loader import load, loads
from seetapsych_lib.utils.logger import logger

__all__ = [
    "LoadedModule",
    "default_config_dir",
    "load_builtin_modules",
    "load_default_modules",
    "load_example_modules",
    "load_dir_modules",
    "load_local_module",
    "load_url_module",
]


def default_config_dir() -> str:
    """Return the user-specific config directory where module YAMLs are stored.

    Reads ``SEETAPSYCH_CONFIG_DIR`` env var when set; otherwise falls back to
    the platform ``user_data_dir`` provided by ``appdirs``.
    """
    config_dir = os.environ.get("SEETAPSYCH_CONFIG_DIR", "") or appdirs.user_data_dir
    return os.path.join(config_dir, "configs")


@dataclass
class LoadedModule:
    """Container for a successfully parsed module and its metadata.

    Attributes:
        source: The origin config path (file path, URL, or ``<anonymous>``).
        module: The parsed :class:`seetapsych_lib.schema.module.Module` object.
        origin: Optional load-origin tag for debugging / introspection.
            Common values: ``builtin``, ``default``, ``example``,
            ``file``, ``url``, ``memory``.  Not populated at
            construction when the caller does not know the origin yet.
    """

    source: str
    module: schema.Module
    origin: str | None = field(default=None)


builtin_module_root = os.path.join(os.path.dirname(__file__), "..", "modules")


builtin_example_root = os.path.join(os.path.dirname(__file__), "..", "example")


def _is_user_error(exc: BaseException) -> bool:
    """Classify an exception as an expected user-space (non-programming) error.

    User-space errors are conditions that can legitimately happen in a
    deployed application because of misconfiguration, missing files,
    malformed content, network issues, or permission problems.  They should
    be surfaced via log + return-value rather than raising.

    Returns:
        True when ``exc`` is considered a user-space issue.
    """
    user_exc_types = (
        # File / filesystem
        FileNotFoundError,
        PermissionError,
        IsADirectoryError,
        NotADirectoryError,
        OSError,
        # IO / encoding
        UnicodeDecodeError,
        # Parsing / schema
        ValueError,
        TypeError,
        RuntimeError,
        # Network / URL
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
    )
    # Pydantic validation errors subclass ValueError, so they are already covered.
    return isinstance(exc, user_exc_types)


def load_builtin_modules() -> list[LoadedModule]:
    """Load modules shipped inside the library package (``modules/`` dir).

    Returns:
        List of successfully loaded modules tagged with ``origin="builtin"``.
        Parse / IO errors are logged as warnings and skipped; a failure on
        one file never prevents the rest from being loaded.
    """
    return load_dir_modules(builtin_module_root, origin="builtin")


def load_default_modules() -> list[LoadedModule]:
    """Load modules from the user-wide default config directory.

    Returns:
        List of successfully loaded modules tagged with ``origin="default"``.
    """
    return load_dir_modules(default_config_dir(), origin="default")


def load_example_modules() -> list[LoadedModule]:
    """Load modules shipped inside the library ``example/`` directory.

    Returns:
        List of successfully loaded modules tagged with ``origin="example"``.
    """
    return load_dir_modules(builtin_example_root, origin="example")


def load_dir_modules(
    root: str,
    *,
    origin: str | None = "file",
) -> list[LoadedModule]:
    """Recursively load every supported module file under ``root``.

    Supported extensions: ``json``, ``toml``, ``yaml``, ``yml``.

    All user-space failures (missing file, permission denied, bad content,
    invalid schema, ...) are logged as warnings and **never** raised.  A
    failure in one file never aborts the whole scan.

    Note:
        This function does **not** emit summary ``INFO``/``WARNING`` lines
        for the overall operation; callers (typically :class:`Factory`) are
        responsible for aggregate logging since they know the operational
        context (builtin / default / custom dir / ...).

    Args:
        root: Directory to scan recursively.
        origin: Value written into :attr:`LoadedModule.origin` for each
            loaded module.  Pass ``None`` to leave the field untouched.

    Returns:
        Modules successfully loaded and parsed.  Empty list when ``root``
        does not exist, is not readable, or contains no valid module files.
    """
    extensions = ["json", "toml", "yaml", "yml"]

    files: list[str] = []
    try:
        for ext in extensions:
            pattern = os.path.join("**", f"*.{ext}")
            ext_files = glob.glob(pattern, root_dir=root, recursive=True)
            files.extend([os.path.join(root, name) for name in ext_files])
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.warning(f"Can not scan module directory: {root}.\n[Exception]: {e}")
        return []

    files = sorted(files)

    modules: list[LoadedModule] = []
    for module_file in files:
        try:
            json_object = load(module_file)
        except Exception as e:
            if _is_user_error(e):
                logger.warning(f"Can not load module file: {module_file}.\n[Exception]: {e}")
                continue
            raise
        try:
            module = schema.module.parse(json_object)
        except Exception as e:
            if _is_user_error(e):
                logger.warning(f"Can not parse module config: {module_file}.\n[Exception]: {e}")
                continue
            raise
        loaded = LoadedModule(source=module_file, module=module)
        if origin is not None:
            loaded.origin = origin
        modules.append(loaded)

    return modules


def load_local_module(
    f: str | bytes | IO[str] | IO[bytes],
    extension: str | None = None,
    *,
    origin: str | None = None,
) -> LoadedModule | None:
    """Load a single module from a file path, raw bytes, or a readable stream.

    User-space errors (unreadable file, unknown extension, malformed JSON /
    TOML / YAML, schema violation, encoding error, ...) are logged as
    warnings and cause the function to return ``None`` instead of raising.

    Only truly unexpected programming errors propagate to the caller.

    Args:
        f: File path (str), raw content (bytes), or a readable text/binary
            stream.
        extension: Explicit file extension hint (``json``, ``toml``,
            ``yaml``, ``yml``).  When omitted it is inferred from the file
            name, or when impossible the loader tries each format in turn.
        origin: Optional value to set on :attr:`LoadedModule.origin`.  When
            ``None`` the function auto-tags ``memory`` for bytes/stream
            inputs and ``file`` for file-path inputs.

    Returns:
        A :class:`LoadedModule` on success, or ``None`` on any user-space
        failure.
    """
    try:
        json_object = load(f, extension)
    except Exception as e:
        if _is_user_error(e):
            f_display: Any
            if isinstance(f, bytes):
                f_display = f"<bytes {len(f)}B>"
            elif isinstance(f, str):
                f_display = f
            else:
                f_display = repr(f)
            logger.warning(f"Can not load local module: {f_display}.\n[Exception]: {e}")
            return None
        raise

    try:
        module = schema.module.parse(json_object)
    except Exception as e:
        if _is_user_error(e):
            if isinstance(f, bytes):
                f_display_parse: Any = f.decode(encoding="utf-8", errors="replace")
            else:
                f_display_parse = f
            logger.warning(f"Can not parse module config: {f_display_parse}.\n[Exception]: {e}")
            return None
        raise

    if isinstance(f, bytes):
        filename_src = f"<bytes {len(f)}B>"
        resolved_origin = origin if origin is not None else "memory"
    elif isinstance(f, str):
        filename_src = f
        resolved_origin = origin if origin is not None else "file"
    else:
        filename_src = "<anonymous>"
        resolved_origin = origin if origin is not None else "memory"

    loaded = LoadedModule(source=filename_src, module=module)
    loaded.origin = resolved_origin
    return loaded


def load_url_module(url: str, *, origin: str | None = "url") -> LoadedModule | None:
    """Fetch and parse a single module from a URL.

    User-space network / HTTP errors (connection failure, timeout, 4xx/5xx,
    SSL problems, ...) plus content / schema failures are logged as warnings
    and result in ``None`` rather than raising.  Only unexpected programming
    errors propagate.

    Args:
        url: HTTP(S), FTP, or ``file://`` URL pointing to a supported module
            document (JSON / TOML / YAML).
        origin: Value written into :attr:`LoadedModule.origin`.  Pass
            ``None`` to leave the field empty.

    Returns:
        :class:`LoadedModule` on success, ``None`` on any user-space
        failure.
    """
    parsed = urllib.parse.urlparse(url)
    filename: str | None = os.path.basename(parsed.path)

    if not filename or filename == "." or filename == "..":
        filename = None
        query = urllib.parse.parse_qs(parsed.query)
        if query:
            for name in ["filename", "file"]:
                if name in query:
                    filename = query[name][0]
                    break

    extension = os.path.splitext(filename)[-1] if filename else None

    try:
        with urllib.request.urlopen(url) as resp:
            response: IO[bytes] = resp
            content = response.read()
    except Exception as e:
        if _is_user_error(e):
            logger.warning(f"Can not fetch module URL: {url}.\n[Exception]: {e}")
            return None
        raise

    try:
        json_object = loads(content, extension)
    except Exception as e:
        if _is_user_error(e):
            logger.warning(f"Can not decode content of module URL: {url}.\n[Exception]: {e}")
            return None
        raise

    try:
        module = schema.module.parse(json_object)
    except Exception as e:
        if _is_user_error(e):
            logger.warning(f"Can not parse module config: {url}.\n[Exception]: {e}")
            return None
        raise

    loaded = LoadedModule(source=url, module=module)
    if origin is not None:
        loaded.origin = origin
    return loaded


def test() -> None:
    modules = load_builtin_modules()
    for m in modules:
        basename = os.path.basename(m.source)
        print(f"Loaded builtin: {basename} -> {', '.join([p.name for p in m.module.packages])}")

    if not modules:
        return

    local_module_path = modules[0].source
    for m_local in [load_local_module(local_module_path)]:
        if m_local is None:
            continue
        basename = os.path.basename(m_local.source)
        print(f"Loaded local: {basename} -> {', '.join([p.name for p in m_local.module.packages])}")

    local_module_url = f"file:///{local_module_path}"
    for m_url in [load_url_module(local_module_url)]:
        if m_url is None:
            continue
        basename = os.path.basename(urllib.parse.urlparse(m_url.source).path)
        print(f"Loaded url: {basename} -> {', '.join([p.name for p in m_url.module.packages])}")


if __name__ == "__main__":
    test()
