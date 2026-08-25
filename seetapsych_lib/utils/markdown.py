# -*- coding: utf-8 -*-

import os

from typing import Any

if not os.environ.get('LANG'):
    os.environ['LANG'] = 'en_US.UTF-8'

import jsonschema2md


__all__ = [
    'schema2markdown',
]


def schema2markdown(schema: dict[str, Any]) -> str:
    parser = jsonschema2md.Parser()

    md = parser.parse_schema(schema, fail_on_error_in_defs=False)
    return ''.join(md)


def main():
    pass


if __name__ == '__main__':
    main()
