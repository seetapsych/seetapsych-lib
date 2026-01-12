# -*- coding: utf-8 -*-

import glob
import os.path
import urllib.parse
import urllib.request
from typing import IO, Optional

from pydantic import BaseModel

from fabopsy_lib import schema
from fabopsy_lib.utils.loader import load, loads


__all__ = [
    'LoadedModule',
    'load_builtin_modules',
    'load_local_module',
    'load_url_module',
]


class LoadedModule(BaseModel):
    path: str               # the origin config path
    module: schema.Module   # loaded module


builtin_module_root = os.path.join(os.path.dirname(__file__), '..', 'modules')


def load_builtin_modules() -> list[LoadedModule]:
    extensions = ['json', 'toml', 'yaml', 'yml']

    files: list[str] = []
    for ext in extensions:
        pattern = os.path.join(builtin_module_root, '**', f'*.{ext}')
        files.extend(glob.glob(pattern, recursive=True))

    files = sorted(files)

    modules: list[LoadedModule] = []
    for module_file in files:
        module = schema.module.parse(load(module_file))
        modules.append(LoadedModule(path=module_file, module=module))

    return modules


def load_local_module(f: str | bytes | IO[str] | IO[bytes], extension: str = None) -> LoadedModule:
    module = schema.module.parse(load(f, extension))

    if isinstance(f, (str, bytes)):
        filename = f.decode(encoding='utf-8') if isinstance(f, bytes) else f
    else:
        filename = '<anonymous>'

    return LoadedModule(path=filename, module=module)


def load_url_module(url: str) -> LoadedModule:
    parsed = urllib.parse.urlparse(url)
    filename: Optional[str] = os.path.basename(parsed.path)

    if not filename or filename == '.' or filename == '..':
        # try extract file=xxx or filename=xxx in url query
        filename = None
        query = urllib.parse.parse_qs(parsed.query)
        if query:
            for name in ['filename', 'file']:
                if name in query:
                    filename = query[name][0]
                    break

    extension = os.path.splitext(filename)[-1] if filename else None

    try:
        with urllib.request.urlopen(url) as response:
            response: IO[bytes]
            content = response.read()
    except Exception:
        raise

    module = schema.module.parse(loads(content, extension))
    return LoadedModule(path=url, module=module)


def test():
    modules = load_builtin_modules()
    for m in modules:
        basename = os.path.basename(m.path)
        print(f'Loaded builtin: {basename} -> {", ".join([p.name for p in m.module.packages])}')

    if not modules:
        return

    local_module_path = modules[0].path
    for m in [load_local_module(local_module_path)]:
        basename = os.path.basename(m.path)
        print(f'Loaded local: {basename} -> {", ".join([p.name for p in m.module.packages])}')

    local_module_url = f'file:///{local_module_path}'
    for m in [load_url_module(local_module_url)]:
        basename = os.path.basename(urllib.parse.urlparse(m.path).path)
        print(f'Loaded url: {basename} -> {", ".join([p.name for p in m.module.packages])}')


if __name__ == '__main__':
    test()

