# -*- coding: utf-8 -*-
import io
import re
import csv
from collections import deque, defaultdict
from typing import Iterable, Any, NamedTuple, Callable, Iterator


__all__ = [
    'flatten',
    'list2grid',
    'list2csv',
]


def flatten(
        a: Any,
        *,
        ignore_keys: Iterable[Any] = None,
        map_none: Callable[[str], Any] = None,
        map_int: Callable[[str, int], Any] = None,
        map_float: Callable[[str, float], Any] = None,
        map_bool: Callable[[str, bool], Any] = None,
        map_others: Callable[[str, Any], Any] = None,
) -> Iterator[tuple[str, Any]]:
    ignore_key_set = set(ignore_keys) if ignore_keys else set()

    if map_none is None:
        map_none = lambda k: None
    if map_int is None:
        map_int = lambda k, v: v
    if map_float is None:
        map_float = lambda k, v: v
    if map_bool is None:
        map_bool = lambda k, v: v
    if map_others is None:
        map_others = lambda k, v: str(v)

    class Item(NamedTuple):
        root: str
        value: Any

    items = deque()
    items.append(Item(root='', value=a))

    while items:
        item = items.popleft()

        root = item.root
        value = item.value

        if root in ignore_key_set:
            continue

        match item.value:
            case None:
                yield root, map_none(root)
            case int(x):
                yield root, map_int(root, x)
            case float(x):
                yield root, map_float(root, x)
            case bool(x):
                yield root, map_bool(root, x)
            case str(x):
                yield root, x
            case bytes(x):
                yield root, x.decode('utf-8')
            case list(x):
                items.extend([
                    Item(root=f'{root}[{i}]' if root else f'[{i}]', value=v)
                    for i, v in enumerate(x)
                ])
            case tuple(x):
                items.extend([
                    Item(root=f'{root}[{i}]' if root else f'[{i}]', value=v)
                    for i, v in enumerate(x)
                ])
            case set(x):
                items.extend([
                    Item(root=f'{root}[{i}]' if root else f'[{i}]', value=v)
                    for i, v in enumerate(x)
                ])
            case dict(x):
                items.extend([
                    Item(root=f'{root}.{k}' if root else f'{k}', value=v)
                    for k, v in x.items()
                ])
            case _:
                yield root, map_others(root, value)


def parse_key(key: str) -> list[str|int]:
    tokens = re.findall(r'\w+|\[.*?]', key.strip())
    result = []

    for token in tokens:
        if token.startswith('[') and token.endswith(']'):
            inner = token[1:-1].strip()

            if len(inner) >= 2 and (
                    (inner[0] == "'" and inner[-1] == "'") or
                    (inner[0] == '"' and inner[-1] == '"')
            ):
                result.append(inner[1:-1])
            else:
                try:
                    result.append(int(inner))
                except (ValueError, TypeError):
                    result.append(inner)
        else:
            result.append(token)

    return result


def list2grid(contents: Iterable[Any], *, ignore_keys: list[str] = None) -> list[list[Any]]:
    grid: dict[str, list[Any]] = defaultdict(list)

    for i, content in enumerate(contents):
        for k, v in flatten(content, ignore_keys=ignore_keys):
            column = grid[k]
            if len(column) < i:
                column.extend([None] * (i - len(column)))
            column.append(v)

    header = list(grid.keys())
    data = [list(row) for row in zip(*grid.values())]

    return [header, *data]


def list2csv(contents: Iterable[Any], *, ignore_keys: list[str] = None) -> str:
    grid = list2grid(contents, ignore_keys=ignore_keys)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerows(grid)

    csv_string = output.getvalue()
    output.close()

    return csv_string


def test():
    report = {
        "time": 1770261549.652793,
        "frame_tick": 1,
        "face_detection": [
            {
                "xyxy": [
                    128.68014526367188,
                    157.75762939453125,
                    283.840087890625,
                    369.04571533203125
                ],
                "score": 0.9950526356697083
            }
        ],
        "face_landmark_5": [
            {
                "landmarks": [
                    163.67152404785156,
                    247.69027709960938,
                    234.9268798828125,
                    244.41014099121094,
                    196.6748046875,
                    287.55096435546875,
                    176.33189392089844,
                    324.64642333984375,
                    231.42239379882812,
                    321.5899963378906
                ]
            }
        ]
    }
    print(list(flatten(report)))
    grid = list2grid([report, report])
    print(grid)

    header = grid[0]
    for name in header:
        print(parse_key(name))


if __name__ == '__main__':
    test()
