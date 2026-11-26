"""Field comparisons for linkage (names across scripts / spellings, ages, DOBs, relatives)."""
from __future__ import annotations

from ..detect.lexicon import get_lexicon
from ..translit.canonical import token_match


def _core(name: tuple) -> tuple:
    lex = get_lexicon()
    c = tuple(t for t in name if t not in lex.generic)
    return c or name


def first_token(name: tuple) -> str:
    c = _core(name)
    return c[0] if c else ""


def full_name_agree(a: tuple, b: tuple, jw: float = 0.9) -> bool:
    """Every token of the shorter (>= 2 tokens) name matches a distinct token of the longer, order-free."""
    ca, cb = _core(a), _core(b)
    if len(ca) >= 2 and len(cb) >= 2:
        a, b = ca, cb
    elif len(a) < 2 or len(b) < 2:
        return False  # a single name token is never a full-name agreement
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    used = set()
    for t in short:
        hit = None
        for i, u in enumerate(long_):
            if i not in used and token_match(t, u, jw):
                hit = i
                break
        if hit is None:
            return False
        used.add(hit)
    return True


def first_agree(a: tuple, b: tuple, jw: float = 0.9) -> bool:
    fa, fb = first_token(a), first_token(b)
    return bool(fa and fb and len(fa) > 1 and len(fb) > 1 and token_match(fa, fb, jw))


def surname_agree(a: tuple, b: tuple, jw: float = 0.9) -> bool:
    ca, cb = _core(a), _core(b)
    return len(ca) >= 2 and len(cb) >= 2 and token_match(ca[-1], cb[-1], jw)


def names_compatible(a_names: list, b_names: list, jw: float = 0.9) -> bool:
    """Could these name sets belong to one person? (used to veto merges, e.g. two spouses sharing a phone)."""
    if not a_names or not b_names:
        return True
    for a in a_names:
        for b in b_names:
            ca, cb = _core(a), _core(b)
            if any(token_match(ca[0], t, jw) for t in cb) or any(token_match(cb[0], t, jw) for t in ca):
                return True
    return False


def any_name_pair(a_names, b_names, pred, jw=0.9) -> bool:
    return any(pred(a, b, jw) for a in a_names for b in b_names)


def relative_agree(a_rel: list, b_rel: list, jw: float = 0.9) -> bool:
    for a in a_rel:
        for b in b_rel:
            if first_agree(a, b, jw):
                return True
    return False


def years_compatible(a: list, b: list, gap: int) -> bool | None:
    """None when unknown; else whether some birth-year estimates are within gap."""
    if not a or not b:
        return None
    return min(abs(x - y) for x in a for y in b) <= gap


def dob_compatible(a: set, b: set) -> bool | None:
    if not a or not b:
        return None
    for x in a:
        for y in b:
            if x == y:
                return True
            # day/month swapped by an ambiguous export
            if x.year == y.year and x.month == y.day and x.day == y.month:
                return True
    return False
