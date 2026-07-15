"""JSON + Power BI column-key helpers."""

import json
from collections import defaultdict
from typing import Any


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def clean_col_key(key: str) -> str:
    """Normalize a Power BI result column key to a bare field name.

    'Product'[Category]  -> Category
    Product[Category]    -> Category
    [Total Sales]        -> Total Sales
    Category             -> Category
    """
    if key is None:
        return key
    if "[" in key:
        key = key[key.rfind("[") + 1:]
    return key.replace("]", "").strip()


def clean_rows(rows: list) -> list:
    """Normalize result keys without losing same-named cross-table columns.

    Power BI can return both ``Orders[Name]`` and ``Customers[Name]`` in one
    row. Flattening both to ``Name`` silently overwrites one value, so bare
    names are used only when unique across the result table. Colliding names
    retain their original table-qualified keys consistently on every row.
    """
    source_rows = list(rows or [])
    variants = defaultdict(set)
    for row in source_rows:
        for key in row:
            variants[clean_col_key(key)].add(str(key).strip())
    colliding_names = {bare for bare, keys in variants.items() if len(keys) > 1}

    cleaned = []
    for row in source_rows:
        bare_names = {key: clean_col_key(key) for key in row}
        out = {}
        for key, value in row.items():
            bare = bare_names[key]
            normalized = str(key).strip() if bare in colliding_names else bare
            # Identical JSON object keys cannot coexist, but two differently
            # formatted source keys could still normalize to the same string.
            # Keep both rather than silently replacing the first.
            if normalized in out:
                base = normalized
                suffix = 2
                while normalized in out:
                    normalized = f"{base} #{suffix}"
                    suffix += 1
            out[normalized] = value
        cleaned.append(out)
    return cleaned
