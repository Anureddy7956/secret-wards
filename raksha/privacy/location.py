"""Location generalisation: village/house/locality removed; district kept or lifted to state."""
from __future__ import annotations

from ..detect.lexicon import get_lexicon

LEVELS = ["village", "tehsil", "district", "state"]


def district_key(raw: str) -> str:
    return " ".join(raw.lower().replace("distt.", "").replace("district", "").split())


def generalize_district(raw: str, level: str) -> str:
    lex = get_lexicon()
    key = district_key(raw)
    if level in ("village", "tehsil", "district"):
        return raw
    state = lex.district_state.get(key) or lex.district_state.get(key.replace(" ", ""))
    return state if state else "[DISTRICT]"


def pin_out(pin: str, level: str, policy) -> str:
    digits = int((policy.get("location.pin_digits", {}) or {}).get(level, 0))
    d = "".join(c for c in str(pin) if c.isdigit())
    if digits <= 0 or len(d) != 6:
        return "[PIN]"
    return d[:digits] + "X" * (6 - digits)
