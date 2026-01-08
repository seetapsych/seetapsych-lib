# -*- coding: utf-8 -*-

import json
import os.path
from typing import Any, Callable, IO

import tomli
import yaml


__all__ = [
    'load',
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

def load(f: str | bytes | IO[str] | IO[bytes], extension: str = None) -> Any:
    if isinstance(f, (str, bytes)):
        filename = f.decode(encoding='utf-8') if isinstance(f, bytes) else f
        extension = extension if extension else os.path.splitext(filename)[-1]
        extension = extension.strip('. ').lower()
        with open(f, 'r', encoding='utf-8') as stream:
            content = stream.read()
    elif hasattr(f, 'read'):
        content = f.read()
        content = content.decode(encoding='utf-8') if isinstance(content, bytes) else content
    else:
        raise RuntimeError('param f should be: str | bytes | IO[str] | IO[bytes]')

    if not extension:
        raise RuntimeError('Unable to identify file type')

    parser = map_parser.get(extension)
    if parser is None:
        raise RuntimeError(f'Unrecognized file type: {extension}')

    return parser(content)


if __name__ == '__main__':
    project_toml = os.path.join(os.path.dirname(__file__), '..', '..', 'pyproject.toml')
    project = load(project_toml)
    print(json.dumps(project, ensure_ascii=False, indent=2))
