"""JSON record enumeration: a list of patient-bearing objects becomes /key/N records; otherwise 'doc'."""
from __future__ import annotations


def pointer_escape(k: str) -> str:
    return str(k).replace("~", "~0").replace("/", "~1")


def iter_leaves(obj, path=()):
    """Iterative walk yielding (path_tuple, value) for scalar leaves (no recursion)."""
    stack = [(obj, path)]
    out = []
    while stack:
        cur, p = stack.pop()
        if isinstance(cur, dict):
            for k in reversed(list(cur.keys())):
                stack.append((cur[k], p + (k,)))
        elif isinstance(cur, list):
            for i in range(len(cur) - 1, -1, -1):
                stack.append((cur[i], p + (i,)))
        else:
            out.append((p, cur))
    return out


def iter_keys(obj, path=()):
    """(path_of_dict, key) for every dict key."""
    stack = [(obj, path)]
    out = []
    while stack:
        cur, p = stack.pop()
        if isinstance(cur, dict):
            for k in cur:
                out.append((p, k))
            for k in reversed(list(cur.keys())):
                stack.append((cur[k], p + (k,)))
        elif isinstance(cur, list):
            for i in range(len(cur) - 1, -1, -1):
                stack.append((cur[i], p + (i,)))
    return out


def pattern_of(path) -> tuple:
    return tuple("[]" if isinstance(p, int) else p for p in path)
