"""Allow-list logger: only pre-approved templates with numeric / hash arguments.

Nothing derived from record content can reach stdout, stderr or a log file through this module:
every argument must be an int, a float, or a short lowercase hex digest / identifier token from
a fixed vocabulary (stage names, exception class names, entity type names).
"""
from __future__ import annotations

import re
import sys

TEMPLATES = {
    "start": "raksha: run started",
    "stage": "raksha: stage {stage} done in {seconds}s",
    "summary": "raksha: files {files} sanitized {sanitized} quarantined {quarantined} records {records} linked {linked}",
    "file_error": "raksha: file {sha} failed in {stage} with {exc}; quarantined",
    "fatal": "raksha: fatal {exc} in {stage}; aborting",
    "no_secret": "raksha: RAKSHA_SECRET is not set; refusing to run",
    "entities": "raksha: entity {etype} count {count}",
}

_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")
_HEX = re.compile(r"^[0-9a-f]{6,64}$")


def _safe(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return v
    s = str(v)
    if _HEX.match(s):
        return s
    # Only identifiers that look like code tokens (stage / class / type names) are allowed,
    # and only from ASCII. Anything else is dropped.
    if _TOKEN.match(s) and s.upper() == s or s in _ALLOWED_WORDS or s.endswith(("Error", "Exception", "Warning")):
        return s
    return "?"


_ALLOWED_WORDS = {"ingest", "parse", "detect", "link", "privacy", "write", "report", "main", "fhir", "csv",
                  "json", "text", "learn"}


def log(key: str, **kwargs) -> None:
    tpl = TEMPLATES.get(key)
    if tpl is None:
        return
    safe = {k: _safe(v) for k, v in kwargs.items()}
    try:
        msg = tpl.format(**safe)
    except (KeyError, IndexError):
        msg = tpl
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
