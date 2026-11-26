"""Truthful age bands. A cluster gets ONE band that contains every age observed for that patient, so
pooling a patient's records gives an attacker nothing narrower than the band."""
from __future__ import annotations


def band_for(ages: list[int], width: int, top: int) -> tuple[int, int | None]:
    """Return (lo, hi); hi None means 'lo+' (top-coded). Prefers bands aligned on multiples of width."""
    if not ages:
        return (0, None)
    lo_a, hi_a = min(ages), max(ages)
    if hi_a >= top:
        return (min(top, lo_a - lo_a % 5), None)
    w = max(1, width)
    while True:
        lo = (lo_a // w) * w                      # 1. aligned band
        if hi_a <= lo + w - 1:
            return _cap(lo, w, top)
        step = max(1, w // 2)                     # 2. half-step band for ages straddling a boundary
        s = (lo_a // step) * step
        while s >= 0 and s + w - 1 >= hi_a:
            if s <= lo_a:
                return _cap(s, w, top)
            s -= step
        w *= 2                                    # 3. widen


def _cap(lo: int, w: int, top: int) -> tuple[int, int | None]:
    hi = lo + w - 1
    if hi >= top:
        return (lo, None)
    return (lo, hi)


def render(band: tuple[int, int | None]) -> str:
    lo, hi = band
    return f"{lo}+" if hi is None else f"{lo}-{hi}"
