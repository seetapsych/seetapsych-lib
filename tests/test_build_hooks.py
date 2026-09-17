"""Unit tests for tools/build_hooks.py README rewriting logic.

These tests exercise the three Markdown/HTML rewriting primitives against a
temporary fake project layout so behaviour is reproducible without depending
on either:

  * the real SeetaPsych git remote / default branch, or
  * the presence of any website/ asset files on the real filesystem.

The fake project root used by all cases is constructed in ``_FakeRepo`` and
tear down on test exit.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_BUILD_HOOKS_PATH = (_HERE.parent / "tools" / "build_hooks.py").resolve()


def _load_build_hooks(path: Path) -> types.ModuleType:
    """Load ``build_hooks.py`` by file path.

    Reimports under a unique module name per call so edits to global state in
    one test do not leak into the next.
    """
    spec = importlib.util.spec_from_file_location(f"_bh_test_{path.stem}_{abs(hash(str(path))) & 0xFFFFF}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def fake_repo():
    """Create a fake project + READMEs + asset files on disk.

    Module-scoped so asset files are created once for the whole test module,
    then removed on teardown.
    """
    tmp = Path(tempfile.mkdtemp(prefix="bh_repo_"))
    (tmp / "docs").mkdir()
    (tmp / "assets").mkdir()
    (tmp / "datasets").mkdir()
    # Files referenced by autolink / HTML-src / Markdown / extension-classifier tests.
    asset_files = [
        "assets/logo.png",
        "assets/demo.mp4",
        "assets/chart.svg",
        "assets/report.pdf",
        "docs/install.md",
        "docs/sibling.md",
        # Extra extensions to exercise every entry in IMAGE_VIDEO_EXTENSIONS.
        "assets/photo.jpg",
        "assets/shot.jpeg",
        "assets/anim.gif",
        "assets/icon.bmp",
        "assets/lossless.webp",
        "assets/clip.webm",
        "assets/teaser.mov",
        "assets/capture.avi",
        "assets/audio.ogg",
        "assets/dataset.json",
    ]
    for rel in asset_files:
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00fake-bytes")
    (tmp / "datasets" / "001.bin").write_bytes(b"\x00")
    (tmp / "quickstart.txt").write_text("lorem ipsum", encoding="utf-8")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def build_hooks_mod():
    """Single reusable import of the build_hooks module under test."""
    return _load_build_hooks(_BUILD_HOOKS_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_OWNER = "seetapsych"
_REPO_NAME = "test-repo"
_REPO_BRANCH = "staging"


def _rewrite(build_hooks_mod: types.ModuleType, markdown: str, readme_path: Path, repo_root: Path) -> str:
    """Apply the same two-pass transform order used by ``rewrite_readme_for_pypi``.

    We bypass ``rewrite_readme_for_pypi`` itself because it reads the input
    file on disk and calls ``_extract_repo_info`` (needs git). Tests feed
    *markdown* directly with fixed (owner, repo, branch) coordinates.
    """
    owner, repo, branch = _REPO_OWNER, _REPO_NAME, _REPO_BRANCH
    content = build_hooks_mod._rewrite_html_attrs(markdown, owner, repo, branch, readme_path, repo_root)
    content = build_hooks_mod._rewrite_markdown_links(content, owner, repo, branch, readme_path, repo_root)
    return content


def _raw_url(rel: str) -> str:
    """Return the expected absolute GitHub raw URL for a repo-root-relative *rel*."""
    return f"https://raw.githubusercontent.com/{_REPO_OWNER}/{_REPO_NAME}/{_REPO_BRANCH}/{rel.lstrip('/')}"


def _blob_url(rel: str) -> str:
    """Return the expected blob URL (used for markdown/docs targets)."""
    return f"https://github.com/{_REPO_OWNER}/{_REPO_NAME}/blob/{_REPO_BRANCH}/{rel.lstrip('/')}"


# ---------------------------------------------------------------------------
# 1. Basic Markdown links + images (no nesting)
# ---------------------------------------------------------------------------


class TestBasicMarkdown:
    def test_image_local_path_rewrite(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "See: ![Logo](assets/logo.png) above."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _raw_url("assets/logo.png") in out, f"logo.png not rewritten: {out!r}"

    def test_link_markdown_target_uses_blob_url(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "Read [install guide](docs/install.md) first."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _blob_url("docs/install.md") in out

    def test_link_with_double_quoted_title_preserved(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = '[x](assets/chart.svg "the chart caption")'
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _raw_url("assets/chart.svg") in out
        assert '"the chart caption"' in out

    def test_absolute_http_url_untouched(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = '![remote](https://cdn.example.com/a.png "title")'
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out == src, f"absolute URL must not be rewritten, got: {out!r}"

    def test_protocol_relative_url_untouched(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "[cdn link](//cdn.example.com/x.png)"
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out == src

    def test_same_page_anchor_untouched(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "[jump](#section)"
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out == src

    def test_mailto_link_untouched(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "[email us](mailto:team@example.com)"
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out == src

    def test_markdown_anchor_fragment_preserved(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "See [install guide](docs/install.md#windows-steps)."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _blob_url("docs/install.md") + "#windows-steps" in out, out

    def test_markdown_query_string_preserved(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = '![v](assets/anim.gif?v=1.2 "the gif")'
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _raw_url("assets/anim.gif") + "?v=1.2" in out, out
        assert '"the gif"' in out

    def test_consecutive_links_each_rewritten(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "[one](docs/install.md) then [two](docs/sibling.md) and [three](assets/logo.png)."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _blob_url("docs/install.md") in out, f"one not rewritten: {out!r}"
        assert _blob_url("docs/sibling.md") in out, f"two not rewritten: {out!r}"
        assert _raw_url("assets/logo.png") in out, f"three not rewritten: {out!r}"

    def test_chinese_unicode_text_untouched(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """Non-ASCII alt text / link text must stay byte-identical around rewrites."""
        from urllib.parse import unquote

        src = '[![示意图 中文alt📊](assets/chart.svg)](docs/安装指南.md "中文标题")'
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert "示意图 中文alt📊" in out, f"chinese alt text corrupted: {out!r}"
        assert '"中文标题"' in out, f"chinese title corrupted: {out!r}"
        assert _raw_url("assets/chart.svg") in out
        # Non-ASCII path components get percent-encoded by urllib.parse.quote
        # (safe="/"). Decode to verify the filename was preserved *semantically*.
        decoded_output = unquote(out)
        assert "/blob/staging/docs/安装指南.md" in decoded_output, (
            f"chinese markdown target path not preserved (after unquote): {decoded_output!r}"
        )

    def test_image_video_extension_classifier_exhaustive(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """All IMAGE_VIDEO_EXTENSIONS must use /raw/; markdown extensions must use /blob/."""
        raw_cases = [
            ("jpg", "[i](assets/photo.jpg)"),
            ("jpeg", "[i](assets/shot.jpeg)"),
            ("gif", "[i](assets/anim.gif)"),
            ("bmp", "[i](assets/icon.bmp)"),
            ("webp", "[i](assets/lossless.webp)"),
            ("webm", "[i](assets/clip.webm)"),
            ("mov", "[i](assets/teaser.mov)"),
            ("avi", "[i](assets/capture.avi)"),
            ("ogg", "[i](assets/audio.ogg)"),
        ]
        for ext, src in raw_cases:
            out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
            assert f"/{_REPO_BRANCH}/assets/" in out and "raw.githubusercontent.com" in out, (
                f"{ext} should use raw URL, got: {out!r}"
            )
        # Markdown / text extensions → /blob/
        for ext, src in (
            ("md", "[x](docs/install.md)"),
            ("txt", "[x](quickstart.txt)"),
            ("pdf", "[x](assets/report.pdf)"),
            ("json", "[x](assets/dataset.json)"),
        ):
            out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
            assert f"blob/{_REPO_BRANCH}/" in out, f"{ext} should use blob URL, got: {out!r}"

    def test_leading_dot_slash_relative_paths_resolved(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """Paths beginning with ``./`` are still recognised and resolved."""
        src = "![L](./assets/logo.png). See [this](./docs/install.md)."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _raw_url("assets/logo.png") in out, f"./assets not resolved: {out!r}"
        assert _blob_url("docs/install.md") in out, f"./docs not resolved: {out!r}"
        assert "/staging/./" not in out, f"leading ./ not normalised: {out!r}"

    def test_trailing_slash_directory_target_routed_to_tree(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """Explicit trailing ``/`` means GitHub directory tree view, not blob."""
        src = "[datasets folder](datasets/)."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        tree_url = f"https://github.com/{_REPO_OWNER}/{_REPO_NAME}/tree/{_REPO_BRANCH}/datasets"
        # Trailing / in the original is stripped during normpath but the
        # directory-target classifier sees the trailing "/" and routes to tree.
        assert tree_url in out, f"datasets/ must route to /tree/, got: {out!r}"
        assert "/blob/" not in out or "/tree/" in out, f"datasets/ routed to blob instead of tree: {out!r}"


# ---------------------------------------------------------------------------
# 2. Nested Markdown links (the bug reported in README L47 of hertz)
# ---------------------------------------------------------------------------


class TestNestedMarkdownLinks:
    def test_image_as_link_anchor_inner_and_outer_both_rewritten(
        self, build_hooks_mod: types.ModuleType, fake_repo: Path
    ):
        """Regression case: ``[![alt](inner.png)](outer.mp4)`` rewrites BOTH URLs."""
        src = "[![preview](assets/logo.png)](assets/demo.mp4)"
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        # 1) Syntactic — expected absolute URLs must appear in output.
        assert _raw_url("assets/logo.png") in out, f"inner image not rewritten: {out!r}"
        assert _raw_url("assets/demo.mp4") in out, f"outer video not rewritten: {out!r}"
        # 2) Structural — peel two layers of `](...)` matches from the out string.
        #    Outer link is `[<inner>](<outer_target>)`. The first `](` closes the inner
        #    image; the *second* `](` closes the outer text link.
        first_close = out.find("](")
        second_close = out.find("](", first_close + 2)
        assert second_close > 0, f"outer link boundary not found in: {out!r}"
        first_end = out.find(")", first_close + 2)
        second_end = out.find(")", second_close + 2)
        assert first_end > 0 and second_end > 0, f"unbalanced parens: {out!r}"
        inner_target = out[first_close + 2 : first_end]
        outer_target = out[second_close + 2 : second_end]
        # Both targets must now be absolute GitHub URLs.
        for where, tgt in (("inner", inner_target), ("outer", outer_target)):
            assert tgt.startswith(("https://raw.githubusercontent.com/", "https://github.com/")), (
                f"{where} target not absolute: {tgt!r} (full out: {out!r})"
            )

    def test_deep_nested_text_link(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """``[[inner link](doc1) outer](doc2)`` -> doc1 AND doc2 become absolute."""
        src = "[[see install](docs/install.md) for context](docs/sibling.md)"
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _blob_url("docs/install.md") in out, f"inner doc not rewritten: {out!r}"
        assert _blob_url("docs/sibling.md") in out, f"outer doc not rewritten: {out!r}"

    def test_triply_nested_image_in_text_in_image(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """Ensure recursion still terminates and handles balanced brackets on >2 levels."""
        src = "[![[![n3](assets/chart.svg)](docs/install.md)](assets/logo.png)](assets/demo.mp4)"
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        # All three relative targets must be absolute now.
        for rel in ("assets/chart.svg", "docs/install.md", "assets/logo.png", "assets/demo.mp4"):
            if rel.endswith((".md",)):
                assert _blob_url(rel) in out, f"missing blob rewrite for {rel}"
            else:
                assert _raw_url(rel) in out, f"missing raw rewrite for {rel}"


# ---------------------------------------------------------------------------
# 3. HTML <img> / <video> src attributes
# ---------------------------------------------------------------------------


class TestHtmlImgVideo:
    def test_img_double_quoted_src_rewrite(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = '<p>pic <img src="assets/logo.png" alt="x" /></p>'
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _raw_url("assets/logo.png") in out

    def test_video_single_quoted_src_rewrite(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "<video src='assets/demo.mp4' controls></video>"
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _raw_url("assets/demo.mp4") in out

    def test_img_unquoted_src_rewrite(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "<IMG SRC=assets/chart.svg>"
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _raw_url("assets/chart.svg") in out

    def test_html_absolute_url_src_untouched(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = '<img src="https://example.com/x.png" />'
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out == src

    def test_html_whitespace_around_equals_sign(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = '<video src  =  "assets/demo.mp4" playsinline>'
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _raw_url("assets/demo.mp4") in out


# ---------------------------------------------------------------------------
# 4. Autolinks: <local/path.ext> (CommonMark §4.7)
# ---------------------------------------------------------------------------


class TestAutolinks:
    def test_autolink_local_existing_file_rewritten(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "Download from <assets/report.pdf> now."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        # .pdf is a document-type target, routed through /blob/ (GitHub viewer).
        assert f"<{_blob_url('assets/report.pdf')}>" in out, f"autolink pdf not rewritten (got {out!r})"

    def test_autolink_local_nonexistent_file_preserved(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "See <assets/not-there.pdf> if you can."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        # File does not exist -> keep original untouched.
        assert "<assets/not-there.pdf>" in out

    def test_autolink_absolute_http_url_preserved(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "Visit <https://example.com/page?q=1> for more."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out == src

    def test_autolink_email_address_preserved(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "Mail to <team@example.com> please."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out == src

    def test_autolink_mailto_url_preserved(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "Link: <mailto:team@example.com>."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out == src

    def test_autolink_sibling_of_readme_txt(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """<quickstart.txt> lives next to README.md; it should resolve and rewrite to /blob/."""
        src = "Sidecar: <quickstart.txt>."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert f"<{_blob_url('quickstart.txt')}>" in out, f"did not rewrite sidecar autolink: {out!r}"

    def test_autolink_media_asset_png_routed_through_raw(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """Image/video extensions on autolinks still use the raw CDN URL."""
        src = "Logo: <assets/logo.png>."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert f"<{_raw_url('assets/logo.png')}>" in out, f"autolink png should be routed to /raw/: {out!r}"

    def test_non_autolink_with_whitespace_preserved(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """CommonMark autolinks cannot contain whitespace; ensure it stays as-is."""
        src = "Broken: <assets/report .pdf>."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out == src

    def test_autolink_anchor_fragment_preserved(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "Link: <docs/install.md#linux>."
        # docs/install.md exists; autolink body: "docs/install.md#linux" -> strip anchor to check file
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        expected = _blob_url("docs/install.md") + "#linux"
        assert f"<{expected}>" in out, f"anchored autolink not rewritten: {out!r}"

    def test_autolink_trailing_slash_directory_routes_to_tree(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """``<datasets/>`` (with trailing slash) autolinks an existing local directory."""
        src = "Under <datasets/> you find everything."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        # datasets/ exists on disk; trailing slash classifier -> tree/
        assert f"https://github.com/{_REPO_OWNER}/{_REPO_NAME}/tree/{_REPO_BRANCH}/datasets" in out, (
            f"directory autolink should use /tree/, got: {out!r}"
        )

    def test_absolute_local_windows_path_not_rewritten(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """Drive-letter absolute paths (Windows) are never rewritten to GitHub URLs."""
        src = "[local](C:/Users/admin/report.pdf) or [x](D:/smile.png)."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out == src, f"absolute local paths must not be rewritten: {out!r}"

    def test_title_that_contains_parens_is_preserved(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """Regression: the quoted title portion may contain ``(`` and ``)`` — do not
        let the simple first-space split consume the closing parenthesis boundary."""
        src = '[chart](assets/chart.svg "see figure 1 (top-left)")'
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert _raw_url("assets/chart.svg") in out
        assert '"see figure 1 (top-left)"' in out, f"nested parens inside title were mangled: {out!r}"


# ---------------------------------------------------------------------------
# 5. Code-block / code-span preservation (must never be rewritten)
# ---------------------------------------------------------------------------


class TestCodeRegionsPreserved:
    def test_fenced_code_block_untouched(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = (
            "Before.\n"
            "```md\n"
            "![x](assets/logo.png) <img src='assets/chart.svg'>\n"
            "```\n"
            "After: ![x](assets/logo.png)."  # <- this one IS rewritten
        )
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        fence_line = [ln for ln in out.splitlines() if "![x]" in ln and "<img" in ln][0]
        assert "](assets/logo.png)" in fence_line, "fenced block image was corrupted"
        assert "<img src='assets/chart.svg'>" in fence_line, "fenced html was corrupted"
        # Non-fenced line got rewritten.
        after_line = [ln for ln in out.splitlines() if ln.startswith("After:")][0]
        assert _raw_url("assets/logo.png") in after_line

    def test_indented_code_block_untouched(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = (
            "Before:\n"
            "    [![a](assets/logo.png)](docs/install.md)  # indented = code\n"
            "\n"
            "Real ref: [i](docs/install.md)."
        )
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        indented_line = [ln for ln in out.splitlines() if ln.startswith("    ")][0]
        assert "](docs/install.md)" in indented_line, "indented code block was corrupted"
        real_line = [ln for ln in out.splitlines() if ln.startswith("Real ref:")][0]
        assert _blob_url("docs/install.md") in real_line

    def test_inline_code_span_untouched(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "Use `[![img](assets/logo.png)](assets/demo.mp4)` syntax or real [x](docs/install.md)."
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        span = out.split("`")[1]  # between backticks
        assert "](assets/logo.png)" in span, "inline code span inner image was corrupted"
        assert "](assets/demo.mp4)" in span, "inline code span outer was corrupted"
        assert _blob_url("docs/install.md") in out, "sibling non-code link not rewritten"


# ---------------------------------------------------------------------------
# 6. Robustness: malformed / edge inputs must not crash
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_unbalanced_opening_bracket_no_crash(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "hello [unbalanced world without close"
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out.startswith("hello [")

    def test_unbalanced_autolink_no_crash(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "text <https://example.com/no closing angle bracket"
        out = _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo)
        assert out == src

    def test_empty_doc(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        assert _rewrite(build_hooks_mod, "", fake_repo / "README.md", fake_repo) == ""

    def test_whitespace_only(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        src = "\n\n   \n\t\n"
        assert _rewrite(build_hooks_mod, src, fake_repo / "README.md", fake_repo) == src


# ---------------------------------------------------------------------------
# 7. README in a subdirectory resolves paths relative to its own folder
# ---------------------------------------------------------------------------


class TestSubdirReadme:
    def test_readme_in_docs_dir_resolves_assets_via_dotdot(self, build_hooks_mod: types.ModuleType, fake_repo: Path):
        """README at ``docs/README.md``; ``../`` correctly climbs out of docs/."""
        src = (
            "Screenshot: ![cap](../assets/chart.svg).\n"
            "Cross link: [sibling](./sibling.md).\n"
            "Autolink: <../assets/report.pdf>.\n"
            "Autolink png: <../assets/logo.png>."
        )
        docs_readme = fake_repo / "docs" / "README.md"
        docs_readme.write_text("placeholder", encoding="utf-8")
        try:
            out = _rewrite(build_hooks_mod, src, docs_readme, fake_repo)
        finally:
            docs_readme.unlink(missing_ok=True)
        # ``../assets/chart.svg`` must resolve to repo-root /assets/chart.svg
        # (raw URL for media), NOT to `staging/../assets/...`.
        assert _raw_url("assets/chart.svg") in out, f"../assets not resolved: {out!r}"
        assert "/staging/../" not in out, f"dotdot not normalised in URL: {out!r}"
        # ``./sibling.md`` resolves to docs/sibling.md (blob URL since markdown).
        assert _blob_url("docs/sibling.md") in out, f"./sibling not resolved: {out!r}"
        # ``../assets/report.pdf`` → document (blob URL).
        assert f"<{_blob_url('assets/report.pdf')}>" in out, f"autolink ../assets/report.pdf not rewritten: {out!r}"
        # ``../assets/logo.png`` → media (raw URL).
        assert f"<{_raw_url('assets/logo.png')}>" in out, f"autolink ../assets/logo.png not rewritten: {out!r}"
