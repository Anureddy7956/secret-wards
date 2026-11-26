"""Date detection, parsing and format-preserving shifting.

Supported: ISO dates and datetimes (with time / zone), d/m/y and m/d/y with / - . separators and
2- or 4-digit years, y/m/d, '5 September', '5 Sep 2026', 'September 5, 2026', Hindi month names.
A shifted date is written back in exactly the input's format (separators, padding, year width,
month-name case and language), so a 9-day stay is still 9 days and the text still reads the same.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
             "november", "december"]
MONTHS_HI = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
MONTH_ALIASES = {}
for i, m in enumerate(MONTHS_EN):
    MONTH_ALIASES[m] = i + 1
    MONTH_ALIASES[m[:3]] = i + 1
MONTH_ALIASES["sept"] = 9
for i, m in enumerate(MONTHS_HI):
    MONTH_ALIASES[m] = i + 1
MONTH_ALIASES.update({"फरवरी": 2, "सितम्बर": 9, "अक्तूबर": 10, "नवम्बर": 11, "दिसम्बर": 12, "अप्रेल": 4})

_MON = "|".join(sorted((re.escape(k) for k in MONTH_ALIASES), key=len, reverse=True))

ISO_RX = re.compile(
    r"(?<![\d])(\d{4})-(\d{2})-(\d{2})"
    r"((?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?(?:Z|[+\-]\d{2}:?\d{2})?)(?![\d])"
)
YMD_RX = re.compile(r"(?<![\d/.\-])(\d{4})([/.])(\d{1,2})\2(\d{1,2})(?![\d/.\-]|\.\d)")
NUM_RX = re.compile(r"(?<![\d/.\-])(\d{1,2})([/.\-])(\d{1,2})\2(\d{4}|\d{2})(?![\d/\-]|\.\d)")
DMON_RX = re.compile(
    r"(?<![\w])(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(" + _MON + r")\.?(?:,?[\s\-]+(\d{4}|'?\d{2}))?(?![\w])", re.I)
MOND_RX = re.compile(r"(?<![\w])(" + _MON + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?![\w])", re.I)


@dataclass
class DateHit:
    start: int
    end: int
    kind: str          # iso | ymd | num | dmon | mond
    groups: tuple
    raw: str
    ambiguous: bool = False   # num dates where both fields <= 12
    order_hint: str | None = None  # 'dmy' / 'mdy' when the numbers decide it

    def parse(self, order: str = "dmy", ref_year: int = 2026) -> dt.date | None:
        try:
            g = self.groups
            if self.kind == "iso":
                return dt.date(int(g[0]), int(g[1]), int(g[2]))
            if self.kind == "ymd":
                return dt.date(int(g[0]), int(g[2]), int(g[3]))
            if self.kind == "num":
                a, b, y = int(g[0]), int(g[2]), _year(g[3])
                if self.order_hint:
                    order = self.order_hint
                d, m = (a, b) if order == "dmy" else (b, a)
                return dt.date(y, m, d)
            if self.kind == "dmon":
                d, m = int(g[0]), MONTH_ALIASES[g[1].lower()]
                y = _year(g[2]) if g[2] else ref_year
                return dt.date(y, m, d)
            if self.kind == "mond":
                m, d, y = MONTH_ALIASES[g[0].lower()], int(g[1]), int(g[2])
                return dt.date(y, m, d)
        except (ValueError, KeyError):
            return None
        return None

    def render(self, new: dt.date, order: str = "dmy") -> str:
        g = self.groups
        if self.kind == "iso":
            return f"{new.year:04d}-{new.month:02d}-{new.day:02d}{g[3]}"
        if self.kind == "ymd":
            sep = g[1]
            return f"{new.year:04d}{sep}{_pad(new.month, g[2])}{sep}{_pad(new.day, g[3])}"
        if self.kind == "num":
            if self.order_hint:
                order = self.order_hint
            sep = g[1]
            first_raw, second_raw = g[0], g[2]
            if order == "dmy":
                a, b = _pad(new.day, first_raw), _pad(new.month, second_raw)
            else:
                a, b = _pad(new.month, first_raw), _pad(new.day, second_raw)
            y = f"{new.year:04d}" if len(g[3]) == 4 else f"{new.year % 100:02d}"
            return f"{a}{sep}{b}{sep}{y}"
        if self.kind == "dmon":
            seg = self.raw
            mon = _render_month(g[1], new.month)
            out = seg.replace(g[1], mon, 1)
            out = re.sub(r"^\d{1,2}", _pad(new.day, g[0]), out, count=1)
            if g[2]:
                yr = g[2]
                new_y = f"{new.year:04d}" if len(yr.strip("'")) == 4 else f"{new.year % 100:02d}"
                if yr.startswith("'"):
                    new_y = "'" + new_y
                out = out[: len(out) - len(yr)] + new_y
            return out
        if self.kind == "mond":
            mon = _render_month(g[0], new.month)
            return self.raw.replace(g[0], mon, 1).replace(g[1], _pad(new.day, g[1]), 1).replace(g[2], f"{new.year:04d}")
        return self.raw


def _year(s: str) -> int:
    s = s.strip("'")
    y = int(s)
    if len(s) == 2:
        y += 2000 if y <= 40 else 1900
    return y


def _pad(v: int, like: str) -> str:
    return f"{v:02d}" if len(like) == 2 else str(v)


def _render_month(raw: str, month: int) -> str:
    if any("\u0900" <= c <= "\u097f" for c in raw):
        return MONTHS_HI[month - 1]
    full = MONTHS_EN[month - 1]
    word = full[:3] if len(raw) <= 4 and raw.lower() not in ("june", "july") else full
    if raw.isupper():
        return word.upper()
    if raw[:1].isupper():
        return word.capitalize()
    return word


def find_dates(text: str) -> list[DateHit]:
    hits: list[DateHit] = []
    taken = []

    def free(s, e):
        return all(e <= a or s >= b for a, b in taken)

    for m in ISO_RX.finditer(text):
        hits.append(DateHit(m.start(), m.end(), "iso", m.groups(), m.group(0)))
        taken.append((m.start(), m.end()))
    for m in YMD_RX.finditer(text):
        if free(m.start(), m.end()):
            hits.append(DateHit(m.start(), m.end(), "ymd", m.groups(), m.group(0)))
            taken.append((m.start(), m.end()))
    for m in NUM_RX.finditer(text):
        if not free(m.start(), m.end()):
            continue
        a, b = int(m.group(1)), int(m.group(3))
        if not (1 <= a <= 31 and 1 <= b <= 31) or (a > 12 and b > 12):
            continue
        # BP-like / fraction-like guards: '120/80' never has a year part, so NUM needs 3 fields.
        hint = "dmy" if a > 12 else ("mdy" if b > 12 else None)
        h = DateHit(m.start(), m.end(), "num", m.groups(), m.group(0), ambiguous=hint is None, order_hint=hint)
        if h.parse("dmy") is None and h.parse("mdy") is None:
            continue
        hits.append(h)
        taken.append((m.start(), m.end()))
    for m in DMON_RX.finditer(text):
        if free(m.start(), m.end()):
            h = DateHit(m.start(), m.end(), "dmon", m.groups(), m.group(0))
            if h.parse() is not None:
                hits.append(h)
                taken.append((m.start(), m.end()))
    for m in MOND_RX.finditer(text):
        if free(m.start(), m.end()):
            h = DateHit(m.start(), m.end(), "mond", m.groups(), m.group(0))
            if h.parse() is not None:
                hits.append(h)
                taken.append((m.start(), m.end()))
    hits.sort(key=lambda h: h.start)
    return hits


def order_votes(text: str) -> tuple[int, int]:
    """(dmy_votes, mdy_votes) from unambiguous numeric dates in text."""
    d = m = 0
    for h in find_dates(text):
        if h.kind == "num" and h.order_hint == "dmy":
            d += 1
        elif h.kind == "num" and h.order_hint == "mdy":
            m += 1
    return d, m


def shift_text_dates(text: str, shift_days: int, order: str, ref_year: int = 2026,
                     transform=None) -> tuple[str, int]:
    """Shift every date in text by shift_days, keeping each date's format. Returns (text, n_shifted).
    `transform(hit, date) -> str | None` may override rendering (e.g. DOB handling)."""
    hits = find_dates(text)
    if not hits:
        return text, 0
    out, last, n = [], 0, 0
    for h in hits:
        d = h.parse(order, ref_year)
        if d is None:
            continue
        rep = None
        if transform is not None:
            rep = transform(h, d)
        if rep is None:
            rep = h.render(d + dt.timedelta(days=shift_days), order)
        out.append(text[last:h.start])
        out.append(rep)
        last = h.end
        n += 1
    out.append(text[last:])
    return "".join(out), n
