# -*- coding: utf-8 -*-

import os.path
from typing import IO, Iterable

from seetapsych_lib import schema
from seetapsych_lib.runtime.module import (
    LoadedModule,
    load_builtin_modules,
    load_default_modules,
    load_dir_modules,
    load_example_modules,
    load_local_module,
    load_url_module,
)
from seetapsych_lib.utils.logger import logger
from seetapsych_lib.utils.pencilbox import unique_list

__all__ = [
    "Factory",
]


class Factory(object):
    """Module registry and query facade for the SeetaPsych runtime.

    A :class:`Factory` loads module descriptors from builtin, user-default,
    example, custom directory, file, URL, or in-memory sources and exposes
    unified lookup helpers for modules, packages, models, and attributes.

    User-space errors encountered while loading (missing files, bad
    schemas, network timeouts, permission problems, ...) never abort a
    batch or raise to the caller; combine the method return value with the
    ``SeetaPsychLib`` logger output for diagnosis.
    """

    def __init__(
        self,
        *,
        disable_builtin: bool = False,
        disable_default: bool = False,
        enable_example: bool = False,
    ):
        """Initialize the Factory and optionally auto-load module sources.

        Args:
            disable_builtin: When True, skip loading the library-shipped
                builtin modules (``seetapsych_lib/modules/``).  Use this to
                reduce startup overhead or to pin a custom module set.
            disable_default: When True, skip loading modules from the
                user-wide default config directory (see
                :func:`seetapsych_lib.runtime.module.default_config_dir`).
                Use this for fully managed deployments.
            enable_example: When True, also load the library-shipped
                example modules (``seetapsych_lib/example/``).  These are
                not loaded by default to avoid accidental exposure of
                experimental / demo packages in production.
        """
        self.__modules: list[LoadedModule] = []

        self.__module_uid_map: dict[schema.Uid, schema.Module] = {}
        self.__package_uid_map: dict[schema.Uid, schema.Package] = {}
        self.__model_uid_map: dict[schema.Uid, schema.Model] = {}
        self.__package_uid_map_module: dict[schema.Uid, schema.Module] = {}
        self.__model_uid_map_package: dict[schema.Uid, schema.Package] = {}
        self.__parameter_map: dict[tuple[schema.Uid, str], schema.Parameter] = {}

        self.__attribute_providers: dict[str, list[schema.Package]] = {}

        if not disable_builtin:
            self.load_builtin_modules()

        if not disable_default:
            self.load_default_modules()

        if enable_example:
            self.load_example_modules()

    def append(self, module: LoadedModule) -> None:
        """Append a single parsed module to the registry.

        Even if there are duplicate UIDs, in most cases, factory operations
        will still work without issues.

        TODO: We still need to handle this situation or provide a prompt
        to the user, in the future.

        Args:
            module: A successfully loaded :class:`LoadedModule` to register.
        """
        self.__modules.append(module)

        self.__module_uid_map[module.module.module.uid] = module.module
        for package in module.module.packages:
            self.__package_uid_map[package.uid] = package
            self.__package_uid_map_module[package.uid] = module.module
            for model in package.models:
                self.__model_uid_map[model.uid] = model
                self.__model_uid_map_package[model.uid] = package
            for attr in set(package.provides) - set(package.requires):
                providers = self.__attribute_providers.get(attr, None)
                if providers is not None:
                    providers.append(package)
                else:
                    self.__attribute_providers[attr] = [package]
            for param in package.parameters:
                self.__parameter_map[(package.uid, param.name)] = param

    def extend(self, modules: Iterable[LoadedModule]) -> None:
        """Append every module from an iterable to the registry.

        Args:
            modules: Iterable of :class:`LoadedModule` to register.
        """
        for module in modules:
            self.append(module)

    def load_builtin_modules(self) -> int:
        """Load modules shipped inside the library (``modules/`` directory).

        Returns:
            Number of modules successfully appended (0 or more).
        """
        modules = load_builtin_modules()
        count = len(modules)
        self.extend(modules)
        return count

    def load_default_modules(self) -> int:
        """Load modules from the user-wide default config directory.

        Returns:
            Number of modules successfully appended (0 or more).
        """
        modules = load_default_modules()
        count = len(modules)
        if count == 0:
            logger.warning(
                "No default modules loaded. "
                'Tip: You can use "seetapsych-manager download" '
                "to install the default built-in module configs."
            )
        else:
            logger.info(f"Loaded {count} default module(s).")
        self.extend(modules)
        return count

    def load_example_modules(self) -> int:
        """Load modules from the library ``example/`` directory.

        Returns:
            Number of modules successfully appended (0 or more).
        """
        modules = load_example_modules()
        count = len(modules)
        self.extend(modules)
        return count

    def load_dir_modules(self, root: str) -> int:
        """Recursively load every supported module file under ``root``.

        User-space errors (unreadable dir, bad files, invalid schemas) are
        logged as warnings per-file and never raised; a failure in one file
        never aborts the scan.

        Args:
            root: Directory to scan recursively.

        Returns:
            Number of modules successfully appended.
        """
        modules = load_dir_modules(root)
        count = len(modules)
        if count == 0:
            logger.warning(f"No module loaded from directory: {root}.")
        else:
            logger.info(f"Loaded {count} module(s) from directory: {root}.")
        self.extend(modules)
        return count

    def load_file_modules(self, filepath: str | Iterable[str], /, *filepaths: str) -> int:
        """Load one or more module files by file-system path.

        Each path is resolved independently through
        :func:`seetapsych_lib.runtime.module.load_local_module`.  Any
        user-space failure on a single file is logged once and skipped;
        subsequent paths are still processed.

        Args:
            filepath: Single file path (``str``) or an iterable of paths.
            *filepaths: Additional paths, accepted variadically for
                convenience.

        Returns:
            Count of files successfully loaded and appended.
        """
        values = [filepath] if isinstance(filepath, str) else list(filepath)
        values = [*values, *filepaths]
        total = len(values)

        success = 0
        for p in values:
            ext = os.path.splitext(p)[1][1:] or None
            module = load_local_module(p, ext)
            if module is not None:
                self.append(module)
                success += 1

        if total:
            if success == 0:
                logger.warning(f"No module loaded: {total} file path(s) provided but all failed.")
            else:
                logger.info(f"Loaded {success}/{total} module file(s).")

        return success

    def load_url_modules(self, url: str | Iterable[str], /, *urls: str) -> int:
        """Load one or more modules by URL.

        Each URL is fetched and parsed independently through
        :func:`seetapsych_lib.runtime.module.load_url_module`.  Network,
        parse, or schema failures on a single URL are logged once and
        skipped; remaining URLs continue loading.

        Args:
            url: Single URL string or iterable of URL strings.
            *urls: Additional URL strings, accepted variadically.

        Returns:
            Count of URLs successfully loaded and appended.
        """
        values = [url] if isinstance(url, str) else list(url)
        values = [*values, *urls]
        total = len(values)

        success = 0
        for u in values:
            module = load_url_module(u)
            if module is not None:
                self.append(module)
                success += 1

        if total:
            if success == 0:
                logger.warning(f"No module loaded: {total} URL(s) provided but all failed.")
            else:
                logger.info(f"Loaded {success}/{total} URL module(s).")

        return success

    def load_local_module(
        self,
        f: str | bytes | IO[str] | IO[bytes],
        extension: str | None = None,
    ) -> bool:
        """Load a single module from a file path, bytes, or readable stream.

        Wraps :func:`seetapsych_lib.runtime.module.load_local_module`; all
        user-space errors are logged once inside the lower layer and never
        raised here.

        Args:
            f: File path (``str``), raw module content (``bytes``), or a
                readable text / binary stream.
            extension: Optional file-extension hint (``json``, ``toml``,
                ``yaml``, ``yml``).  If omitted the loader infers it from
                the file name or auto-detects the content format.

        Returns:
            ``True`` when the module was parsed successfully and appended
            to the registry; ``False`` otherwise.
        """
        module = load_local_module(f, extension)
        if module is not None:
            self.append(module)
            return True
        return False

    @property
    def modules(self) -> list[LoadedModule]:
        """All loaded modules in registration order (read-only view)."""
        return self.__modules

    @property
    def packages(self) -> list[schema.Package]:
        """Flattened list of every :class:`Package` exposed by loaded modules."""
        return [p for m in self.__modules for p in m.module.packages]

    @property
    def attributes(self) -> list[str]:
        """Deduplicated list of every attribute key declared in ``provides``."""
        packages = self.packages
        return unique_list([attr for p in packages for attr in p.provides])

    def loaded_sources(self) -> dict[str, list[str]]:
        """Return loaded-module :attr:`LoadedModule.source` grouped by origin.

        Use this helper for debugging / introspection: inspect which
        modules have been loaded from each source category.

        Returns:
            Dictionary keyed by :attr:`LoadedModule.origin` (falling back
            to the key ``"unknown"`` when the origin tag is empty).  Each
            value is the list of ``source`` strings for that origin, in
            registration order.
        """
        result: dict[str, list[str]] = {}
        for m in self.__modules:
            key = m.origin if m.origin is not None else "unknown"
            bucket = result.get(key)
            if bucket is None:
                result[key] = [m.source]
            else:
                bucket.append(m.source)
        return result

    def query_module(self, uid: schema.Uid) -> schema.Module | None:
        """Look up a module schema by its UID.

        Args:
            uid: The target module UID.

        Returns:
            The matched :class:`Module`, or ``None`` if not registered.
        """
        return self.__module_uid_map.get(uid, None)

    def query_package(self, uid: schema.Uid) -> schema.Package | None:
        """Look up a package schema by its UID.

        Args:
            uid: The target package UID.

        Returns:
            The matched :class:`Package`, or ``None`` if not registered.
        """
        return self.__package_uid_map.get(uid, None)

    def query_model(self, uid: schema.Uid) -> schema.Model | None:
        """Look up a model schema by its UID.

        Args:
            uid: The target model UID.

        Returns:
            The matched :class:`Model`, or ``None`` if not registered.
        """
        return self.__model_uid_map.get(uid, None)

    def query_module_of_package(self, uid: schema.Uid) -> schema.Module | None:
        """Return the owning :class:`Module` for the given package UID.

        Args:
            uid: Target package UID.

        Returns:
            The module that declares the package, or ``None`` if unknown.
        """
        return self.__package_uid_map_module.get(uid, None)

    def query_package_of_model(self, uid: schema.Uid) -> schema.Package | None:
        """Return the owning :class:`Package` for the given model UID.

        Args:
            uid: Target model UID.

        Returns:
            The package that declares the model, or ``None`` if unknown.
        """
        return self.__model_uid_map_package.get(uid, None)

    def query_attribute_providers(self, attr: str) -> list[schema.Package]:
        """Return every package that provides ``attr``, sorted by priority.

        Args:
            attr: Attribute key (matches an entry in a package's
                ``provides`` list).

        Returns:
            Provider packages ordered by ``priority`` descending.  Empty
            list when no provider is registered for ``attr``.
        """
        providers = self.__attribute_providers.get(attr, [])
        return sorted(providers, key=lambda x: x.priority, reverse=True)

    def query_parameter(self, uid: schema.Uid, name: str) -> schema.Parameter | None:
        """Look up a declared parameter by package UID and parameter name.

        Args:
            uid: Owning package UID.
            name: Parameter ``name`` key.

        Returns:
            The matched :class:`Parameter`, or ``None`` if not declared.
        """
        return self.__parameter_map.get((uid, name), None)


def test() -> None:
    pass


if __name__ == "__main__":
    test()
