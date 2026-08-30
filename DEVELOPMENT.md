# Development Guide

## Local Verification (Before Creating a Release Tag)

Run these commands from the repository root. Make sure you have [`uv`](https://github.com/astral-sh/uv) installed.

```bash
# Per-project: set PACKAGE to the top-level importable package directory
PACKAGE=seetapsych_lib
#   For any seetapsych-* project, auto-detect instead:
#   PACKAGE="$(ls -d seetapsych_* 2>/dev/null | head -n1)"

# 1. Sync dependencies (installs the package + dev tools)
uv sync --group dev

# 2. Lint (ruff) (use `ruff check . --fix` to fix)
uv run ruff check .

# 3. Format check (ruff format -- non-destructive; use `ruff format` to apply)
uv run ruff format --check .

# 4. Static type check (mypy, strict mode)
uv run mypy "$PACKAGE"

# 5. Security scan (bandit)
uv run bandit -r "$PACKAGE" -c pyproject.toml

# 6. Unit tests (pytest)
uv run pytest

# 7. Build the distribution packages + verify metadata
uv run python -m build
uv run twine check dist/*
```

If all seven steps pass, the code is ready to be tagged for release.

## Tag Naming and Release Pipeline

Tag format is managed by [`hatch-vcs`](https://github.com/ofek/hatch-vcs) with the following pattern in `pyproject.toml`:

```
tag-pattern = "^r(?P<version>[^-]+)$"
```

This separates tags into two classes that drive the GitHub Actions pipeline in `.github/workflows/publish.yml`:

### Class A — Official Release: `r<version>` (no `-`)

**Format**: `r` + a version string that contains **no hyphen** `-`.

Examples:
- `r0.1.0`
- `r2026.08.30`
- `r1.0.0.post1`

Pipeline behavior:
1. CI runs (lint + test + build).
2. `github-release` job builds sdist + wheel, **creates a GitHub Release** (`prerelease: false`), attaches both assets, and links to the PyPI version page.
3. `pypi-publish` job runs (`if: no '-' in tag`) and uploads the same sdist + wheel to PyPI via Trusted Publisher (OIDC, no API token required).

### Class B — Temporary / Pre-release: `r<version>-<suffix>`

**Format**: `r` + anything + **at least one hyphen** `-` + anything.

Examples:
- `r0.2.0-alpha`
- `r0.2.0-rc1`
- `r2026.08.30-tmp-hotfix-42`
- `r1.0.0-just-testing-release-flow`

Pipeline behavior:
1. CI still runs (same lint + test + build gates — everything must still pass).
2. `github-release` job builds sdist + wheel, creates a GitHub Release **marked as `prerelease: true`**, attaches both assets, and the release body clearly states "not published to PyPI".
3. `pypi-publish` job is **skipped** (`if:` condition fails because the tag contains `-`). Nothing is uploaded to PyPI.

### Quick Tagging Recipe

```bash
# --- official release (PyPI + GitHub Release) ---
git tag r0.1.0
git push origin r0.1.0

# --- temp / pre-release (GitHub Release only, PyPI skipped) ---
git tag r0.1.0-alpha
git push origin r0.1.0-alpha
```

### Why the two classes?

Use Class B tags whenever you want to:
- exercise the full build + release-creation pipeline end-to-end without polluting PyPI,
- ship a throwaway build for QA or a staging consumer that can pull GitHub Release assets directly,
- share candidate wheels for a hotfix before cutting the final tag.

When the candidate is validated, re-tag without the suffix (e.g., `r0.1.0`) and push — the same CI gates run again, followed by the official PyPI publish.
