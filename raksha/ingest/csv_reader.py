"""Robust CSV/TSV parsing: delimiter sniffing, quoted newlines, ragged rows, duplicate headers."""
from __future__ import annotations

import csv
import io


def sniff_delimiter(text: str, ext: str) -> str:
    if ext == ".tsv" or ext == ".tab":
        return "\t"
    if ext == ".psv":
        return "|"
    head = "\n".join(text.splitlines()[:20])
    counts = {d: head.count(d) for d in (",", "\t", ";", "|")}
    best = max(counts, key=lambda d: (counts[d], d == ","))
    return best if counts[best] > 0 else ","


def detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text[:5000] else "\n"


def read_csv(text: str, delimiter: str) -> list[list[str]]:
    csv.field_size_limit(10 * 1024 * 1024)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return [row for row in reader]
