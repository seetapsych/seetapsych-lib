# -*- coding: utf-8 -*-

import argparse
import glob
import os
import shutil
import sys
import tempfile
import importlib
from pathlib import Path
from typing import cast, Protocol

from seetapsych_lib import schema
from seetapsych_lib.utils.logger import logger
from seetapsych_lib.runtime.module import default_config_dir
from seetapsych_lib.utils.loader import load as load_config
from seetapsych_lib.utils.loader import map_parser as _loader_map_parser
from seetapsych_lib.runtime.actions import install_requirements, install_module_requirements
from seetapsych_lib.runtime.model import build_model, default_cache_dir
from seetapsych_lib.utils.download_file import download_file


CONFIG_EXTENSIONS: list[str] = sorted(_loader_map_parser.keys())


def list_installed_configs() -> dict[schema.Uid, list[str]]:
    """Scan config directory, parse each file, return uid -> list[file_path] mapping.

    Files that fail to parse are logged as warnings and skipped.
    Reused by show/uninstall commands.
    """
    config_root = default_config_dir()
    result: dict[schema.Uid, list[str]] = {}

    if not os.path.isdir(config_root):
        return result

    files: list[str] = []
    for ext in CONFIG_EXTENSIONS:
        pattern = os.path.join('**', f'*.{ext}')
        ext_files = glob.glob(pattern, root_dir=config_root, recursive=True)
        files.extend([os.path.join(config_root, name) for name in ext_files])

    files = sorted(files)

    for f in files:
        try:
            json_object = load_config(f)
            module = schema.module.parse(json_object)
        except Exception as e:
            logger.warning(f'Skip unparsable installed config: {f}.\n[Exception]: {e}')
            continue
        uid = module.module.uid
        result.setdefault(uid, []).append(f)

    return result


class InstallArgs(Protocol):
    path: Path


class UninstallArgs(Protocol):
    path: Path


class ShowArgs(Protocol):
    detail: bool


class SetupArgs(Protocol):
    pass


class CacheArgs(Protocol):
    pass


class DownloadArgs(Protocol):
    force: bool


def _iter_default_modules() -> list[tuple[schema.Module, list[str]]]:
    """Scan config dir, parse modules, dedupe by uid, return (module, sources) entries.

    Shared by setup/cache. Parse failures are logged and skipped.
    """
    config_root = default_config_dir()
    entries: list[tuple[schema.Module, list[str]]] = []
    uid_seen: dict[schema.Uid, int] = {}

    if not os.path.isdir(config_root):
        return entries

    files: list[str] = []
    for ext in CONFIG_EXTENSIONS:
        pattern = os.path.join('**', f'*.{ext}')
        ext_files = glob.glob(pattern, root_dir=config_root, recursive=True)
        files.extend([os.path.join(config_root, name) for name in ext_files])
    files = sorted(files)

    for f in files:
        try:
            json_object = load_config(f)
            module = schema.module.parse(json_object)
        except Exception as e:
            logger.warning(f'Skip unparsable config: {f}.\n[Exception]: {e}')
            continue
        uid = module.module.uid
        if uid in uid_seen:
            entries[uid_seen[uid]][1].append(f)
        else:
            uid_seen[uid] = len(entries)
            entries.append((module, [f]))

    return entries


def install_config(args: argparse.Namespace) -> None:
    param = cast(InstallArgs, cast(object, args))
    logger.info(f"Install config {param.path.name}")

    if not param.path.exists():
        logger.error(f'Config not exists.')
        exit(1)

    json_object = load_config(str(param.path.resolve()))
    try:
        module = schema.module.parse(json_object)
    except Exception as e:
        logger.error(f'{e}')
        exit(2)

    uid = module.module.uid
    config_root = default_config_dir()
    uid_dir = os.path.join(config_root, uid)
    dest = os.path.join(uid_dir, param.path.name)

    logger.info(f'Default config directory: {config_root}')

    existing = list_installed_configs().get(uid, [])
    if existing:
        logger.info(f'Removing previous install of uid={uid} ({len(existing)} file(s))')
        for f in existing:
            try:
                os.remove(f)
            except OSError as e:
                logger.warning(f'Failed to remove old config {os.path.relpath(f, config_root)}: {e}')
        try:
            if os.path.isdir(uid_dir) and not os.listdir(uid_dir):
                os.rmdir(uid_dir)
        except OSError:
            pass

    os.makedirs(uid_dir, exist_ok=True)
    shutil.copy2(param.path, dest)

    logger.info(f'Installed config -> {os.path.relpath(dest, config_root)} (uid={uid})')


def uninstall_config(args: argparse.Namespace) -> None:
    param = cast(UninstallArgs, cast(object, args))
    logger.info(f"Uninstall config {param.path.name}")

    if not param.path.exists():
        logger.error(f'Config not exists.')
        exit(1)

    json_object = load_config(str(param.path.resolve()))
    try:
        module = schema.module.parse(json_object)
    except Exception as e:
        logger.error(f'{e}')
        exit(2)

    uid = module.module.uid
    config_root = default_config_dir()

    installed = list_installed_configs()
    files = installed.get(uid, [])

    if not files:
        logger.error(f'No installed config found with uid={uid}')
        exit(1)

    logger.info(f'Uninstalling uid={uid} ({len(files)} file(s))')
    for f in files:
        try:
            os.remove(f)
            logger.info(f'Removed {os.path.relpath(f, config_root)}')
        except OSError as e:
            logger.warning(f'Failed to remove {os.path.relpath(f, config_root)}: {e}')

    uid_dir = os.path.join(config_root, uid)
    try:
        if os.path.isdir(uid_dir) and not os.listdir(uid_dir):
            os.rmdir(uid_dir)
            logger.info(f'Removed empty uid directory: {os.path.relpath(uid_dir, config_root)}')
    except OSError as e:
        logger.warning(f'Failed to clean uid directory {os.path.relpath(uid_dir, config_root)}: {e}')


def _ensure_seetapsych_configs() -> object:
    try:
        return importlib.import_module('seetapsych_configs')
    except ImportError:
        pass

    logger.info('seetapsych_configs not found, attempting to install...')
    try:
        install_requirements(['seetapsych-configs'])
    except Exception as e:
        logger.error(f'Failed to install seetapsych_configs: {e}')
        sys.exit(1)

    try:
        return importlib.import_module('seetapsych_configs')
    except ImportError as e:
        logger.error(f'Failed to import seetapsych_configs after install: {e}')
        sys.exit(1)


def download_configs(args: argparse.Namespace) -> None:
    param = cast(DownloadArgs, cast(object, args))

    configs_pkg = _ensure_seetapsych_configs()
    from seetapsych_configs import ConfigInfo
    configs_list: list[ConfigInfo] = getattr(configs_pkg, 'configs', [])

    if not configs_list:
        logger.warning('No configs found in seetapsych_configs.')
        return

    total = len(configs_list)
    success = 0
    skipped = 0
    failures: list[tuple[str, str]] = []

    config_root = default_config_dir()
    logger.info(f'Download target directory: {config_root}')

    installed = list_installed_configs()

    with tempfile.TemporaryDirectory(prefix='seetapsych_dl_') as tmpdir:
        for config in configs_list:
            tag = f"{config['name']} v{config['version']}"
            logger.info(f'Processing config: {tag}')

            try:
                dl_path = download_file(
                    url=config['download_url'],
                    output=tmpdir,
                    overwrite=param.force,
                )
            except Exception as e:
                reason = f'{type(e).__name__}: {e}'
                logger.error(f'Failed to download {tag}: {reason}')
                failures.append((tag, reason))
                continue

            try:
                json_object = load_config(dl_path)
                module = schema.module.parse(json_object)
            except Exception as e:
                reason = f'{type(e).__name__}: {e}'
                logger.error(f'Downloaded config invalid for {tag}: {reason}')
                failures.append((tag, reason))
                continue

            uid = module.module.uid

            if uid in installed and not param.force:
                logger.info(f'Already installed with uid={uid}. Skip (use --force to overwrite).')
                skipped += 1
                continue

            uid_dir = os.path.join(config_root, uid)
            dest = os.path.join(uid_dir, os.path.basename(dl_path))

            existing_same = installed.get(uid, [])
            if existing_same:
                logger.info(f'Removing previous install of uid={uid} ({len(existing_same)} file(s))')
                for f in existing_same:
                    try:
                        os.remove(f)
                    except OSError as e:
                        logger.warning(f'Failed to remove old config {os.path.relpath(f, config_root)}: {e}')
                try:
                    if os.path.isdir(uid_dir) and not os.listdir(uid_dir):
                        os.rmdir(uid_dir)
                except OSError:
                    pass

            os.makedirs(uid_dir, exist_ok=True)
            shutil.copy2(dl_path, dest)

            logger.info(f'Installed -> {os.path.relpath(dest, config_root)} (uid={uid})')
            installed[uid] = [dest]
            success += 1

    lines: list[str] = []
    lines.append('')
    lines.append('Download summary:')
    lines.append(f'  Configs processed      : {total}')
    lines.append(f'  Succeeded              : {success}')
    lines.append(f'  Skipped (installed)    : {skipped}')
    lines.append(f'  Failed                 : {len(failures)}')
    if failures:
        lines.append('  Failures:')
        for tag, reason in failures:
            lines.append(f'    - {tag}')
            lines.append(f'        reason: {reason}')

    print('\n'.join(lines))


def show_configs(args: argparse.Namespace) -> None:
    param = cast(ShowArgs, cast(object, args))
    detail = param.detail

    config_root = default_config_dir()

    lines: list[str] = []

    entries: list[tuple[schema.Module, list[str]]] = []
    uid_seen: dict[schema.Uid, int] = {}

    if os.path.isdir(config_root):
        files: list[str] = []
        for ext in CONFIG_EXTENSIONS:
            pattern = os.path.join('**', f'*.{ext}')
            ext_files = glob.glob(pattern, root_dir=config_root, recursive=True)
            files.extend([os.path.join(config_root, name) for name in ext_files])
        files = sorted(files)

        for f in files:
            try:
                json_object = load_config(f)
                module = schema.module.parse(json_object)
            except Exception as e:
                lines.append(f'[!] Skip unparsable config: {os.path.relpath(f, config_root)}')
                lines.append(f'    {e}')
                continue
            uid = module.module.uid
            if uid in uid_seen:
                entries[uid_seen[uid]][1].append(f)
            else:
                uid_seen[uid] = len(entries)
                entries.append((module, [f]))

    lines.append(f'Installed modules ({len(entries)} total):')
    if not entries:
        lines.append('  (none)')
    else:
        for module, sources in entries:
            m = module.module
            lines.append(f'  {m.name} v{m.version}')
            lines.append(f'    uid         : {m.uid}')
            if m.description:
                lines.append(f'    description : {m.description}')
            if m.keywords:
                lines.append(f'    keywords    : {", ".join(m.keywords)}')
            if detail and m.requirements:
                lines.append(f'    requirements: {", ".join(m.requirements)}')
            lines.append(f'    source(s)   :')
            for s in sources:
                lines.append(f'      - {os.path.relpath(s, config_root)}')

            lines.append(f'    packages ({len(module.packages)}):')
            if not module.packages:
                lines.append('      (none)')
            else:
                for p in module.packages:
                    lines.append(f'      - {p.name} v{p.version}')
                    lines.append(f'          uid         : {p.uid}')
                    if p.description:
                        lines.append(f'          description : {p.description}')
                    if p.keywords:
                        lines.append(f'          keywords    : {", ".join(p.keywords)}')
                    lines.append(f'          priority    : {p.priority}')
                    if p.provides:
                        lines.append(f'          provides    : {", ".join(p.provides)}')
                    if p.requires:
                        lines.append(f'          requires    : {", ".join(p.requires)}')
                    if detail and p.inputs:
                        lines.append(f'          inputs      : {", ".join(p.inputs)}')
                    if detail and p.usage_models:
                        lines.append(f'          usage_models: {", ".join(p.usage_models)}')
                    if p.parameters:
                        lines.append(f'          parameters ({len(p.parameters)}):')
                        for param in p.parameters:
                            default = ''
                            if param.value is not None:
                                default = f' = {param.value!r}'
                            selection = ''
                            if param.selection is not None:
                                selection = f' [{", ".join(param.selection)}]'
                            lines.append(
                                f'            - {param.name} ({param.type.value}){default}{selection}')
                    if p.models:
                        lines.append(f'          models ({len(p.models)}):')
                        for md in p.models:
                            tag = ' [recommended]' if md.recommended else ''
                            origin = ''
                            if detail:
                                if md.cloud is not None:
                                    origin = f' ({md.cloud.host}:{md.cloud.model_id})'
                                elif md.download is not None:
                                    origin = f' (download: {md.download.url})'
                                elif md.entry is not None:
                                    origin = f' (entry: {md.entry.method})'
                            lines.append(f'            - {md.name} v{md.version}{tag}{origin}')

    print('\n'.join(lines))


def setup_configs(args: argparse.Namespace) -> None:
    _ = cast(SetupArgs, cast(object, args))

    entries = _iter_default_modules()
    total = len(entries)
    success = 0
    skipped = 0
    failures: list[tuple[str, list[str], str]] = []

    logger.info(f'Setting up dependencies for {total} installed module(s)...')

    for module, sources in entries:
        m = module.module
        spec = m.requirements + [
            f'{r.name}{r.require or ""} (git+{r.repo})' for r in m.refs
        ]
        display_name = f'{m.name} v{m.version} (uid={m.uid})'
        logger.info(f'Installing dependencies for: {display_name}')

        if not spec:
            logger.info(f'No dependencies declared. Skip.')
            skipped += 1
            continue

        try:
            install_module_requirements(m)
            success += 1
            logger.info(f'Dependencies installed successfully.')
        except Exception as e:
            reason = f'{type(e).__name__}: {e}'
            logger.error(f'Failed to install dependencies for {display_name}: {reason}')
            failures.append((display_name, spec, reason))

    lines: list[str] = []
    lines.append('')
    lines.append('Setup summary:')
    lines.append(f'  Modules processed      : {total}')
    lines.append(f'  Succeeded              : {success}')
    lines.append(f'  Skipped (no deps)      : {skipped}')
    lines.append(f'  Failed                 : {len(failures)}')
    if failures:
        lines.append('  Failures:')
        for display_name, spec, reason in failures:
            lines.append(f'    - {display_name}')
            lines.append(f'        requested: {", ".join(spec)}')
            lines.append(f'        reason   : {reason}')

    print('\n'.join(lines))


def cache_models(args: argparse.Namespace) -> None:
    _ = cast(CacheArgs, cast(object, args))

    cache_dir = default_cache_dir()
    logger.info(f'Default model cache directory: {cache_dir}')

    entries = _iter_default_modules()
    total_models = 0
    already_cached = 0
    success = 0
    failures: list[tuple[str, str, str]] = []

    for module, sources in entries:
        m = module.module
        module_tag = f'{m.name} v{m.version} (uid={m.uid})'
        for package in module.packages:
            for md in package.models:
                total_models += 1
                model_tag = f'[{module_tag}] {package.name}::{md.name} v{md.version} (uid={md.uid})'
                logger.info(f'Processing model: {model_tag}')
                try:
                    usage_model = build_model(md, cache_dir=None)
                    if usage_model.exists():
                        logger.info(f'Already cached. Skip.')
                        already_cached += 1
                        continue
                    usage_model.cache()
                    logger.info(f'Cached successfully.')
                    success += 1
                except Exception as e:
                    reason = f'{type(e).__name__}: {e}'
                    logger.error(f'Failed to cache model {model_tag}: {reason}')
                    failures.append((model_tag, str(md.uid), reason))

    lines: list[str] = []
    lines.append('')
    lines.append('Cache summary:')
    lines.append(f'  Models processed       : {total_models}')
    lines.append(f'  Newly cached           : {success}')
    lines.append(f'  Already cached (skip)  : {already_cached}')
    lines.append(f'  Failed                 : {len(failures)}')
    if failures:
        lines.append('  Failures:')
        for model_tag, uid, reason in failures:
            lines.append(f'    - uid={uid} {model_tag}')
            lines.append(f'        reason: {reason}')

    print('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(
        description="SeetaPsych configuration manager",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        help="Available commands",
    )

    install_parser = subparsers.add_parser(
        "install",
        help="Install configuration file",
    )
    install_parser.set_defaults(func=install_config)
    install_parser.add_argument(
        "path",
        type=Path,
        help="Configuration file in toml/yaml/json",
    )

    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Uninstall configuration file",
    )
    uninstall_parser.set_defaults(func=uninstall_config)
    uninstall_parser.add_argument(
        "path",
        type=Path,
        help="Configuration file in toml/yaml/json",
    )

    download_parser = subparsers.add_parser(
        "download",
        help="Download and install all configs from seetapsych_configs",
    )
    download_parser.set_defaults(func=download_configs)
    download_parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force re-download and overwrite existing installed configs",
    )

    show_parser = subparsers.add_parser(
        "show",
        help="Show configuration files",
    )
    show_parser.set_defaults(func=show_configs)
    show_parser.add_argument(
        "-d", "--detail",
        action="store_true",
        help="Show full details including requirements, model origins and internal fields",
    )

    setup_parser = subparsers.add_parser(
        "setup",
        help="Cache current configs models",
    )
    setup_parser.set_defaults(func=setup_configs)

    cache_parser = subparsers.add_parser(
        "cache",
        help="Cache current configs models",
    )
    cache_parser.set_defaults(func=cache_models)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
