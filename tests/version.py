# -*- coding: utf-8 -*-

import logging
import os.path
from typing import Optional

import tomli

import fabopsy_lib
import fabopsy_lib.api


def main() -> Optional[int]:
    project_toml = os.path.join(os.path.dirname(__file__), '..', 'pyproject.toml')

    with open(project_toml, 'rb') as f:
        project = tomli.load(f)

    project_version = project['project']['version']
    library_version = fabopsy_lib.___version___

    if project_version != library_version:
        logging.warning(f"project and library version mismatch:\n"
                        f"\tfabopsy_lib.___version___ = '{library_version}'\n"
                        f"\tpyproject.toml > project > version = '{project_version}'")
        print(library_version)
        return 1
    else:
        print(library_version)
        return 0


if __name__ == '__main__':
    exit(main())
