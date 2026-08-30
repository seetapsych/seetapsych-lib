# -*- coding: utf-8 -*-

import os
import re
from typing import Any
from urllib.parse import unquote

if not os.environ.get("LANG"):
    os.environ["LANG"] = "en_US.UTF-8"

import jsonschema2md

__all__ = [
    "schema2markdown",
    "sanitize_markdown_links",
]


_COMPACT_LONG_LIST_THRESHOLD = 16


def _compact_truncate_list(lst: list[Any]) -> str | list[Any]:
    if len(lst) <= _COMPACT_LONG_LIST_THRESHOLD:
        return lst
    return f"[{lst[0]!r}] * {len(lst)}"


def _compact_process_value(value: Any, in_examples: bool = False) -> Any:
    if isinstance(value, dict):
        return {k: _compact_process_value(v, in_examples or (k == "examples")) for k, v in value.items()}
    if isinstance(value, list):
        if in_examples:
            truncated = _compact_truncate_list(value)
            if isinstance(truncated, str):
                return truncated
            return [_compact_process_value(v, in_examples) for v in truncated]
        return [_compact_process_value(v, in_examples) for v in value]
    return value


def _compact_examples(schema: dict[str, Any]) -> dict[str, Any]:
    result = _compact_process_value(schema, in_examples=False)
    assert isinstance(result, dict)
    return result


def _sanitize_id(s: str) -> str:
    s = unquote(s)
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def sanitize_markdown_links(text: str) -> str:
    text = re.sub(r"\[#/\$defs/([^\]]+)\]", r"[\1]", text)

    def link_replacer(m: re.Match[str]) -> str:
        display = m.group(1)
        orig_fragment = m.group(2)
        clean = _sanitize_id(orig_fragment)
        if clean == orig_fragment:
            return m.group(0)
        return f"[{display}](#{clean})"

    text = re.sub(r"\[([^\]]+)\]\(#([^)]+)\)", link_replacer, text)

    link_targets: set[str] = set()
    for m in re.finditer(r"\[[^\]]*\]\(#([^)]+)\)", text):
        link_targets.add(m.group(1))

    added_clean_ids: set[str] = set()

    def anchor_replacer(m: re.Match[str]) -> str:
        orig_id = m.group(1)
        clean_id = _sanitize_id(orig_id)
        clean_is_target = clean_id in link_targets
        if not clean_is_target:
            return m.group(0)
        if clean_id == orig_id:
            return m.group(0)
        if clean_id in added_clean_ids:
            return ""
        added_clean_ids.add(clean_id)
        return f'<a id="{clean_id}"></a>'

    text = re.sub(r'<a id="([^"]+)"></a>', anchor_replacer, text)

    return text


def schema2markdown(
    schema: dict[str, Any],
    *,
    compact: bool = True,
    sanitize_links: bool = True,
) -> str:
    parser = jsonschema2md.Parser()

    processed = _compact_examples(schema) if compact else schema
    md = "".join(parser.parse_schema(processed, fail_on_error_in_defs=False))
    if sanitize_links:
        md = sanitize_markdown_links(md)
    return md


def main():
    pass


if __name__ == "__main__":
    main()
