"""Truthful age bands. A cluster gets ONE band that contains every age observed for that patient, so
pooling a patient's records gives an attacker nothing narrower than the band."""
from __future__ import annotations


def band_for(ages: list[int], width: int, top: int) -> tuple[int, int | None]:
    """Return (lo, hi) with hi None meaning 'lo+'. Bands start on multiples of width/2."""
    if not ages:
        return (0, None)
    lo_a, hi_a = min(ages), max(ages)
    if hi_a >= top:
        return (min(top, lo_a - lo_a % 5) if lo_a < top else top, None)
    step = max(1, width // 2)
    w = width
    while True:
        start = (hi_a - w + 1)
        start = ((start + step - 1) // step) * step if start > 0 else 0
        candidates = []
        s = start
        while s <= lo_a:
            if s <= lo_a and hi_a <= s + w - 1:
                candidates.append(s)
            s += step
        aligned = [c for c in candidates if c % w == 0]
        if aligned:
            best = aligned[0]
            if best + w - 1 >= top:
                return (best, None) if best >= top else (best, best + w - 1)
            return (best, best + w - 1)
        if candidates:
            # straddles an aligned boundary: use the half-step band closest to the observed ages
            mid = (lo_a + hi_a) / 2
            best = min(candidates, key=lambda c: (abs(c + (w - 1) / 2 - mid), c))
            if best + w - 1 >= top:
                return (best, None) if best >= top else (best, best + w - 1)
            return (best, best + w - 1)
        w *= 2


def render(band: tuple[int, int | None]) -> str:
    lo, hi = band
    return f"{lo}+" if hi is None else f"{lo}-{hi}"
