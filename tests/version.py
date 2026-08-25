# -*- coding: utf-8 -*-

from typing import Optional

from packaging.version import Version, InvalidVersion

import seetapsych_lib
from seetapsych_lib.utils.logger import logger


def main() -> Optional[int]:
    released_version = seetapsych_lib.__version__
    dev_version = seetapsych_lib.get_version()

    print(f"released   (__version__ attribute): {released_version!r}")
    print(f"developing (get_version(), runtime): {dev_version!r}")

    try:
        rv = Version(released_version)
        dv = Version(dev_version)
    except InvalidVersion as exc:
        logger.error(f"invalid PEP 440 version: {exc}")
        return 2

    if rv > dv:
        logger.warning(
            "released version is NEWER than the in-memory developing version;"
            " this usually means the built ``_version.py`` is stale (re-run the"
            " build / uv sync) or the tag history was rewritten.\n"
            f"  released  : {released_version}\n"
            f"  developing: {dev_version}"
        )
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
