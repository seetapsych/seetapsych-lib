# -*- coding: utf-8 -*-
"""
Release tags follow the pattern ``r<PEP 440 version>`` where the
version body **must not contain a dash** (``-``) so it stays distinct
from the ``-N-gSHA`` suffix produced by ``git describe``.

Good tags:

* ``r1.0.0``           release
* ``r1.2.3b1``         beta
* ``r1.2.3rc2``        release candidate
* ``r2.0.0a5``         alpha
* ``r0.9.0.post1``     post release

Bad tags (ignored by the hatchling VCS version source):

* ``r1.0.0-beta.1``    dash inside the version body
* ``1.0.0``            missing ``r`` prefix
* ``r1.0.0-wip``       dash inside trailing segment
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

__all__ = [
    "__version__",
    "get_version",
    "FALLBACK_VERSION",
]


FALLBACK_VERSION: str = "0.0.0.dev0"

# Keep in sync with ``[tool.hatch.version] tag-pattern`` in pyproject.toml.
TAG_PATTERN = re.compile(r"^r(?P<version>[^-]+)$")


def _version_from_build_file() -> Optional[str]:
    try:
        from ._version import __version__  # type: ignore[import-not-found]

        return __version__.strip() or None
    except Exception:
        return None


def _package_root() -> Path:
    return Path(__file__).resolve().parent


def _run_git(*args: str) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(_package_root()), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    return completed.stdout.strip()


def _strip_tag_prefix(raw: str) -> str:
    m = TAG_PATTERN.match(raw)
    return m.group("version") if m else raw


def _parse_git_describe(raw: str) -> str:
    # Input shapes (``git describe --long --always``):
    #   r1.2.3-5-gabc1234   -> 1.2.3.post5.dev0+gabc1234
    #   r1.2.3b1-0-gdeadbea -> 1.2.3b1
    #   abc1234             -> 0.0.0.dev0+gabc1234  (no matching tag)
    m = re.match(r"^(?P<tag>.+)-(?P<count>\d+)-g(?P<sha>[^-]+)$", raw)
    if m:
        version = _strip_tag_prefix(m.group("tag"))
        try:
            n = int(m.group("count"))
        except ValueError:
            n = 0
        if n == 0:
            return version
        return f"{version}.post{n}.dev0+g{m.group('sha')}"

    rev = _run_git("rev-parse", "--short", "HEAD") or raw
    return f"{FALLBACK_VERSION}+g{rev.lstrip('g')}"


def _inside_git_worktree() -> bool:
    cur = _package_root()
    while True:
        if (cur / ".git").exists():
            return True
        parent = cur.parent
        if parent == cur:
            return False
        cur = parent


def get_version() -> str:
    """Return the full-precision version. No caching. Intended for debug use."""
    built = _version_from_build_file()
    if built is not None:
        return built
    if _inside_git_worktree():
        raw = _run_git(
            "describe",
            "--tags",
            "--long",
            "--always",
            "--match=r[0-9]*",
        )
        if raw:
            return _parse_git_describe(raw)
    return FALLBACK_VERSION


__version__: str = _version_from_build_file() or FALLBACK_VERSION
