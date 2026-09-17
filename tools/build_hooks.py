# -*- coding: utf-8 -*-
"""Hatchling build hooks for PyPI README generation.

Dynamically rewrites the English README.md to convert relative resource paths
to absolute GitHub URLs for PyPI distribution, ensuring images and linked
documents resolve correctly on PyPI.org while the source README remains
GitHub-friendly with relative paths.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:  # pragma: no cover - import guard only for standalone tests
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
    from hatchling.metadata.plugin.interface import MetadataHookInterface
except ModuleNotFoundError:  # pragma: no cover - hatchling always available during builds
    BuildHookInterface = object  # type: ignore[assignment,misc]
    MetadataHookInterface = object  # type: ignore[assignment,misc]

IMAGE_VIDEO_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
    ".svg",
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".ogg",
}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
DEFAULT_BRANCH = "main"


def _extract_repo_info(root: str) -> tuple[str, str, str]:
    """Extract GitHub owner, repo name, and default branch.

    Args:
        root: Absolute path to the project root directory.

    Returns:
        Tuple of (owner, repo, branch). Falls back to the repository name
        derived from the project root if pyproject.toml parsing fails.
    """
    import sys

    pyproject_path = Path(root) / "pyproject.toml"
    owner = "seetapsych"
    repo = Path(root).name
    branch = DEFAULT_BRANCH

    try:
        if sys.version_info >= (3, 11):
            import tomllib as toml_loader  # type: ignore[import-not-found,no-redef]
        else:
            import tomli as toml_loader  # type: ignore[import-not-found,no-redef]
        with pyproject_path.open("rb") as f:
            data = toml_loader.load(f)
        urls = data.get("project", {}).get("urls", {})
        repo_url = urls.get("Repository") or urls.get("Homepage")
        if repo_url:
            match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url)
            if match:
                owner, repo = match.group(1), match.group(2)
    except (OSError, toml_loader.TOMLDecodeError, EOFError, ValueError):
        pass

    return owner, repo, branch


def _is_relative_local_path(path: str) -> bool:
    """Return True if *path* is a repository-relative local file reference.

    Skips: empty strings, URL schemes, protocol-agnostic ``//host`` links,
    page-internal fragment-only references, ``mailto:``, and server-absolute
    paths that start with ``/`` (those are not repo-relative).

    Args:
        path: The path or URL component to inspect.

    Returns:
        True when the target is a repo-relative file reference that should
        be rewritten to an absolute GitHub URL during PyPI packaging.
    """
    if not path:
        return False
    target = path.lstrip()
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return False
    if target.startswith(("/", "//", "#")) or target.startswith("mailto:"):
        return False
    return True


def _resolve_relative_path(base_file: Path, rel_path: str) -> str:
    """Resolve a relative path against the README location and return the repo-relative POSIX path.

    Args:
        base_file: Absolute path to the README file being processed.
        rel_path: The relative path component (may include a trailing anchor).

    Returns:
        Repository-root-relative POSIX path without leading ``./`` or ``../``
        escape markers. Preserves a trailing ``#anchor`` fragment when present.
    """
    anchor = ""
    if "#" in rel_path:
        rel_path, anchor = rel_path.split("#", 1)
        anchor = "#" + anchor

    raw = rel_path
    query = ""
    if "?" in rel_path:
        raw, query = rel_path.split("?", 1)
        query = "?" + query

    resolved = (base_file.parent / raw).resolve()
    root = base_file.parent
    try:
        repo_relative = resolved.relative_to(root)
    except ValueError:
        return rel_path

    posix = repo_relative.as_posix()
    return posix + query + anchor


def _is_directory_target(repo_rel_wo_affix: str, root: Path | None = None) -> bool:
    """Classify a relative target as directory vs file for GitHub URL routing.

    Decision order (first match wins):

    1. Explicit trailing ``/`` always signals a directory view, regardless of
       the local file system state. Authors use this for links that must stay
       a ``/tree/<branch>/`` GitHub directory page.
    2. When *root* is provided and the target exists locally, return the
       on-disk verdict: existing directories → ``True``, existing files →
       ``False``.
    3. Fall back to treating missing targets as files (``False``), which
       routes to ``/blob/<branch>/`` and matches the long-standing default
       for non-existent README references.
    """
    if repo_rel_wo_affix.endswith("/"):
        return True
    if root is not None:
        candidate = root / repo_rel_wo_affix
        try:
            if candidate.exists():
                return candidate.is_dir()
        except OSError:
            return False
    return False


def _build_url(owner: str, repo: str, branch: str, rel_path: str, root: Path | None = None) -> str:
    """Build the appropriate GitHub absolute URL for a repo-relative resource.

    Args:
        owner: GitHub owner/organization name.
        repo: Repository name.
        branch: Default branch name (typically ``main``).
        rel_path: Repository-relative path, possibly with query / fragment.
        root: Project-root path. When provided, real targets that exist on
            disk are auto-routed to ``/tree/<branch>/`` for directories and
            ``/blob/<branch>/`` for files. Trailing ``/`` always wins.

    Returns:
        An absolute URL targeting ``raw.githubusercontent.com`` for binary
        assets, ``/tree/<branch>/`` for directories (either via trailing
        ``/`` or a real local directory), and
        ``github.com/<org>/<repo>/blob/<branch>/`` otherwise.
    """
    fragment = ""
    if "#" in rel_path:
        rel_path, fragment = rel_path.split("#", 1)
        fragment = "#" + fragment

    query = ""
    if "?" in rel_path:
        rel_path, query = rel_path.split("?", 1)
        query = "?" + query

    ext = Path(rel_path).suffix.lower()
    encoded = quote(rel_path, safe="/")

    if ext in IMAGE_VIDEO_EXTENSIONS:
        base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{encoded}"
    elif ext in MARKDOWN_EXTENSIONS:
        base = f"https://github.com/{owner}/{repo}/blob/{branch}/{encoded}"
    elif _is_directory_target(rel_path, root):
        base = f"https://github.com/{owner}/{repo}/tree/{branch}/{encoded}"
    else:
        base = f"https://github.com/{owner}/{repo}/blob/{branch}/{encoded}"

    return base + query + fragment


def _rewrite_html_attrs(content: str, owner: str, repo: str, branch: str, base_file: Path, root: Path) -> str:
    """Rewrite ``src`` attributes on ``<img>`` and ``<video>`` tags outside code blocks.

    Args:
        content: Raw Markdown / HTML text.
        owner: GitHub owner/organization name.
        repo: Repository name.
        branch: Default branch name.
        base_file: Absolute path of the file being rewritten.
        root: Absolute path of the project root (used for directory vs file
            disambiguation when building GitHub URLs).

    Returns:
        Content with relative ``src`` paths converted to absolute URLs.
        Lines inside fenced code blocks (```` ``` ````), indented code blocks,
        or inline code spans are left unchanged.
    """

    def _replace_tag(match: re.Match[str]) -> str:
        full_tag = match.group(0)
        attr = match.group(1)
        if match.group(2) is not None:
            quote_char = '"'
            value = match.group(2)
        elif match.group(3) is not None:
            quote_char = "'"
            value = match.group(3)
        else:
            quote_char = '"'
            value = match.group(4) or ""

        if not _is_relative_local_path(value):
            return full_tag

        clean_value = value.strip()
        repo_rel = _resolve_relative_path(base_file, clean_value)
        new_url = _build_url(owner, repo, branch, repo_rel, root)
        return full_tag.replace(
            f"{attr}={quote_char}{value}{quote_char}",
            f"{attr}={quote_char}{new_url}{quote_char}",
        )

    tag_pattern = re.compile(
        r"<(?:img|video)\b[^>]*?\s(src)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))[^>]*>",
        re.IGNORECASE,
    )
    code_span_pattern = re.compile(r"`[^`\n]*`")

    in_code_block = False
    rewritten_lines: list[str] = []
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            rewritten_lines.append(line)
            continue
        if in_code_block or re.match(r"^( {4,}|\t)", line):
            rewritten_lines.append(line)
            continue

        segments: list[str] = []
        cursor = 0
        for span in code_span_pattern.finditer(line):
            segments.append(line[cursor : span.start()])
            segments.append(span.group(0))
            cursor = span.end()
        tail = line[cursor:]
        tail = tag_pattern.sub(_replace_tag, tail)
        segments.append(tail)
        rewritten_lines.append("".join(segments))

    return "".join(rewritten_lines)


def _rewrite_markdown_links(content: str, owner: str, repo: str, branch: str, base_file: Path, root: Path) -> str:
    """Rewrite Markdown ``[text](target)`` link targets outside code regions.

    Args:
        content: Raw Markdown text.
        owner: GitHub owner/organization name.
        repo: Repository name.
        branch: Default branch name.
        base_file: Absolute path of the file being rewritten.
        root: Absolute path of the project root.

    Returns:
        Content with relative link targets converted to absolute URLs.
        Fenced / indented code blocks and inline code spans are preserved.
    """
    in_code_block = False
    lines = content.splitlines(keepends=True)
    rewritten: list[str] = []

    link_pattern = re.compile(r"(!?\[(?:[^\[\]()]+|\[[^\]]*\]|\([^)]*\))*\])\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
    code_span_pattern = re.compile(r"`[^`\n]*`")

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            rewritten.append(line)
            continue
        if in_code_block or re.match(r"^( {4,}|\t)", line):
            rewritten.append(line)
            continue

        def _replace(match: re.Match[str]) -> str:
            prefix = match.group(1)
            target = match.group(2)
            suffix = match.group(0)[match.end(2) : match.end(0) - 1]

            if not _is_relative_local_path(target):
                return match.group(0)

            repo_rel = _resolve_relative_path(base_file, target)
            new_url = _build_url(owner, repo, branch, repo_rel, root)
            return f"{prefix}({new_url}{suffix})"

        segments: list[str] = []
        cursor = 0
        for span in code_span_pattern.finditer(line):
            before = line[cursor : span.start()]
            before = link_pattern.sub(_replace, before)
            segments.append(before)
            segments.append(span.group(0))
            cursor = span.end()
        tail = line[cursor:]
        tail = link_pattern.sub(_replace, tail)
        segments.append(tail)
        rewritten.append("".join(segments))

    return "".join(rewritten)


def rewrite_readme_for_pypi(readme_path: Path, root: str) -> str:
    """Apply all rewriting transforms to produce a PyPI-suitable README.

    Args:
        readme_path: Absolute path to the source README.md.
        root: Absolute path to the project root (for repo-info extraction and
            directory-vs-file disambiguation).

    Returns:
        The fully rewritten README content as a string.
    """
    owner, repo, branch = _extract_repo_info(root)
    root_path = Path(root)
    content = readme_path.read_text(encoding="utf-8")
    content = _rewrite_html_attrs(content, owner, repo, branch, readme_path, root_path)
    content = _rewrite_markdown_links(content, owner, repo, branch, readme_path, root_path)
    return content


class CustomMetadataHook(MetadataHookInterface):
    """Hatchling metadata hook that dynamically rewrites the project README.

    The source ``README.md`` uses repository-relative paths so that rendering
    on GitHub.com is correct for every branch and pull request. During
    package build this hook transforms every relative reference into an
    absolute GitHub URL and injects the transformed Markdown into the
    package metadata as the PyPI long description.
    """

    PLUGIN_NAME = "custom"

    def update(self, metadata: dict[str, Any]) -> None:
        """Hook entry point invoked while Hatch assembles project metadata.

        Args:
            metadata: Mutable project metadata dictionary; the ``readme``
                entry is replaced in-place with the rewritten long-description
                payload (``text`` + ``content-type``).
        """
        root = Path(self.root)
        source_readme = root / "README.md"
        if not source_readme.exists():
            return

        rewritten = rewrite_readme_for_pypi(source_readme, str(root))
        metadata["readme"] = {
            "content-type": "text/markdown",
            "text": rewritten,
        }
