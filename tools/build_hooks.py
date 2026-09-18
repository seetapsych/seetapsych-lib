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


def _resolve_relative_path(base_file: Path, rel_path: str, repo_root: Path | None = None) -> str:
    """Resolve a relative path against the README location and return the repo-relative POSIX path.

    Args:
        base_file: Absolute path to the README file being processed.
        rel_path: The relative path component (may include a trailing anchor / query).
        repo_root: Absolute path to the repository root. When provided, targets
            are resolved against *base_file.parent* and then made relative to
            *repo_root* so callers always receive a repo-root-relative result,
            even when the original ``../`` escapes the README's own directory.

    Returns:
        Repository-root-relative POSIX path without leading ``./`` or ``../``
        escape markers. Preserves any trailing ``#anchor`` or ``?query``
        fragments on the original *rel_path*.  ``../`` sequences are
        normalised away via ``posixpath.normpath`` so final URLs never contain
        `/branch/../` segments that browsers must reinterpret on the server.
    """
    import posixpath

    anchor = ""
    if "#" in rel_path:
        rel_path, anchor = rel_path.split("#", 1)
        anchor = "#" + anchor

    raw = rel_path
    query = ""
    if "?" in rel_path:
        raw, query = rel_path.split("?", 1)
        query = "?" + query

    if repo_root is not None:
        try:
            resolved = (base_file.parent / raw).resolve(strict=False)
            repo_relative = resolved.relative_to(repo_root.resolve(strict=False))
        except ValueError:
            # Target escapes the repo entirely (e.g. `../../out-of-repo`).
            # Fall back to the raw input, normalised.
            posix = posixpath.normpath(raw.replace("\\", "/"))
            return posix + query + anchor
        posix = posixpath.normpath(repo_relative.as_posix())
        if posix == ".":
            posix = ""
        return posix + query + anchor

    resolved = (base_file.parent / raw).resolve(strict=False)
    relative_root = base_file.parent
    try:
        repo_relative = resolved.relative_to(relative_root.resolve(strict=False))
    except ValueError:
        posix = posixpath.normpath(raw.replace("\\", "/"))
        return posix + query + anchor

    posix = posixpath.normpath(repo_relative.as_posix())
    if posix == ".":
        posix = ""
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


def _find_matching_bracket(text: str, open_pos: int, open_char: str, close_char: str) -> int:
    r"""Return the index of the matching *close_char* for a bracket starting at *open_pos*.

    Tracks nested pairs of the same bracket type. Respects backslash escapes so
    that ``\\]``/``\\)`` inside quoted text do not prematurely terminate a match.
    Returns ``-1`` when the pair is unbalanced.

    Args:
        text: String to search inside.
        open_pos: Index of the opening bracket in *text* (must equal *open_char*).
        open_char: Opening bracket character (``[`` or ``(`` or ``<``).
        close_char: Closing bracket character (``]`` or ``)`` or ``>``).

    Returns:
        Index of the matching closing bracket, or ``-1`` if unbalanced.
    """
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != open_char:
        return -1
    depth = 1
    i = open_pos + 1
    escaped = False
    while i < len(text):
        ch = text[i]
        if escaped:
            escaped = False
            i += 1
            continue
        if ch == "\\":
            escaped = True
            i += 1
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


# ---------------------------------------------------------------------------
# Simple, non-backtracking regex building blocks.
# Every pattern below is intentionally "single-responsibility":
#   * anchors locate a candidate's starting position (or an attribute prefix)
#   * character classes are strictly negated sets with a clear terminator
#     (e.g. [^"]* ends at the next `"`), guaranteeing zero ambiguity / no
#     catastrophic-backtracking surface area.
# ---------------------------------------------------------------------------
_IMG_VIDEO_START_RE = re.compile(r"<\s*(img|video)\b", re.IGNORECASE)
_SRC_ATTR_RE = re.compile(
    r"""src\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
    re.IGNORECASE,
)
_MD_LINK_START_RE = re.compile(r"!?\[")
_AUTOLINK_START_RE = re.compile(r"<")
_CODE_SPAN_START_RE = re.compile(r"`")


def _parse_md_link_suffix(inner: str) -> tuple[str, str]:
    """Split a Markdown link ``"target"`` or ``"target \"title\""`` into parts.

    Args:
        inner: Raw text between the parentheses of a ``[text](...)`` link.

    Returns:
        ``(target, title_suffix)`` where *title_suffix* is the original
        whitespace + quoted title (e.g. ``' "My Title"'``) or ``""`` when no
        title is present. The caller decides whether the *target* needs to be
        rewritten; the title suffix is always preserved verbatim.
    """
    if not inner or inner[0].isspace():
        return inner, ""
    space_idx = -1
    for j, c in enumerate(inner):
        if c.isspace():
            space_idx = j
            break
    if space_idx == -1:
        return inner, ""
    target = inner[:space_idx]
    title_part = inner[space_idx:]
    return target, title_part


def _rewrite_html_attrs(content: str, owner: str, repo: str, branch: str, base_file: Path, root: Path) -> str:
    """Rewrite relative ``src`` attributes on ``<img>`` and ``<video>`` tags.

    Processing is split into two strictly separated layers to avoid any
    backtracking-prone regex:

    1. **Range anchor** — scan for ``<img`` / ``<video`` and find the matching
       ``>`` (simple character search; HTML tags in Markdown READMEs never
       contain unquoted ``>`` inside attribute values).
    2. **Field extraction** — once a tag slice is isolated, run a small,
       non-ambiguous regex to pull out ``src="..."`` / ``src='...'`` /
       ``src=...`` and decide whether to rewrite.

    Inline code spans are handled inside the per-line scanner to keep any HTML
    fragments written inside `` ` ``…`` ` `` verbatim — see
    :func:`_rewrite_html_attrs_in_text`.

    Args:
        content: Raw Markdown / HTML text.
        owner: GitHub owner/organization name.
        repo: Repository name.
        branch: Default branch name.
        base_file: Absolute path of the file being rewritten.
        root: Absolute project root (for directory vs file disambiguation).

    Returns:
        Content with relative ``src`` paths converted to absolute GitHub URLs.
        Fenced code blocks, indented code blocks, and inline code spans are
        preserved unchanged.
    """
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
        rewritten_lines.append(_rewrite_html_attrs_in_text(line, owner, repo, branch, base_file, root))

    return "".join(rewritten_lines)


def _rewrite_html_attrs_in_text(text: str, owner: str, repo: str, branch: str, base_file: Path, root: Path) -> str:
    """Rewrite img/video ``src`` attributes inside a single line, respecting code spans.

    Args:
        text: A piece of a single Markdown line. May contain inline code spans;
            they are preserved verbatim and never scanned for ``<img>``/
            ``<video>`` tag syntax.
        owner/repo/branch: GitHub coordinates for building absolute URLs.
        base_file: Absolute path of the README being rewritten.
        root: Absolute project root.

    Returns:
        Copy of *text* with relative ``src`` values on ``<img>``/``<video>``
        tags converted to absolute GitHub URLs.
    """
    out: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        img_match = _IMG_VIDEO_START_RE.search(text, pos)
        code_match = _CODE_SPAN_START_RE.search(text, pos)
        img_idx = img_match.start() if img_match is not None else n
        code_idx = code_match.start() if code_match is not None else n

        if code_idx <= img_idx:
            # Inline code span `...` — emit verbatim, skip interior.
            backtick_close = text.find("`", code_idx + 1)
            if backtick_close == -1:
                out.append(text[pos:])
                break
            out.append(text[pos : backtick_close + 1])
            pos = backtick_close + 1
            continue

        match = img_match
        tag_start = match.start()
        out.append(text[pos:tag_start])
        close_idx = text.find(">", match.end())
        if close_idx == -1:
            out.append(text[tag_start:])
            break
        tag_slice = text[tag_start : close_idx + 1]
        rebuilt = _maybe_rewrite_img_video_src(tag_slice, owner, repo, branch, base_file, root)
        out.append(rebuilt)
        pos = close_idx + 1
    return "".join(out)


def _maybe_rewrite_img_video_src(tag: str, owner: str, repo: str, branch: str, base_file: Path, root: Path) -> str:
    """If ``tag`` has a relative ``src``, rewrite it; otherwise return unchanged.

    The small ``_SRC_ATTR_RE`` regex is safe here because the match is bounded
    inside a pre-isolated slice between ``<img...`` and ``>`` — even if the
    pattern fails (e.g. malformed attribute quoting), it simply returns no
    match and the tag is preserved verbatim. No catastrophic-backtracking
    surface exists because each alternation ends at a distinct terminator
    (``"``, ``'``, or a whitespace/``>``).
    """
    src_match = _SRC_ATTR_RE.search(tag)
    if src_match is None:
        return tag
    value = (
        src_match.group(1)
        if src_match.group(1) is not None
        else (src_match.group(2) if src_match.group(2) is not None else src_match.group(3) or "")
    )
    if not _is_relative_local_path(value.strip()):
        return tag
    repo_rel = _resolve_relative_path(base_file, value.strip(), root)
    new_url = _build_url(owner, repo, branch, repo_rel, root)
    # Reconstruct the exact original attribute span (preserve quote style)
    full_match_start, full_match_end = src_match.span()
    original_attr = src_match.group(0)
    before_value = (
        original_attr[: src_match.start(1) - src_match.start()]
        if src_match.group(1) is not None
        else (
            original_attr[: src_match.start(2) - src_match.start()]
            if src_match.group(2) is not None
            else original_attr[: src_match.start(3) - src_match.start()]
        )
    )
    quote_end_idx = (
        src_match.end(1)
        if src_match.group(1) is not None
        else (src_match.end(2) if src_match.group(2) is not None else src_match.end(3))
    )
    after_value = original_attr[quote_end_idx - src_match.start() :]
    new_attr = f"{before_value}{new_url}{after_value}"
    return tag[:full_match_start] + new_attr + tag[full_match_end:]


def _rewrite_markdown_links(content: str, owner: str, repo: str, branch: str, base_file: Path, root: Path) -> str:
    """Rewrite Markdown ``[text](target)`` link targets outside code regions.

    The rewrite is performed in three stages to keep each regex tiny and
    unambiguous:

    1. **Anchor** — locate any ``[`` or ``![`` with ``_MD_LINK_START_RE``.
    2. **Boundary** — use :func:`_find_matching_bracket` (explicit depth
       counter, zero regex) to isolate the ``[text]`` portion and then the
       following ``(target ["title"])`` portion.
    3. **Split** — split the parenthesised content into target / title via a
       plain character scan, then decide whether to rewrite based on
       :func:`_is_relative_local_path`.

    This avoids the catastrophic-backtracking failure mode of the previous
    "one-regex-to-match-everything" approach while keeping the main loop
    readable and free of character-level if/else chains.

    Inline code spans (`` `...` ``) are skipped *inside* the per-line scanner
    so that Markdown links whose anchor text contains backtick-wrapped code
    (e.g. ``[`foo.py`](foo.py)``) remain syntactically intact — a pre-split
    on code spans would sever the ``[`` from the matching ``]``.

    Args:
        content: Raw Markdown text.
        owner/repo/branch: GitHub coordinates for building absolute URLs.
        base_file: Absolute path of the file being rewritten.
        root: Absolute project root.

    Returns:
        Content with relative link targets converted to absolute GitHub URLs.
        Fenced code blocks, indented code blocks, and inline code spans are
        preserved unchanged.
    """
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
        rewritten_lines.append(_rewrite_md_links_in_text(line, owner, repo, branch, base_file, root))

    return "".join(rewritten_lines)


def _rewrite_md_links_in_text(text: str, owner: str, repo: str, branch: str, base_file: Path, root: Path) -> str:
    """Rewrite Markdown links inside a single line, respecting inline code spans.

    Handles three Markdown syntaxes on one pass:

    1. **Standard inline links** — ``[text](target "title")`` /
       ``![alt](src "title")``. The bracket portion is processed recursively so
       that nested shapes such as ``[![alt](inner.png)](outer.mp4)`` result in
       *both* targets being rewritten.
    2. **Autolinks** — ``<https://example.com>`` / ``<relative/local/path>``
       (CommonMark §4.7). Only relative-local autolinks whose target resolves
       to an existing file on disk are rewritten; ``mailto:`` / ``<user@host>``
       style e-mail autolinks and absolute-URL autolinks are left untouched.
    3. **Bare ``<img>/<video>`` tags** are rewritten by an earlier pass
       (:func:`_rewrite_html_attrs`) and are not processed here.

    Inline code spans (`` `...` ``) are detected on the fly and skipped in
    full. This ensures anchors whose *display text* wraps content in
    backticks (e.g. ``[`foo.py`](foo.py)``) remain parseable — a pre-split
    strategy would sever ``[`` from the matching ``]``.

    Args:
        text: Piece of a single Markdown line. May contain inline code spans;
            they are preserved verbatim and never scanned for link syntax.
        owner/repo/branch: GitHub coordinates for building absolute URLs.
        base_file: Absolute path of the README being rewritten.
        root: Absolute project root.

    Returns:
        Copy of *text* with relative local links replaced by absolute GitHub
        URLs. Non-matching constructs are preserved byte-for-byte.
    """
    out: list[str] = []
    pos = 0
    n = len(text)
    base_dir = base_file.parent
    while pos < n:
        bracket_match = _MD_LINK_START_RE.search(text, pos)
        autolink_match = _AUTOLINK_START_RE.search(text, pos)
        code_span_match = _CODE_SPAN_START_RE.search(text, pos)
        bracket_idx = bracket_match.start() if bracket_match is not None else n
        autolink_idx = autolink_match.start() if autolink_match is not None else n
        code_span_idx = code_span_match.start() if code_span_match is not None else n

        if code_span_idx <= bracket_idx and code_span_idx <= autolink_idx:
            # ------------------------------------------------------------------
            # Case 0: Inline code span `...` — emit verbatim, skip interior.
            # ------------------------------------------------------------------
            backtick_close = text.find("`", code_span_idx + 1)
            if backtick_close == -1:
                out.append(text[pos:])
                break
            out.append(text[pos : backtick_close + 1])
            pos = backtick_close + 1
            continue

        if bracket_idx < autolink_idx:
            # ------------------------------------------------------------------
            # Case 1: Standard / image Markdown link `[text](target)`
            # ------------------------------------------------------------------
            anchor = bracket_match
            bracket_start = anchor.end() - 1  # position of '['
            bracket_end = _find_matching_bracket(text, bracket_start, "[", "]")
            if bracket_end == -1:
                out.append(text[pos : bracket_start + 1])
                pos = bracket_start + 1
                continue
            if bracket_end + 1 >= n or text[bracket_end + 1] != "(":
                out.append(text[pos : bracket_end + 1])
                pos = bracket_end + 1
                continue
            paren_start = bracket_end + 1
            paren_end = _find_matching_bracket(text, paren_start, "(", ")")
            if paren_end == -1:
                out.append(text[pos : paren_start + 1])
                pos = paren_start + 1
                continue
            # Rewrite the bracket interior *recursively* — this handles nested
            # `[![alt](inner.png)](outer.mp4)` / `[[ref](link)][ref]` shapes.
            bracket_interior = text[bracket_start + 1 : bracket_end]
            bracket_interior_rewritten = _rewrite_md_links_in_text(
                bracket_interior, owner, repo, branch, base_file, root
            )
            # Rewrite the outer (target "title") segment.
            out.append(text[pos : anchor.start()])
            bang_prefix = "!" if anchor.group(0).startswith("!") else ""
            prefix = f"{bang_prefix}[{bracket_interior_rewritten}]"
            inner_paren = text[paren_start + 1 : paren_end]
            target, title_suffix = _parse_md_link_suffix(inner_paren)
            if _is_relative_local_path(target):
                repo_rel = _resolve_relative_path(base_file, target, root)
                new_url = _build_url(owner, repo, branch, repo_rel, root)
                out.append(f"{prefix}({new_url}{title_suffix})")
            else:
                out.append(f"{prefix}({inner_paren})")
            pos = paren_end + 1
        elif autolink_idx < n:
            # ------------------------------------------------------------------
            # Case 2: Autolink `<...>` (CommonMark §4.7)
            # ------------------------------------------------------------------
            lt = autolink_idx
            gt = text.find(">", lt + 1)
            if gt == -1:
                out.append(text[pos:])
                break
            body = text[lt + 1 : gt]
            # Safeguard: Markdown autolinks must not contain whitespace.
            if any(c.isspace() for c in body):
                out.append(text[pos : lt + 1])
                pos = lt + 1
                continue
            # Strip an optional `?query` / `#fragment` suffix before filesystem
            # checks; we preserve the suffix exactly as-is after rewriting.
            affix = ""
            stripped_body = body
            for sep in ("#", "?"):
                if sep in stripped_body:
                    cut = stripped_body.index(sep)
                    affix = stripped_body[cut:] + affix
                    stripped_body = stripped_body[:cut]
            rewritten_body: str | None = None
            if _is_relative_local_path(stripped_body) and "@" not in stripped_body:
                candidate = (base_dir / stripped_body).resolve()
                try:
                    # Autolinks may target either files (assets, docs) or whole
                    # directories (indicated by trailing `/` in the source).
                    exists_on_disk = candidate.is_file() or candidate.is_dir()
                except OSError:
                    exists_on_disk = False
                if exists_on_disk:
                    repo_rel = _resolve_relative_path(base_file, stripped_body, root)
                    rewritten_body = _build_url(owner, repo, branch, repo_rel, root)
            out.append(text[pos:lt])
            final_body = rewritten_body if rewritten_body is not None else body
            out.append(f"<{final_body}{affix if rewritten_body is not None else ''}>")
            pos = gt + 1
        else:
            out.append(text[pos:])
            break
    return "".join(out)


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
