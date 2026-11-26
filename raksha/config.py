"""Policy loading. All privacy knobs come from config/policy.yaml."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "data"


def _deep_get(d: dict, dotted: str, default=None):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


class Policy:
    def __init__(self, data: dict):
        self.data = data or {}

    def get(self, dotted: str, default=None):
        return _deep_get(self.data, dotted, default)


def load_policy(path: str | os.PathLike | None = None) -> Policy:
    p = Path(path) if path else Path(os.environ.get("RAKSHAK_POLICY", ROOT / "config" / "policy.yaml"))
    if not p.is_absolute():
        p = ROOT / p
    try:
        import yaml  # type: ignore
        with open(p, encoding="utf-8") as fh:
            return Policy(yaml.safe_load(fh))
    except FileNotFoundError:
        return Policy({})
