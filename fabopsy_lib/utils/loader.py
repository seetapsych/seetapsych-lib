# -*- coding: utf-8 -*-

import json
import os.path
from typing import Any, Callable, IO

import tomli
import yaml


__all__ = [
    'load',
    'loads',
]


def parse_json(content: str) -> Any:
    return json.loads(content)


def parse_toml(content: str) -> Any:
    return tomli.loads(content)


def parse_yaml(content: str) -> Any:
    return yaml.safe_load(content)


map_parser: dict[str, Callable[[str], Any]] = {
    'json': parse_json,
    'toml': parse_toml,
    'yaml': parse_yaml,
    'yml': parse_yaml,
}


def try_parse(content: str) -> tuple[bool, Any]:
    try:
        return True, parse_json(content)
    except Exception:
        pass
    try:
        return True, parse_toml(content)
    except Exception:
        pass
    try:
        return True, parse_yaml(content)
    except Exception:
        pass
    return False, None


def load(f: str | bytes | IO[str] | IO[bytes], extension: str = None) -> Any:
    if isinstance(f, (str, bytes)):
        filename = f.decode(encoding='utf-8') if isinstance(f, bytes) else f
        extension = extension if extension else os.path.splitext(filename)[-1]
        with open(filename, 'r', encoding='utf-8') as stream:
            content = stream.read()
    elif hasattr(f, 'read'):
        content = f.read()
    else:
        raise RuntimeError('param f should be: str | bytes | IO[str] | IO[bytes]')

    return loads(content, extension)


def loads(content: str | bytes, extension: str = None) -> Any:
    content = content.decode(encoding='utf-8') if isinstance(content, bytes) else content

    if extension:
        extension = extension.strip('. ').lower()
    else:
        ok, parsed = try_parse(content)
        if ok:
            return parsed
        raise RuntimeError('Unable to identify content extension')

    parser = map_parser.get(extension)
    if parser is None:
        raise RuntimeError(f'Unrecognized file extension: {extension}')

    return parser(content)


if __name__ == '__main__':
    project_toml = os.path.join(os.path.dirname(__file__), '..', '..', 'pyproject.toml')
    project = load(project_toml)
    print(json.dumps(project, ensure_ascii=False, indent=2))
