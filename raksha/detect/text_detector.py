"""Free-text PII detection: patterns + labels + relation markers + honorifics + gazetteer/shape + propagation,
vetoed by the medical guard, merged into non-overlapping spans."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..privacy.dates import find_dates
from ..translit.canonical import canon_token, token_match
from . import context_rules as CR
from . import names as N
from .combine import LOCATION_TYPES, NAME_TYPES, Span, merge_adjacent_names, resolve
from .lexicon import get_lexicon
from .medical_guard import find_guards, inside, overlaps
from .patterns import (AADHAAR_RX, ABHA_RX, find_direct_ids, find_id_candidates, id_shape, norm_id, digits,
                       PAN_RX, EMAIL_RX)

AGE_SLASH_RX = re.compile(r"(?<![\d/.])(\d{1,3})\s*(?:Y|Yr|Yrs|Years?|yrs?|years?|वर्ष|साल)?\.?\s*/\s*"
                          r"(M|F|Male|Female|male|female|पुरुष|महिला)(?![A-Za-z])")
AGE_WORD_RX = re.compile(r"(?<![\d/.x×])(\d{1,3})\s*(?:yrs?|years?|Y|Yrs|वर्ष)\b\.?\s*(?:old\s*)?[,/]?\s*"
                         r"(male|female|M|F|पुरुष|महिला)\b", re.I)
AGE_AGED_RX = re.compile(r"\b(?:aged|age)\s+(\d{1,3})\b", re.I)
AGE_VALUE_RX = re.compile(r"(\d{1,3})(?:\s*(?:Y|Yr|Yrs|Years?|yrs?|years?|वर्ष|साल)\b\.?)?")


@dataclass
class Learned:
    """Dataset-level knowledge collected in the learning pass (no PII leaves memory)."""
    id_shapes: set = field(default_factory=set)        # shapes of identifiers seen in ID-labelled fields
    id_values: set = field(default_factory=set)        # normalised identifier values
    id_digit_cores: set = field(default_factory=set)   # digit cores (>= 5 digits) of known identifiers


@dataclass
class Context:
    learned: Learned
    known_names: list = field(default_factory=list)    # [(canon tokens tuple, role)]
    field_type: str | None = None                      # column / key class if this text is a field value


def _add(spans, s, e, etype, conf, role="patient", value="", **meta):
    if e > s:
        spans.append(Span(s, e, etype, conf, value, role, meta))


def _label_value_end(text: str, pos: int) -> int:
    """End of a label's value: line end, double space or next 'Label:' pattern."""
    nl = text.find("\n", pos)
    end = len(text) if nl < 0 else nl
    m = re.search(r"\s{2,}|\t", text[pos:end])
    if m and m.start() > 0:
        end = pos + m.start()
    return end


def detect(text: str, ctx: Context) -> list[Span]:
    if not text or not text.strip():
        return []
    lex = get_lexicon()
    guards = find_guards(text)
    spans: list[Span] = []

    # 1. direct identifier patterns ------------------------------------------------------------
    for s, e, typ, val, conf in find_direct_ids(text):
        if inside(guards, s, e, {"dose", "vital", "freq", "icd"}) and conf < 0.95:
            continue
        _add(spans, s, e, typ, conf, value=val)

    # 2. alphanumeric identifiers: learned shapes / known values -------------------------------
    for s, e, raw in find_id_candidates(text):
        nid = norm_id(raw)
        if nid in ctx.learned.id_values or id_shape(raw) in ctx.learned.id_shapes:
            if not inside(guards, s, e, {"icd"}):
                _add(spans, s, e, "MRN", 0.85, value=nid)
    for m in re.finditer(r"(?<![\d])\d{5,}(?![\d])", text):
        if m.group(0) in ctx.learned.id_digit_cores:
            _add(spans, m.start(), m.end(), "MRN", 0.8, value=m.group(0))

    # 3. labels --------------------------------------------------------------------------------
    for rx, etype, role, mode, conf in CR.LABELS:
        for m in rx.finditer(text):
            if overlaps(guards, m.start(), m.end(), {"doctor"}):
                continue
            if etype == "PATIENT_NAME" and _REL_BEFORE_RX.search(text[max(0, m.start() - 25):m.start()]):
                continue  # 'पिता का नाम:' / "Father's Name:" is a relative label
            _apply_label(text, m.end(), etype, role, mode, conf, spans, guards, ctx)

    # 4. relation markers ------------------------------------------------------------------------
    for m in CR.RELATION_RX.finditer(text):
        marker = (m.group(1) or m.group(0)).strip().lower().replace(".", "/").rstrip("/")
        if inside(guards, m.start(), m.end(), {"complaint"}) or overlaps(guards, m.start(), m.end() + 1, {"complaint"}):
            continue
        g = N.grab_forward(text, m.end(), strict=True)
        if g and not overlaps(guards, g[0], g[1], {"doctor", "org", "eponym"}):
            _add(spans, g[0], g[1], "RELATIVE_NAME", 0.9, "relative", text[g[0]:g[1]], src="relation")
        # the person BEFORE "S/o / W/o / D/o" is the patient ("Asha, W/o Kamal")
        if marker in ("s/o", "d/o", "w/o", "son of", "daughter of", "wife of"):
            b = N.grab_backward(text, m.start())
            if b and not overlaps(guards, b[0], b[1]):
                before = text[max(0, b[0] - 25):b[0]]
                if not re.search(r"(?i)(attendant|relative|guardian)\W*$", before):
                    _add(spans, b[0], b[1], "PATIENT_NAME", 0.8, "patient", text[b[0]:b[1]], src="relation_before")

    # 5. honorifics ----------------------------------------------------------------------------
    for m in CR.HONORIFIC_SUFFIX_RX.finditer(text):
        word = m.group(1).lower()
        b = N.grab_backward(text, m.start(), max_tokens=2)
        if not b or overlaps(guards, b[0], b[1], {"doctor", "org"}):
            continue
        name = text[b[0]:b[1]]
        # lowercase names are accepted only when they are in the gazetteer
        if not N.is_cap(name.split()[0]) and not N.is_gaz(name.split()[0]):
            continue
        if text[m.start() - 1: m.start()] not in (" ",):
            continue
        rest = text[m.end(): m.end() + 2]
        role = "relative" if word in CR.KINSHIP and rest.startswith(":") else "patient"
        _add(spans, b[0], m.end(), "PATIENT_NAME" if role == "patient" else "RELATIVE_NAME", 0.85, role, name,
             src="honorific", gender=CR.GENDER_BY_HONORIFIC.get(word))
    for m in CR.HONORIFIC_SUFFIX_DEVA_RX.finditer(text):
        b = N.grab_backward(text, m.start(), max_tokens=2)
        if b:
            _add(spans, b[0], m.end(), "PATIENT_NAME", 0.85, "patient", text[b[0]:b[1]], src="honorific")
    for m in CR.HONORIFIC_PREFIX_RX.finditer(text):
        g = N.grab_forward(text, m.end(), strict=False)
        if g and not overlaps(guards, g[0], g[1], {"doctor", "org"}):
            word = (m.group(1) or "").lower()
            _add(spans, m.start(), g[1], "PATIENT_NAME", 0.85, "patient", text[g[0]:g[1]], src="honorific",
                 gender=CR.GENDER_BY_HONORIFIC.get(word))

    # 6. address components outside labelled address lines ------------------------------------
    for rx, etype in ((CR.HOUSE_RX, "HOUSE"), (CR.LANDMARK_RX, "LANDMARK"), (CR.VILLAGE_RX, "VILLAGE"),
                      (CR.TEHSIL_RX, "TEHSIL"), (CR.DISTRICT_RX, "DISTRICT")):
        for m in rx.finditer(text):
            if overlaps(guards, m.start(), m.end(), {"ward", "doctor", "dose", "vital", "org"}):
                continue
            s, e = m.start(), _trim_place(text, m.start(), m.end())
            _add(spans, s, e, etype, 0.75, value=text[s:e])
    for m in CR.LOCALITY_RX.finditer(text):
        if overlaps(guards, m.start(), m.end(), {"ward", "doctor"}):
            continue
        frag = m.group(0)
        if frag.lower().startswith("ward") and not _address_context(text, m.start()):
            continue
        _add(spans, m.start(), _trim_place(text, m.start(), m.end()), "LOCALITY", 0.75, value=frag)

    # 6b. bare district names (hospital headers, referrals): generalised with the location level
    for m in _district_rx().finditer(text):
        w = m.group(0)
        if w[:1].isupper() or N.is_deva(w):
            _add(spans, m.start(), m.end(), "DISTRICT", 0.6, value=w, src="gazetteer")

    # 7. gazetteer + shape names ----------------------------------------------------------------
    spans.extend(_scan_names(text, guards))

    # 8. ages (for banding, not removal) -------------------------------------------------------
    for rx in (AGE_SLASH_RX, AGE_WORD_RX, AGE_AGED_RX):
        for m in rx.finditer(text):
            if inside(guards, m.start(1), m.end(1), {"dose", "freq"}):
                continue
            age = int(m.group(1))
            if age <= 120:
                _add(spans, m.start(1), m.end(1), "AGE", 0.8, value=str(age))

    # 9. propagation of known / detected name tokens -------------------------------------------
    spans = _propagate(text, spans, guards, ctx)

    out = resolve(spans)
    out = merge_adjacent_names(text, out)
    for sp in out:
        if sp.etype in NAME_TYPES:
            m = re.search(r"(?:\b(?:Mohd|Md|Mohammad|Mohammed|Muhammad)\.?\s|मोहम्मद\s|मो\.\s?)$", text[max(0, sp.start - 12):sp.start])
            if m:
                sp.start -= len(m.group(0))
    return out


_REL_BEFORE_RX = re.compile(r"(?:पिता|पति|माता|अभिभावक|पिता/पति)\s*का\s*$|(?i:(?:father|husband|mother|guardian|"
                            r"spouse|relative|attendant)(?:'s)?\s*$|(?:pita|pati|mata)\s*ka\s*$)")


_DRX = None


def _district_rx():
    global _DRX
    if _DRX is None:
        lex = get_lexicon()
        names = sorted(set(lex.district_state) | set(lex.deva_district), key=len, reverse=True)
        alts = []
        for n in names:
            if any("\u0900" <= c <= "\u097f" for c in n):
                alts.append(re.escape(n))
            else:
                alts.append(r"\s+".join(re.escape(x) for x in n.split()))
        _DRX = re.compile(r"(?<![\w\u0900-\u097F])(?:" + "|".join(alts) + r")(?![\w\u0900-\u097F])", re.I)
    return _DRX


def _address_context(text: str, pos: int) -> bool:
    before = text[max(0, pos - 60):pos]
    return bool(re.search(r"(?i)(H\.?\s?No|House|Makan|Mohalla|Address|C/O|near|Vill|Gram|मकान|पता)", before))


def _trim_place(text: str, s: int, e: int) -> int:
    """Stop a place phrase at a comma / ' - ' / digits / the next keyword."""
    seg = text[s:e]
    m = re.search(r",|\s-\s|\s–\s|\s(?:Tehsil|Distt|District|Vill|Gram|near|opp|Teh)\b|\s(?:तहसील|जिला|ग्राम)", seg[1:])
    if m:
        e = s + 1 + m.start()
    return e


def _apply_label(text, pos, etype, role, mode, conf, spans, guards, ctx):
    lex = get_lexicon()
    if mode in ("name", "name_weak"):
        g = N.grab_forward(text, pos, strict=(mode == "name"), allow_lower=True)
        if not g:
            return
        if overlaps(guards, g[0], g[1], {"doctor", "org"}):
            return
        frag = text[g[0]:g[1]]
        if mode == "name_weak":
            toks = frag.split()
            if not all(N.is_cap(t) for t in toks):
                return
        if etype == "PATIENT_NAME" and frag.split()[0].rstrip(".").lower() in ("dr", "doctor"):
            return
        _add(spans, g[0], g[1], etype, conf, role, frag, src="label")
    elif mode == "id":
        m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9/\-]*[0-9][A-Za-z0-9/\-]*)", text[pos:])
        if m:
            s, e = pos + m.start(1), pos + m.end(1)
            raw = m.group(1).rstrip("-/")
            _add(spans, s, s + len(raw), "MRN", conf, value=norm_id(raw), src="label")
    elif mode == "phone":
        m = re.match(r"\s*(\+?\d[\d \-.()]{6,17}\d)", text[pos:])
        if m and len(digits(m.group(1))) >= 8:
            _add(spans, pos + m.start(1), pos + m.end(1), "PHONE", conf, value=digits(m.group(1))[-10:], src="label")
    elif mode == "aadhaar":
        m = re.match(r"\s*([\dXx*][\dXx* \-]{10,16}[\dXx*])", text[pos:])
        if m and len(re.sub(r"[^\dXx*]", "", m.group(1))) == 12:
            typ = "AADHAAR_MASKED" if re.search(r"[Xx*]", m.group(1)) else "AADHAAR"
            _add(spans, pos + m.start(1), pos + m.end(1), typ, conf, value=digits(m.group(1)), src="label")
    elif mode == "pin":
        m = re.match(r"\s*([1-9]\d{2}\s?\d{3})(?!\d)", text[pos:])
        if m:
            _add(spans, pos + m.start(1), pos + m.end(1), "PIN", conf, value=digits(m.group(1)), src="label")
    elif mode == "token":
        m = re.match(r"\s*([^\s,;|]+)", text[pos:])
        if m and any(c.isdigit() for c in m.group(1)) or (m and "@" in m.group(1)):
            _add(spans, pos + m.start(1), pos + m.end(1), etype, conf, value=norm_id(m.group(1)), src="label")
    elif mode == "dob":
        for h in find_dates(text[pos:pos + 40]):
            if h.start <= 3:
                _add(spans, pos + h.start, pos + h.end, "DOB", conf, value=h.raw, src="label")
            break
    elif mode == "age":
        m = AGE_VALUE_RX.match(text, pos)
        if m and m.group(1):
            _add(spans, m.start(1), m.end(1), "AGE", conf, value=m.group(1), src="label")
    elif mode == "address":
        end = _label_value_end(text, pos)
        if end > pos:
            seg = text[pos:end]
            info = parse_address(seg)
            _add(spans, pos, end, "ADDRESS", conf, value=seg, src="label", **info)
            # relatives named inside the address ('C/O Naresh Chauhan, H.No. ...') still count as relatives
            for rm in CR.RELATION_RX.finditer(seg):
                g = N.grab_forward(seg, rm.end(), strict=True)
                if g:
                    _add(spans, pos + g[0], pos + g[1], "RELATIVE_NAME", 0.5, "relative", seg[g[0]:g[1]],
                         src="address_relation")
    elif mode == "village":
        end = _label_value_end(text, pos)
        frag = text[pos:end]
        m2 = re.search(r",|;|\s{2,}", frag)
        if m2:
            end = pos + m2.start()
        if end > pos:
            _add(spans, pos, end, "VILLAGE", conf, value=text[pos:end].strip(), src="label")


def parse_address(seg: str) -> dict:
    """Pull the generalisable parts out of an address: village, tehsil, district, pin (for identity + k-anon)."""
    from ..translit.devanagari import transliterate
    lex = get_lexicon()
    info = {}
    m = CR.VILLAGE_RX.search(seg)
    if m:
        v = re.sub(r"^(?:Vill(?:age)?|Gram|Gaon|Grm|ग्राम|गांव|गाँव)\.?\s*[:\-]?\s*", "", m.group(0), flags=re.I)
        info["village"] = v.split(",")[0].strip()
    m = CR.TEHSIL_RX.search(seg)
    if m:
        info["tehsil"] = re.sub(r"^(?:Tehsil|Teh\.?|Tahsil|Taluka|Block|तहसील|ब्लॉक)\s*[:\-]?\s*", "", m.group(0),
                                flags=re.I).split(",")[0].strip()
    m = CR.DISTRICT_RX.search(seg)
    district = None
    if m:
        district = re.sub(r"^(?:Distt?\.?|District|Zila|Jila|जिला|ज़िला|जनपद)\s*[:\-]?\s*", "", m.group(0),
                          flags=re.I).split(",")[0].split(" - ")[0].strip()
    else:
        low = seg.lower()
        for d in sorted(lex.district_state, key=len, reverse=True):
            if re.search(r"\b" + re.escape(d) + r"\b", low):
                district = d
                break
        for dv, key in lex.deva_district.items():
            if dv in seg:
                district = key
    if district:
        if any("ऀ" <= c <= "ॿ" for c in district):
            district = lex.deva_district.get(district, transliterate(district))
        info["district"] = district
    pins = CR.PIN_RX.findall(seg)
    if pins:
        info["pin"] = pins[-1]
    return info


def _scan_names(text: str, guards) -> list[Span]:
    """Unlabelled names: runs of capitalised (or Devanagari) tokens scored by gazetteer + shape."""
    out: list[Span] = []
    toks = N.tokens(text)
    lines_upper = {}
    i = 0
    while i < len(toks):
        s, e, t = toks[i]
        deva = N.is_deva(t)
        if not deva and not N.is_cap(t):
            i += 1
            continue
        run = [toks[i]]
        j = i + 1
        while j < len(toks):
            ps, pe, pt = run[-1]
            ns, ne, nt = toks[j]
            if text[pe:ns] != " " or N.is_deva(nt) != deva or (not deva and not N.is_cap(nt)):
                break
            run.append(toks[j])
            j += 1
        i = j
        out.extend(_score_run(text, run, deva, guards, lines_upper))
    return out


def _line_is_upper(text: str, pos: int, cache: dict) -> bool:
    ls = text.rfind("\n", 0, pos) + 1
    if ls in cache:
        return cache[ls]
    le = text.find("\n", pos)
    line = text[ls: le if le >= 0 else len(text)]
    letters = [c for c in line if c.isalpha() and c.isascii()]
    v = len(letters) > 8 and sum(c.isupper() for c in letters) / len(letters) > 0.8
    cache[ls] = v
    return v


def _score_run(text, run, deva, guards, cache) -> list[Span]:
    out = []
    # split the run at vocabulary words that are not gazetteer names
    cur = []
    groups = []
    for tok in run:
        t = tok[2]
        ok = N.is_gaz(t) or (not N.is_vocab(t) and not N.is_honorific(t) and t.rstrip(".").lower() not in N.LABEL_WORDS)
        if deva:
            ok = N.is_gaz(t) or (t not in N.HINDI_STOP and len(t) > 1)
        if ok:
            cur.append(tok)
        else:
            if cur:
                groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    for g in groups:
        s, e = g[0][0], g[-1][1]
        if overlaps(guards, s, e):
            continue
        words = [t for _, _, t in g]
        gaz = [N.is_gaz(w) for w in words]
        first = [N.is_first_gaz(w) for w in words]
        n = len(words)
        if text[e - 1] == "." and n > 1:
            e -= 1
        if deva:
            if any(first) and n >= 1 and (n >= 2 or _followed_by_particle(text, e)):
                out.append(Span(s, e, "PATIENT_NAME", 0.7, text[s:e], "unknown", {"src": "gazetteer"}))
            elif n >= 2 and sum(gaz) >= 1:
                out.append(Span(s, e, "PATIENT_NAME", 0.65, text[s:e], "unknown", {"src": "gazetteer"}))
            continue
        upper_line = _line_is_upper(text, s, cache)
        all_caps = all(w.isupper() for w in words)
        if all_caps and (upper_line or not all(gaz)):
            continue
        if n == 1:
            w = words[0]
            if first[0] and len(w) > 2 and not N.is_vocab(w) and _followed_by_particle(text, e):
                out.append(Span(s, e, "PATIENT_NAME", 0.7, w, "unknown", {"src": "gazetteer"}))
            continue
        if any(gaz):
            out.append(Span(s, e, "PATIENT_NAME", 0.75 if any(first) else 0.65, text[s:e], "unknown",
                            {"src": "gazetteer"}))
        else:
            # unknown capitalised bigram: canary-style names nobody listed
            if not upper_line and all(len(w.rstrip(".")) > 2 for w in words):
                out.append(Span(s, e, "OTHER_NAME", 0.55, text[s:e], "unknown", {"src": "shape"}))
    return out


_PARTICLE_RX = re.compile(r"\s+(?:ka|ki|ke|ko|ne|se|bhai|ji|sahab|का|की|के|को|ने|से|जी)\b")


def _followed_by_particle(text: str, e: int) -> bool:
    return bool(_PARTICLE_RX.match(text, e))


def _propagate(text: str, spans: list[Span], guards, ctx: Context) -> list[Span]:
    """Every other occurrence of a name token already known for this record is redacted too."""
    lex = get_lexicon()
    seeds: dict[str, str] = {}
    for toks, role in ctx.known_names:
        for t in toks:
            if len(t) >= 3 and t not in lex.generic:
                seeds.setdefault(t, role)
    for sp in spans:
        if sp.etype in NAME_TYPES and sp.conf >= 0.8 and sp.meta.get("src") not in ("shape",):
            for raw in re.split(r"[\s.]+", text[sp.start:sp.end]):
                c = N.deva_canon(raw) if N.is_deva(raw) else canon_token(raw)
                if len(c) >= 3 and c not in lex.generic and not N.is_honorific(raw):
                    role = "patient" if sp.etype == "PATIENT_NAME" else ("relative" if sp.etype == "RELATIVE_NAME"
                                                                          else "other")
                    seeds.setdefault(c, role)
    if not seeds:
        return spans
    out = list(spans)
    tok_list = N.tokens(text)
    tok_pos = {t[0]: i for i, t in enumerate(tok_list)}
    for s, e, t in tok_list:
        if N.is_deva(t):
            c = N.deva_canon(t)
        else:
            core = N.tok_core(t)
            if not core or not core[0].isupper():
                continue
            c = canon_token(core)
        if len(c) < 3:
            continue
        role = seeds.get(c)
        vocab = (not N.is_deva(t)) and N.is_vocab(N.tok_core(t)) and not N.is_gaz(N.tok_core(t))
        if role is not None and vocab and c in lex.medical:
            continue
        if role is None and not vocab:
            from ..translit.canonical import jaro_winkler
            for sd, r in seeds.items():
                if sd[0] == c[0] and abs(len(sd) - len(c)) <= 1 and jaro_winkler(sd, c) >= 0.93:
                    role = r
                    break
        if role is None:
            continue
        if overlaps(guards, s, e, {"doctor", "org", "eponym", "complaint", "dose"}):
            continue
        e2 = e - 1 if t.endswith(".") else e
        s2 = s
        # extend over adjacent capitalised name tokens (surnames, generic parts like Bano / Devi / Kumar)
        idx = tok_pos.get(s)
        if idx is not None:
            j = idx + 1
            while j < len(tok_list) and text[tok_list[j - 1][1]:tok_list[j][0]] == " ":
                nt = tok_list[j][2]
                if N.is_cap(nt) and (N.is_gaz(nt) or canon_token(N.tok_core(nt)) in lex.generic) and not N.is_vocab(nt):
                    e2 = tok_list[j][1] - (1 if nt.endswith(".") else 0)
                    j += 1
                else:
                    break
        etype = {"patient": "PATIENT_NAME", "relative": "RELATIVE_NAME"}.get(role, "OTHER_NAME")
        out.append(Span(s2, e2, etype, 0.78, text[s2:e2], role, {"src": "propagation"}))
    return out
