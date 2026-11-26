"""Content sniffing: decides how a file is parsed (never trusts the extension alone)."""
from __future__ import annotations

import json
import sys

from ..security.quarantine import Quarantine
from .encodings import decode, looks_binary

MAGIC = (b"%PDF", b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"PK\x03\x04", b"%!PS", b"\x1f\x8b", b"BM", b"II*\x00",
         b"MM\x00*", b"\xd0\xcf\x11\xe0", b"Rar!", b"7z\xbc\xaf")
TEXT_EXT = {".txt", ".text", ".log", ".md", ".note", ".notes", ""}
CSV_EXT = {".csv", ".tsv", ".psv", ".tab"}
JSON_EXT = {".json"}


def max_depth(obj, limit: int) -> int:
    """Iterative depth measurement (no recursion)."""
    stack = [(obj, 1)]
    deepest = 0
    while stack:
        cur, d = stack.pop()
        deepest = max(deepest, d)
        if deepest > limit:
            return deepest
        if isinstance(cur, dict):
            stack.extend((v, d + 1) for v in cur.values())
        elif isinstance(cur, list):
            stack.extend((v, d + 1) for v in cur)
    return deepest


def sniff(raw: bytes, ext: str, max_json_depth: int = 200):
    """Return (fmt, text, encoding, parsed) where fmt in csv|json|fhir|text. Raises Quarantine."""
    if not raw.strip():
        raise Quarantine("empty_file")
    if raw.startswith(MAGIC):
        raise Quarantine("unsupported_format")
    text, enc = decode(raw)
    if text is None:
        raise Quarantine("undecodable_text")
    if looks_binary(text):
        raise Quarantine("binary_content")
    stripped = text.lstrip("﻿ \t\r\n")
    if stripped.startswith("<"):
        raise Quarantine("unsupported_format")  # XML / HTML / CDA
    if stripped[:1] in ("{", "["):
        old = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(max(old, max_json_depth * 3 + 200))
            parsed = json.loads(stripped)
        except RecursionError:
            raise Quarantine("nesting_too_deep")
        except ValueError:
            parsed = None
            if ext in JSON_EXT or ext not in CSV_EXT | TEXT_EXT or (stripped[:1] == "{" and stripped.rstrip()[-1:] != "}"
                                                                   and ext in CSV_EXT):
                raise Quarantine("malformed_json")
        finally:
            sys.setrecursionlimit(old)
        if parsed is None:
            return ("csv" if ext in CSV_EXT else "text"), text, enc, None
        if max_depth(parsed, max_json_depth) > max_json_depth:
            raise Quarantine("nesting_too_deep")
        if isinstance(parsed, dict) and parsed.get("resourceType") == "Bundle":
            return "fhir", stripped, enc, parsed
        return "json", stripped, enc, parsed
    if ext in JSON_EXT:
        raise Quarantine("malformed_json")
    if ext in CSV_EXT:
        return "csv", text, enc, None
    if ext in TEXT_EXT:
        return "text", text, enc, None
    raise Quarantine("unsupported_format")
