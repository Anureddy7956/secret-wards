"""Two-pass pipeline.

pass 1  ingest -> parse -> learn identifier shapes -> classify fields -> detect -> identity evidence
link    conflict-aware clustering -> keyed pseudonyms -> per-patient date shifts and age bands
privacy k-anonymity search picks age-band width and location level; rare diagnoses generalised
pass 2  re-detect with cluster-wide names -> render -> write sanitized/ + records.jsonl + report.json

Everything stays in memory. No file content is ever logged.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .config import Policy
from .detect import column_classifier as CC
from .detect import context_rules as CR
from .detect.combine import LOCATION_TYPES, NAME_TYPES
from .detect.lexicon import get_lexicon
from .detect.normalize import normalize_text
from .detect.patterns import digits, id_shape, norm_id
from .detect.text_detector import Context, Learned, detect, parse_address
from .ingest.csv_reader import detect_newline, read_csv, sniff_delimiter
from .ingest.detect_format import sniff
from .ingest.fhir_reader import fhir_class, ident_class
from .ingest.json_reader import iter_keys, iter_leaves, pattern_of, pointer_escape
from .link.cluster import link
from .link.compare import names_compatible
from .link.extract_identity import Identity, normalize_gender, village_key
from .privacy import rare_values
from .privacy.age_band import band_for
from .privacy.dates import find_dates
from .privacy.risk import choose as choose_k
from .pseudo.hmac_ids import assign as assign_pseudonyms
from .security.crypto import Keyring
from .security.quarantine import Quarantine
from .security.safe_log import log
from .translit.canonical import name_tokens
from .write.filename_sanitizer import component_has_pii, safe_name
from .write.render import RecordView, maybe_b64_text, render_text, shift_date_value

PATIENT_EVIDENCE = {"PATIENT_NAME", "NAME_PART", "MRN", "AADHAAR", "ABHA_NUMBER", "DOB", "AGE_SEX", "IDENT"}
STRUCT_PII = {"PATIENT_NAME", "NAME_PART", "RELATIVE_NAME", "OTHER_NAME", "PHONE", "EMAIL", "MRN", "AADHAAR",
              "ABHA_NUMBER", "ABHA_ADDRESS", "PAN", "INSURANCE_ID", "IDENT", "EXT"}
TEXTLIKE = {"TEXT", "SOURCE_PATH", "ADDRESS", None}


@dataclass
class Rec:
    loc: str
    kind: str                       # row | json | doc
    fields: list = field(default_factory=list)   # [(path, cls, hint)]
    ident: Identity = field(default_factory=Identity)
    raw_dates: list = field(default_factory=list)  # [(str, hint)]
    raw_ages: list = field(default_factory=list)   # [age]
    raw_dobs: list = field(default_factory=list)   # [(str, hint)]
    struct_names: list = field(default_factory=list)  # raw patient names (structured)
    rel_names: list = field(default_factory=list)
    cid: int | None = None
    pid: str | None = None
    shift: int = 0
    band: tuple | None = None
    generalized: bool = False
    suppressed: bool = False


@dataclass
class Doc:
    rel: str
    sha: str
    ext: str
    fmt: str = ""
    enc: str = ""
    text: str = ""
    parsed: object = None
    delim: str = ","
    newline: str = "\n"
    bom: bool = False
    rows: list = field(default_factory=list)
    col_cls: list = field(default_factory=list)
    records: list = field(default_factory=list)
    leaf_cls: dict = field(default_factory=dict)    # JSON: path tuple -> (cls, hint)
    rec_of_path: dict = field(default_factory=dict)  # JSON: path prefix -> rec index
    collections: list = field(default_factory=list)
    order: str = "dmy"
    votes: list = field(default_factory=lambda: [0, 0])
    keys: list = field(default_factory=list)        # hospital/source keys for order voting
    status: str = "sanitized"
    reason: str | None = None
    out_rel: str | None = None
    output: str | bytes | None = None


_CHECKS = {
    "PHONE": lambda v: 10 <= len(digits(v)) <= 13 or bool(re.search(r"[Xx*]{4}", v)),
    "AADHAAR": lambda v: len(digits(v)) == 12 or bool(re.search(r"[Xx*]{4}", v)),
    "PAN": lambda v: bool(re.fullmatch(r"\s*[A-Z]{5}\d{4}[A-Z]\s*", v)),
    "EMAIL": lambda v: "@" in v,
    "PIN": lambda v: bool(re.fullmatch(r"\s*[1-9]\d{2}\s?\d{3}\s*", v)),
    "AGE": lambda v: bool(re.match(r"\s*\d{1,3}\b", v)),
    "GENDER": lambda v: v.strip().lower() in CC.GENDER_VALUES,
    "DOB": lambda v: bool(find_dates(v)),
}


def _positional_ok(row: list, col_cls: list) -> bool:
    """A ragged row (cells missing at the end, or extra cells at the end) keeps its column meanings when every
    checkable cell still fits its column (phone looks like a phone, age like an age...). A row whose cells
    moved (an inserted or dropped cell in the middle) fails the checks and is handled as free text."""
    passed = 0
    for ci, cell in enumerate(row[:len(col_cls)]):
        cls = col_cls[ci][0]
        chk = _CHECKS.get(cls)
        if chk is None or not str(cell).strip():
            continue
        if not chk(str(cell)):
            return False
        passed += 1
    return passed >= 2


class Pipeline:
    def __init__(self, policy: Policy, secret: bytes):
        self.policy = policy
        self.keys = Keyring(secret)
        self.lex = get_lexicon()
        self.learned = Learned()
        self.docs: list[Doc] = []
        self.counter = Counter()
        self.ref_year = 2026
        self.max_depth = int(policy.get("limits.max_json_depth", 200))

    # ------------------------------------------------------------------ ingest
    def ingest(self, root: Path):
        paths = []
        for dp, dn, fn in os.walk(root):
            dn.sort()
            for n in sorted(fn):
                paths.append(Path(dp) / n)
        for p in paths:
            rel = p.relative_to(root).as_posix()
            with open(p, "rb") as fh:
                raw = fh.read()
            d = Doc(rel=rel, sha=hashlib.sha256(raw).hexdigest(), ext=p.suffix.lower())
            try:
                if len(raw) > int(self.policy.get("limits.max_file_mb", 200)) * 1024 * 1024:
                    raise Quarantine("too_large")
                fmt, text, enc, parsed = sniff(raw, d.ext, self.max_depth)
                d.fmt, d.enc, d.bom = fmt, enc, raw.startswith(b"\xef\xbb\xbf")
                if fmt == "csv":
                    d.delim = sniff_delimiter(text, d.ext)
                    d.newline = detect_newline(text)
                    rows = read_csv(text, d.delim)
                    if not rows:
                        raise Quarantine("empty_file")
                    d.rows = [[normalize_text(c) for c in r] for r in rows]
                elif fmt in ("json", "fhir"):
                    d.parsed = _normalize_json(parsed)
                    d.newline = "\n"
                    d.text = text
                else:
                    d.newline = detect_newline(text)
                    d.text = normalize_text(text.replace("\r\n", "\n"))
            except Quarantine as q:
                d.status, d.reason = "quarantined", q.reason
            except Exception as exc:  # noqa: BLE001 - never crash on one file
                log("file_error", sha=d.sha[:12], stage="ingest", exc=type(exc).__name__)
                d.status, d.reason = "quarantined", "processing_error"
            self.docs.append(d)

    # ------------------------------------------------------------------ learn identifier shapes
    def learn(self):
        def add_id(raw):
            raw = str(raw).strip()
            if not raw or len(raw) > 40:
                return
            nid = norm_id(raw)
            if sum(c.isdigit() for c in nid) < 4:
                return
            self.learned.id_values.add(nid)
            if any(c.isalpha() for c in nid):
                self.learned.id_shapes.add(id_shape(raw))
            groups = re.findall(r"\d+", raw)
            if groups and len(groups[-1]) >= 6:
                self.learned.id_digit_cores.add(groups[-1])

        for d in self.docs:
            if d.status != "sanitized":
                continue
            if d.fmt == "csv" and d.rows:
                header = d.rows[0]
                for ci, h in enumerate(header):
                    cls, _ = CC.classify_header([h])
                    if cls == "MRN":
                        for r in d.rows[1:]:
                            if ci < len(r) and len(r) == len(header):
                                add_id(r[ci])
            elif d.fmt == "json":
                for path, v in iter_leaves(d.parsed):
                    keys = [k for k in path if isinstance(k, str)]
                    if isinstance(v, (str, int)) and keys and CC.classify_header(keys)[0] == "MRN":
                        add_id(v)
            elif d.fmt == "fhir":
                for e in d.parsed.get("entry", []) or []:
                    res = (e or {}).get("resource") or {}
                    for ident in res.get("identifier", []) if isinstance(res.get("identifier"), list) else []:
                        if isinstance(ident, dict) and ident_class(ident.get("system"), None) == "MRN":
                            add_id(ident.get("value", ""))
            # labelled identifiers in free text (UHID:, IPD No:, पंजीकरण सं.:)
            texts = []
            if d.fmt == "text":
                texts = [d.text]
            for t in texts:
                for rx, etype, role, mode, conf in CR.LABELS:
                    if mode != "id":
                        continue
                    for m in rx.finditer(t):
                        mm = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9/\-]*[0-9][A-Za-z0-9/\-]*)", t[m.end():])
                        if mm:
                            add_id(mm.group(1).rstrip("-/"))

    # ------------------------------------------------------------------ pass 1: structure + detection
    def analyse(self):
        for d in self.docs:
            if d.status != "sanitized":
                continue
            try:
                if d.fmt == "csv":
                    self._analyse_csv(d)
                elif d.fmt in ("json", "fhir"):
                    self._analyse_json(d)
                else:
                    self._analyse_text(d)
            except Exception as exc:  # noqa: BLE001
                log("file_error", sha=d.sha[:12], stage="detect", exc=type(exc).__name__)
                d.status, d.reason, d.records = "quarantined", "processing_error", []
        for d in self.docs:
            if d.status == "sanitized" and len(d.records) == 1 and d.records[0].loc == "doc":
                self._filename_evidence(d, d.records[0])
        self._infer_orders()
        self._finalize_identities()

    def _filename_evidence(self, d: Doc, rec: Rec):
        """Phones / IDs in a single-record file's name ('7148988804_report_0047.json') are that patient's."""
        stem = Path(d.rel).name.rsplit(".", 1)[0]
        text = re.sub(r"[_]+", " ", stem)
        for sp in detect(text, self._ctx()):
            if sp.etype in ("MRN", "PHONE", "AADHAAR", "ABHA_NUMBER", "PAN", "INSURANCE_ID"):
                v = digits(sp.value or text[sp.start:sp.end])[-10:] if sp.etype == "PHONE" else \
                    norm_id(sp.value or text[sp.start:sp.end])
                if v and not (sp.etype == "PHONE" and len(v) < 10):
                    rec.ident.ids.add((sp.etype, v))

    def _ctx(self, known=()):
        return Context(self.learned, known_names=list(known))

    def _text_evidence(self, rec: Rec, text: str, known=()):
        spans = detect(text, self._ctx(known))
        for sp in spans:
            frag = text[sp.start:sp.end]
            if sp.meta.get("src") == "propagation":
                continue
            if sp.etype == "PATIENT_NAME" and sp.role == "patient":
                rec.ident.add_name(frag)
                g = sp.meta.get("gender")
                if g:
                    rec.ident.genders.add(g)
            elif sp.etype == "RELATIVE_NAME":
                rec.ident.add_relative(frag)
            elif sp.etype in ("MRN", "PHONE", "AADHAAR", "ABHA_NUMBER", "ABHA_ADDRESS", "EMAIL", "PAN",
                              "INSURANCE_ID"):
                v = sp.value or frag
                v = digits(v)[-10:] if sp.etype == "PHONE" else (norm_id(v) if sp.etype not in ("EMAIL",) else v)
                if v and not (sp.etype == "PHONE" and len(v) < 10):
                    rec.ident.ids.add((sp.etype, v))
            elif sp.etype == "AGE":
                try:
                    rec.raw_ages.append(int(sp.value or frag))
                except ValueError:
                    pass
            elif sp.etype == "DOB":
                rec.raw_dobs.append((frag, None))
            elif sp.etype == "ADDRESS":
                self._address_evidence(rec, sp.meta)
            elif sp.etype == "VILLAGE":
                rec.ident.villages.add(village_key(re.sub(r"(?i)^(?:vill(?:age)?|gram|gaon|ग्राम|गांव)\.?\s*[:\-]?\s*",
                                                          "", frag)))
        # gender cues in free text
        for m in re.finditer(r"/\s*(M|F|Male|Female|पुरुष|महिला)\b", text):
            g = normalize_gender(m.group(1))
            if g:
                rec.ident.genders.add(g)
        for h in find_dates(text):
            rec.raw_dates.append((h.raw, None))
        return spans

    def _address_evidence(self, rec: Rec, info: dict):
        if info.get("village"):
            rec.ident.villages.add(village_key(info["village"]))
        if info.get("district"):
            rec.ident.districts.add(info["district"].lower())
        if info.get("pin"):
            rec.ident.pins.add(info["pin"])

    def _struct_evidence(self, rec: Rec, cls: str, value, hint=None):
        if value is None or (isinstance(value, str) and not value.strip()) or isinstance(value, bool):
            return
        v = str(value).strip()
        if cls == "PATIENT_NAME":
            rec.struct_names.append(v)
            rec.ident.add_name(v)
        elif cls == "NAME_PART":
            rec.struct_names.append(v)
        elif cls == "RELATIVE_NAME":
            rec.rel_names.append(v)
            rec.ident.add_relative(v)
            m = re.match(r"(?i)^\s*([sdwh])\s*/\s*o", v)
            if m:
                rec.ident.genders.add("M" if m.group(1).lower() in "sh" else "F")
        elif cls == "RELATION":
            low = v.lower().replace(".", "/")
            if low in CR.GENDER_BY_RELATION:
                rec.ident.genders.add(CR.GENDER_BY_RELATION[low])
        elif cls in ("MRN", "AADHAAR", "ABHA_NUMBER", "PAN", "INSURANCE_ID", "IDENT"):
            nid = norm_id(v)
            if cls in ("AADHAAR", "ABHA_NUMBER"):
                nid = digits(v)
                if cls == "AADHAAR" and len(nid) != 12:
                    return
            if len(nid) >= 4:
                rec.ident.ids.add(("MRN" if cls == "IDENT" else cls, nid))
        elif cls == "PHONE":
            dg = digits(v)
            if len(dg) >= 10:
                rec.ident.ids.add(("PHONE", dg[-10:]))
        elif cls in ("EMAIL", "ABHA_ADDRESS"):
            rec.ident.ids.add((cls, v.lower()))
        elif cls == "GENDER":
            rec.ident.add_gender(v)
        elif cls == "AGE":
            m = re.match(r"\s*(\d{1,3})", v)
            if m:
                rec.raw_ages.append(int(m.group(1)))
        elif cls == "AGE_SEX":
            m = re.match(r"\s*(\d{1,3})\s*(?:y\w*)?\s*/\s*(\w+)", v, re.I)
            if m:
                rec.raw_ages.append(int(m.group(1)))
                rec.ident.add_gender(m.group(2))
        elif cls == "DOB":
            rec.raw_dobs.append((v, hint))
        elif cls == "DATE":
            rec.raw_dates.append((v, hint))
        elif cls == "VILLAGE":
            rec.ident.villages.add(village_key(v))
        elif cls == "DISTRICT":
            rec.ident.districts.add(v.lower())
        elif cls == "PIN":
            rec.ident.pins.add(digits(v))
        elif cls == "ADDRESS":
            self._address_evidence(rec, parse_address(v))

    def _analyse_csv(self, d: Doc):
        header, body = d.rows[0], d.rows[1:]
        n = len(header)
        d.col_cls = []
        for ci, h in enumerate(header):
            vals = [r[ci] for r in body if len(r) == n and ci < len(r)]
            d.col_cls.append(CC.classify([h], vals, self.learned.id_shapes))
        self._vote_text(d, " ".join(header))
        d.keys.append("prefix:" + _prefix(d.rel))
        for i, row in enumerate(body):
            rec = Rec(loc=f"row:{i}", kind="row")
            aligned = len(row) == n or _positional_ok(row, d.col_cls)
            name_parts = []
            for ci, cell in enumerate(row):
                cls, hint = d.col_cls[ci] if aligned and ci < n else ("TEXT", None)
                rec.fields.append(((ci,), cls, hint))
                if cls == "NAME_PART" and cell.strip():
                    name_parts.append((header[ci] if ci < n else "", cell))
                if cls not in TEXTLIKE:
                    self._struct_evidence(rec, cls, cell, hint)
                    if cls in ("DATE", "DOB"):
                        self._vote_value(d, cell, hint)
            if name_parts:
                rec.ident.add_name(_join_name_parts(name_parts))
            known = self._known_from_struct(rec)
            for ci, cell in enumerate(row):
                cls = rec.fields[ci][1]
                if cls in TEXTLIKE and cell.strip():
                    self._text_evidence(rec, cell, known)
                    self._vote_text(d, cell)
            d.records.append(rec)

    def _known_from_struct(self, rec: Rec):
        known = []
        for n in rec.struct_names:
            known.append((tuple(name_tokens(n)), "patient"))
        for n in rec.rel_names:
            known.append((tuple(name_tokens(re.sub(r"(?i)^\s*[sdwch]\s*/\s*o\.?\s*", "", n))), "relative"))
        return known

    def _analyse_text(self, d: Doc):
        rec = Rec(loc="doc", kind="doc")
        rec.fields.append((("text",), "TEXT", None))
        self._text_evidence(rec, d.text)
        self._vote_text(d, d.text)
        first = next((ln for ln in d.text.splitlines() if ln.strip()), "")
        d.keys.append("head:" + re.sub(r"[^A-Z]", "", first.upper().split(",")[0].split(" - ")[0])[:40])
        d.keys.append("prefix:" + _prefix(d.rel))
        d.records.append(rec)

    def _json_records(self, d: Doc):
        """Decide record boundaries: FHIR / single object -> doc; list of patient-bearing objects -> pointers."""
        data = d.parsed
        if d.fmt == "fhir":
            return []
        if isinstance(data, list):
            if data and all(isinstance(x, dict) for x in data):
                return [()]
            return []
        if not isinstance(data, dict):
            return []
        colls = []
        top_evidence = False
        for k, v in data.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                ev = 0
                for item in v[:50]:
                    for path, leaf in iter_leaves(item):
                        keys = [x for x in path if isinstance(x, str)]
                        c, _ = CC.classify_header([k] + keys)
                        if c in PATIENT_EVIDENCE and leaf not in (None, ""):
                            ev += 1
                            break
                if ev >= max(1, min(len(v), 50) // 2):
                    colls.append((k,))
            else:
                for path, leaf in iter_leaves(v, (k,)):
                    keys = [x for x in path if isinstance(x, str)]
                    c, _ = CC.classify_header(keys)
                    if c in PATIENT_EVIDENCE and leaf not in (None, ""):
                        top_evidence = True
        if top_evidence:
            return []
        return colls

    def _analyse_json(self, d: Doc):
        data = d.parsed
        colls = self._json_records(d)
        d.collections = colls
        recs: dict[tuple, Rec] = {}
        if colls:
            for c in colls:
                lst = data if c == () else data[c[0]]
                for i in range(len(lst)):
                    prefix = c + (i,)
                    loc = "/" + "/".join(pointer_escape(x) for x in prefix)
                    recs[prefix] = Rec(loc=loc, kind="json")
        else:
            recs[()] = Rec(loc="doc", kind="doc")
        leaves = iter_leaves(data)
        # classify by path pattern, with all values of that pattern
        by_pat = defaultdict(list)
        for path, v in leaves:
            if isinstance(v, (str, int, float)) and not isinstance(v, bool):
                by_pat[pattern_of(path)].append(str(v))
        pat_cls = {}
        resource_of = {}
        if d.fmt == "fhir":
            for i, e in enumerate(data.get("entry", []) or []):
                resource_of[i] = ((e or {}).get("resource") or {})
        for pat, vals in by_pat.items():
            keys = [k for k in pat if isinstance(k, str) and k != "[]"]
            if d.fmt == "fhir":
                pat_cls[pat] = None
            else:
                pat_cls[pat] = CC.classify(keys, vals, self.learned.id_shapes) if keys else ("TEXT", None)
        if d.fmt != "fhir" and isinstance(data, dict):
            meta = data.get("_export_meta") or data.get("meta") or {}
            hosp = (meta.get("hospital") if isinstance(meta, dict) else None) or data.get("hospital") or \
                (data.get("facility") or {}).get("name") if isinstance(data.get("facility"), dict) else None
            if isinstance(hosp, str):
                d.keys.append("head:" + re.sub(r"[^A-Z]", "", hosp.upper())[:40])
        d.keys.append("prefix:" + _prefix(d.rel))
        # assign leaves to records
        for path, v in leaves:
            rec_key = None
            for c in colls:
                if path[:len(c) + 1][:len(c)] == c and len(path) > len(c) and isinstance(path[len(c)], int):
                    rec_key = c + (path[len(c)],)
                    break
            if not colls:
                rec_key = ()
            if d.fmt == "fhir":
                cls, hint = self._fhir_leaf_class(data, path), None
            else:
                cls, hint = pat_cls.get(pattern_of(path), ("TEXT", None))
            d.leaf_cls[path] = (cls, hint)
            rec = recs.get(rec_key) if rec_key is not None else None
            if rec is None:
                continue  # file-level metadata (sanitised, not a record)
            rec.fields.append((path, cls, hint))
            if isinstance(v, bool) or v is None:
                continue
            if cls not in TEXTLIKE and cls not in ("BASE64", "EXT", "DATE_META"):
                if cls == "IDENT" and d.fmt == "fhir":
                    ic = self._fhir_ident_cls(data, path)
                    self._struct_evidence(rec, ic, v)
                else:
                    self._struct_evidence(rec, cls, v, hint)
                if cls in ("DATE", "DOB") and isinstance(v, str):
                    self._vote_value(d, v, hint)
        # FHIR name parts -> full name
        for rk, rec in recs.items():
            parts = [(str(p[-2]) if len(p) > 1 else "", data_get(data, p)) for p, c, _ in rec.fields
                     if c == "NAME_PART"]
            parts = [(k, v) for k, v in parts if isinstance(v, str) and v.strip()]
            if parts:
                rec.ident.add_name(_join_name_parts(parts))
            known = self._known_from_struct(rec)
            for path, cls, hint in rec.fields:
                v = data_get(data, path)
                if cls in TEXTLIKE and isinstance(v, str) and v.strip():
                    self._text_evidence(rec, _strip_html(v), known)
                    self._vote_text(d, v)
                    if len(v) >= 24 and " " not in v.strip():
                        t = maybe_b64_text(v)   # an attachment under an unrecognised key ('scan_b64')
                        if t:
                            self._text_evidence(rec, normalize_text(t), known)
                elif cls == "BASE64" and isinstance(v, str):
                    t = maybe_b64_text(v)
                    if t:
                        self._text_evidence(rec, normalize_text(t), known)
        d.rec_of_path = {k: i for i, k in enumerate(recs)}
        d.records = list(recs.values())

    def _fhir_leaf_class(self, data, path):
        if len(path) < 3 or path[0] != "entry" or path[2] != "resource":
            keys = tuple(k for k in path if isinstance(k, str))
            if keys[:1] == ("meta",) and keys[-1:] == ("source",):
                return "TEXT"
            if keys[-1:] in (("timestamp",), ("lastUpdated",)):
                return "DATE_META"
            if keys and keys[-1] in ("id", "system", "value", "resourceType", "type", "profile", "url"):
                return "KEEP" if not (keys[:1] == ("identifier",) and keys[-1] == "value") else "KEEP"
            return "KEEP"
        res = data_get(data, path[:3]) or {}
        rtype = res.get("resourceType") if isinstance(res, dict) else None
        rpath = tuple(k for k in path[3:] if isinstance(k, str))
        c = fhir_class(rtype, rpath, res)
        if c == "EXT":
            ext = data_get(data, path[:-1]) or {}
            url = str(ext.get("url", "")).lower() if isinstance(ext, dict) else ""
            if any(w in url for w in ("name", "mother", "father", "husband", "spouse", "guardian", "relative")):
                return "RELATIVE_NAME"
            if any(w in url for w in ("phone", "mobile", "contact")):
                return "PHONE"
            return "TEXT"
        if c is None:
            return "TEXT"
        return c

    def _fhir_ident_cls(self, data, path):
        ident = data_get(data, path[:-1]) or {}
        tcode = None
        try:
            tcode = ident.get("type", {}).get("coding", [{}])[0].get("code")
        except (AttributeError, IndexError):
            tcode = None
        return ident_class(ident.get("system") if isinstance(ident, dict) else None, tcode)

    # ------------------------------------------------------------------ date order (dmy / mdy)
    def _vote_value(self, d: Doc, v: str, hint):
        if hint in ("dmy", "mdy"):
            d.votes[0 if hint == "dmy" else 1] += 3
            return
        self._vote_text(d, v)

    def _vote_text(self, d: Doc, text: str):
        if hasattr(text, "lower") and re.search(r"(?i)mm\W*dd\W*yy", text):
            d.votes[1] += 3
        for h in find_dates(text):
            if h.kind == "num" and h.order_hint == "dmy":
                d.votes[0] += 1
            elif h.kind == "num" and h.order_hint == "mdy":
                d.votes[1] += 1

    def _infer_orders(self):
        default = str(self.policy.get("dates.default_order", "dmy"))
        live = [d for d in self.docs if d.status == "sanitized"]
        # ID shapes present in each doc act as source keys too (e.g. every 'UHID-######' file is one hospital)
        for d in live:
            shapes = set()
            for rec in d.records:
                for t, v in rec.ident.ids:
                    if t == "MRN":
                        shapes.add(re.sub(r"\d", "9", v))
            d.keys.extend("shape:" + s for s in sorted(shapes))
        key_votes = defaultdict(lambda: [0, 0])
        for d in live:
            if d.votes[0] != d.votes[1]:
                side = 0 if d.votes[0] > d.votes[1] else 1
                for k in d.keys:
                    key_votes[k][side] += 1
        for d in live:
            if d.votes[0] > d.votes[1]:
                d.order = "dmy"
            elif d.votes[1] > d.votes[0]:
                d.order = "mdy"
            else:
                # most specific source key with a decisive majority wins: ID format > header > file prefix
                d.order = default
                for kind in ("shape:", "head:", "prefix:"):
                    tot = [0, 0]
                    for k in d.keys:
                        if k.startswith(kind):
                            kv = key_votes.get(k)
                            if kv:
                                tot[0] += kv[0]
                                tot[1] += kv[1]
                    if tot[0] != tot[1]:
                        d.order = "mdy" if tot[1] > tot[0] else "dmy"
                        break
        years = Counter()
        for d in live:
            for rec in d.records:
                for raw, hint in rec.raw_dates[:20]:
                    for h in find_dates(raw):
                        if h.kind in ("iso", "num", "ymd"):
                            dd = h.parse(d.order)
                            if dd:
                                years[dd.year] += 1
        if years:
            self.ref_year = years.most_common(1)[0][0]

    def _finalize_identities(self):
        for d in self.docs:
            if d.status != "sanitized":
                continue
            hosp = next((k for k in d.keys if k.startswith("head:") and len(k) > 8), None) or \
                next((k for k in d.keys if k.startswith("prefix:")), None)
            for rec in d.records:
                ident = rec.ident
                ident.hospital = hosp
                mrns = {v for t, v in ident.ids if t == "MRN"}
                # a record that holds two different people (a FHIR Bundle with two Patients, a multi-patient
                # note) must not bridge them into one cluster: it takes no part in linking (patient: null)
                two_exclusive = any(len({v for t, v in ident.ids if t == k}) > 1 for k in ("AADHAAR", "ABHA_NUMBER"))
                two_people = len(ident.genders) > 1 and len(ident.names) > 1 and not all(
                    names_compatible([a], [b]) for a in ident.names for b in ident.names)
                if len(mrns) > 3 or two_exclusive or two_people:
                    ident.ids = set()
                    ident.names, ident.weak_names, ident.relatives = [], [], []
                dates = []
                for raw, hint in rec.raw_dates:
                    for h in find_dates(raw):
                        x = h.parse(hint or d.order, self.ref_year)
                        if x:
                            dates.append(x)
                dobs = set()
                for raw, hint in rec.raw_dobs:
                    for h in find_dates(raw):
                        x = h.parse(hint or d.order, self.ref_year)
                        if x:
                            dobs.add(x)
                ident.dobs = dobs
                event = [x for x in dates if x not in dobs]
                ident.dates = event
                ref = max(event) if event else dt.date(self.ref_year, 6, 30)
                ident.ages = [(a, ref) for a in rec.raw_ages if 0 <= a <= 120]

    # ------------------------------------------------------------------ linkage + pseudonyms
    def link(self):
        recs = [(d, r) for d in self.docs if d.status == "sanitized" for r in d.records]
        idents = [r.ident for _, r in recs]
        cids = link(idents, self.policy)
        members = defaultdict(list)
        for (d, r), cid in zip(recs, cids):
            r.cid = cid
            if cid is not None:
                members[cid].append(r)
        cluster_keys = {}
        cands = {}
        for cid, rs in members.items():
            ids = sorted({f"{t}:{v}" for r in rs for t, v in r.ident.ids if t != "PHONE"})
            phones = sorted({f"P:{v}" for r in rs for t, v in r.ident.ids if t == "PHONE"})
            names = sorted({"N:" + " ".join(n) for r in rs for n in r.ident.names})
            has_patient = any(r.ident.has_patient_evidence() for r in rs)
            keys = ids + phones + names
            if (not has_patient and len(rs) == 1) or not keys:
                for r in rs:
                    r.cid = None
                continue
            cands[cid] = keys
        used = set()
        for cid in sorted(cands, key=lambda c: (cands[c], c)):
            key = next((k for k in cands[cid] if k not in used), None)
            if key is None:
                n = 2
                while f"{cands[cid][0]}#{n}" in used:
                    n += 1
                key = f"{cands[cid][0]}#{n}"
            used.add(key)
            cluster_keys[cid] = key
        pids = assign_pseudonyms(cluster_keys, self.keys.pseudonym, str(self.policy.get("pseudonym.prefix", "PSN-")),
                                 int(self.policy.get("pseudonym.length", 6)))
        self.cluster_members = {cid: members[cid] for cid in cluster_keys}
        self.cluster_pid = pids
        lo = int(self.policy.get("dates.shift_min_days", 15))
        hi = int(self.policy.get("dates.shift_max_days", 180))
        self.cluster_shift = {cid: _shift(self.keys.shift, "shift|" + key, lo, hi) for cid, key in cluster_keys.items()}
        self.id_to_cluster = {}
        for cid in cluster_keys:
            for r in self.cluster_members[cid]:
                for t, v in r.ident.ids:
                    if t == "MRN":
                        self.id_to_cluster.setdefault(v, cid)
        for d in self.docs:
            for r in d.records:
                if r.cid is not None and r.cid in pids:
                    r.pid = pids[r.cid]
                    r.shift = self.cluster_shift[r.cid]
                else:
                    r.cid = None
                    r.shift = _shift(self.keys.shift, f"rec|{d.rel}|{r.loc}", lo, hi)

    # ------------------------------------------------------------------ privacy policy (k-anonymity)
    def privacy(self):
        top = int(self.policy.get("age.top_code", 80))
        patients = []
        self.cluster_ages = {}
        for cid, rs in self.cluster_members.items():
            ages = sorted({a for r in rs for a, _ in r.ident.ages})
            self.cluster_ages[cid] = ages
            genders = {g for r in rs for g in r.ident.genders}
            districts = sorted({x for r in rs for x in r.ident.districts})
            dist = districts[0] if districts else None
            state = self.lex.district_state.get(dist or "", None) if dist else None
            patients.append({"ages": ages, "gender": next(iter(genders)) if len(genders) == 1 else None,
                             "district": dist, "state": state or ("?" if dist else None)})
        self.k_choice = choose_k(patients, self.policy)
        self.policy.data.setdefault("_chosen", {})["width"] = self.k_choice["width"]
        self.level = self.k_choice["level"]
        width = self.k_choice["width"]
        self.cluster_band = {cid: band_for(ages, width, top) if ages else None for cid, ages in self.cluster_ages.items()}
        for d in self.docs:
            for r in d.records:
                if r.cid is not None:
                    r.band = self.cluster_band.get(r.cid)
        self.rare = rare_values.plan(self, self.policy)

    # ------------------------------------------------------------------ pass 2: render
    def render(self, out_root: Path):
        san = out_root / "sanitized"
        for d in self.docs:
            if d.status != "sanitized":
                continue
            try:
                if d.fmt == "csv":
                    content = self._render_csv(d)
                elif d.fmt in ("json", "fhir"):
                    content = self._render_json(d)
                else:
                    content = self._render_text(d)
                d.out_rel = self._out_name(d)
                d.output = content
            except Exception as exc:  # noqa: BLE001
                log("file_error", sha=d.sha[:12], stage="write", exc=type(exc).__name__)
                d.status, d.reason, d.output = "quarantined", "processing_error", None
        used = set()
        for d in self.docs:
            if d.status != "sanitized":
                continue
            rel = d.out_rel
            if rel in used:  # never overwrite another output
                stem, _, ext = rel.rpartition(".")
                rel = f"{stem}_{d.sha[:8]}.{ext}" if stem else f"{rel}_{d.sha[:8]}"
            used.add(rel)
            d.out_rel = rel
            dest = san / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = d.output.encode("utf-8") if isinstance(d.output, str) else d.output
            if d.bom:
                data = b"\xef\xbb\xbf" + data
            with open(dest, "wb") as fh:
                fh.write(data)

    def _view(self, d: Doc, rec: Rec | None) -> RecordView:
        if rec is None:
            return RecordView(None, _shift(self.keys.shift, f"file|{d.rel}", 15, 180), None, d.order, self.level,
                              self.policy, [], self.counter, self.ref_year)
        names = []
        if rec.cid is not None:
            for r in self.cluster_members.get(rec.cid, []):
                names.extend(r.ident.names)
                names.extend(r.ident.weak_names)
        else:
            names = list(rec.ident.names) + list(rec.ident.weak_names)
        return RecordView(rec.pid, rec.shift, rec.band, d.order, self.level, self.policy, names, self.counter,
                          self.ref_year)

    def _known_for(self, rec: Rec | None):
        if rec is None:
            return []
        known = self._known_from_struct(rec)
        src = self.cluster_members.get(rec.cid, [rec]) if rec.cid is not None else [rec]
        for r in src:
            known += [(n, "patient") for n in r.ident.names]
            known += [(n, "patient") for n in r.ident.weak_names]
            known += [(n, "relative") for n in r.ident.relatives]
        return known

    def _render_value_text(self, text: str, view: RecordView, known, rec: Rec | None) -> str:
        spans = detect(text, self._ctx(known))
        out = render_text(text, spans, view)
        if rec is not None:
            out = rare_values.apply(self, rec, out)
        return out

    def _render_struct(self, cls, value, view: RecordView, rec, hint, known, first_name_part: list):
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, str) and not value.strip():
            return value
        numeric = isinstance(value, (int, float))
        sval = str(value)
        if cls == "PATIENT_NAME":
            self.counter["PATIENT_NAME"] += 1
            return view.pid or "[PATIENT]"
        if cls == "NAME_PART":
            self.counter["PATIENT_NAME"] += 1
            if not first_name_part:
                first_name_part.append(True)
                return view.pid or "[PATIENT]"
            return "[REDACTED]"
        if cls == "RELATIVE_NAME":
            self.counter["RELATIVE_NAME"] += 1
            m = re.match(r"(?i)^\s*((?:[sdwch])\s*/\s*o\.?)\s*", sval)
            return (m.group(1) + " " if m else "") + "[RELATIVE]"
        if cls == "OTHER_NAME":
            self.counter["OTHER_NAME"] += 1
            return "[NAME]"
        if cls in ("MRN", "IDENT"):
            self.counter["MRN"] += 1
            if numeric:
                return 0
            if view.pid:
                return view.pid
            cid = self.id_to_cluster.get(norm_id(sval))
            return self.cluster_pid.get(cid, "[ID]") if cid is not None else "[ID]"
        if cls in ("PHONE", "EMAIL", "AADHAAR", "ABHA_NUMBER", "ABHA_ADDRESS", "PAN", "INSURANCE_ID"):
            self.counter[cls] += 1
            if numeric:
                return 0
            return {"PHONE": "[PHONE]", "EMAIL": "[EMAIL]", "AADHAAR": "[AADHAAR]", "ABHA_NUMBER": "[ABHA]",
                    "ABHA_ADDRESS": "[ABHA]", "PAN": "[PAN]", "INSURANCE_ID": "[INSURANCE-ID]"}[cls]
        if cls == "ADDRESS":
            self.counter["ADDRESS"] += 1
            return view.address_text(parse_address(sval))
        if cls == "VILLAGE":
            self.counter["VILLAGE"] += 1
            view.generalized = True
            return "[VILLAGE]"
        if cls == "TEHSIL":
            self.counter["TEHSIL"] += 1
            view.generalized = True
            return "[TEHSIL]"
        if cls == "DISTRICT":
            return view.district_text(sval)
        if cls == "PIN":
            self.counter["PIN"] += 1
            return view.pin_text(sval)
        if cls == "AGE":
            m = re.match(r"\s*(\d{1,3})(.*)$", sval, re.S)
            if m:
                return view.age_text(int(m.group(1))) + (m.group(2) if not numeric else "")
            return value
        if cls == "AGE_SEX":
            m = re.match(r"\s*(\d{1,3})(.*)$", sval, re.S)
            if m:
                return view.age_text(int(m.group(1))) + m.group(2)
            return value
        if cls in ("DOB", "DATE"):
            if numeric:
                return value
            if cls == "DOB":
                self.counter["DOB"] += 1
            return shift_date_value(sval, view, hint)
        if cls == "DATE_META":   # FHIR Bundle.timestamp / meta.lastUpdated equal clinical times: shift them too
            return shift_date_value(sval, view, hint) if not numeric else value
        if cls in ("GENDER", "RELATION", "DOCTOR", "KEEP", "STATE"):
            if cls == "KEEP" and isinstance(value, str) and rec is not None and getattr(self, "_leaf_key", None) not in (
                    "id", "fullUrl", "reference", "system", "url", "profile"):
                return rare_values.apply(self, rec, value)
            return value
        if cls == "BASE64":
            t = maybe_b64_text(sval)
            import base64
            if t is None:
                self.counter["ATTACHMENT"] += 1
                return base64.b64encode(b"[ATTACHMENT REMOVED]").decode()
            clean = self._render_value_text(normalize_text(t), view, known, rec)
            return base64.b64encode(clean.encode("utf-8")).decode()
        # TEXT / SOURCE_PATH / unknown
        if numeric:
            return value
        url = re.match(r"(?i)^([a-z][a-z0-9+.\-]*://[^/\s]*/)(\S*)$", sval)
        if url:
            # 'http://his.local/UHID/2026/40398': identifiers hide in the URL path (FHIR meta.source etc.);
            # the path is checked as one string so 'UHID/2026/40398' is seen whole, and any remaining
            # long digit run in a path segment is removed
            path = self._render_value_text(url.group(2), view, known, rec)
            path = re.sub(r"(?<![^/?=&#])\d{5,}(?![^/?=&#])", "[ID]", path)
            return url.group(1) + path
        if cls == "SOURCE_PATH" or re.search(r"^[A-Za-z]:\\|\\\\|^/[^/ ]+/|[\\/][^\\/ ]+\.\w{2,4}$", sval):
            return self._render_path(sval, view, known, rec)
        return self._render_value_text(sval, view, known, rec)

    def _render_path(self, sval: str, view, known, rec=None) -> str:
        parts = re.split(r"([\\/])", sval)
        ctx = self._ctx(known)
        toks = {t for n, _ in known for t in n}
        out = []
        for p in parts:
            if p in ("\\", "/") or not p:
                out.append(p)
            elif component_has_pii(p, ctx, toks):
                self.counter["PATH_COMPONENT"] += 1
                out.append("[REDACTED]")
            else:
                out.append(self._render_value_text(p, view, known, rec))
        return "".join(out)

    def _render_csv(self, d: Doc) -> str:
        import csv
        import io
        header = d.rows[0]
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=d.delim, lineterminator=d.newline)
        hv = self._view(d, None)
        new_header = []
        for h in header:
            spans = [s for s in detect(h, self._ctx()) if s.etype not in ("AGE",)]
            pii = [s for s in spans if s.etype in NAME_TYPES | {"MRN", "PHONE", "AADHAAR", "EMAIL"} and s.conf >= 0.6]
            if pii:
                pid = None
                for s in spans:
                    if s.etype == "MRN":
                        cid = self.id_to_cluster.get(norm_id(h[s.start:s.end]))
                        pid = self.cluster_pid.get(cid) if cid is not None else None
                self.counter["HEADER"] += 1
                new_header.append(pid or "[PATIENT]")
            else:
                new_header.append(h)
        w.writerow(new_header)
        for rec, row in zip(d.records, d.rows[1:]):
            view = self._view(d, rec)
            known = self._known_for(rec)
            first_part = []
            out = []
            for (path, cls, hint), cell in zip(rec.fields, row):
                if cls in TEXTLIKE and cls != "ADDRESS":
                    out.append(self._render_value_text(cell, view, known, rec) if cell.strip() else cell)
                else:
                    out.append(str(self._render_struct(cls, cell, view, rec, hint, known, first_part)))
            if rec.pid and rec.pid not in "".join(out):
                pass
            rec.generalized = view.generalized
            w.writerow(out)
        return buf.getvalue()

    def _render_text(self, d: Doc) -> str:
        rec = d.records[0]
        view = self._view(d, rec)
        out = self._render_value_text(d.text, view, self._known_for(rec), rec)
        if rec.pid and rec.pid not in out:
            out = out.rstrip("\n") + f"\nPatient: {rec.pid}\n"
        rec.generalized = view.generalized
        if d.newline == "\r\n":
            out = out.replace("\n", "\r\n")
        return out

    def _render_json(self, d: Doc) -> str:
        data = d.parsed
        views, knowns, firsts = {}, {}, {}

        def rec_for(path):
            for c in d.collections:
                if len(path) > len(c) and tuple(path[:len(c)]) == c and isinstance(path[len(c)], int):
                    i = d.rec_of_path.get(c + (path[len(c)],))
                    return d.records[i] if i is not None else None
            if not d.collections:
                return d.records[0] if d.records else None
            return None

        def ctx_for(path):
            rec = rec_for(path)
            k = id(rec)
            if k not in views:
                views[k] = self._view(d, rec)
                knowns[k] = self._known_for(rec)
                firsts[k] = []
            return rec, views[k], knowns[k], firsts[k]

        id_map = self._fhir_id_map(d) if d.fmt == "fhir" else {}
        new = _rebuild(data, (), self, d, ctx_for, id_map)
        for rec in d.records:
            v = views.get(id(rec))
            if v is not None:
                rec.generalized = v.generalized
        if d.fmt == "fhir" or "\n" in d.text[:200]:
            indent = _detect_indent(d.text)
            return json.dumps(new, ensure_ascii=False, indent=indent) + ("\n" if d.text.endswith("\n") else "")
        return json.dumps(new, ensure_ascii=False, separators=(",", ":"))

    def _fhir_id_map(self, d: Doc) -> dict:
        """FHIR resource ids that themselves contain PII get a keyed replacement, applied to ids, fullUrls
        and references alike, so every reference still resolves."""
        m = {}
        for e in d.parsed.get("entry", []) or []:
            res = (e or {}).get("resource") or {}
            rid = res.get("id")
            if isinstance(rid, str):
                spans = [s for s in detect(rid.replace("-", " ") if not re.fullmatch(r"[0-9a-f\-]{36}", rid) else "",
                                           self._ctx()) if s.etype in ("MRN", "PHONE", "AADHAAR") or s.etype in NAME_TYPES]
                if spans or norm_id(rid) in self.learned.id_values:
                    tag = hmac.new(self.keys.misc, ("fhirid|" + rid).encode(), hashlib.sha256).hexdigest()[:16]
                    m[rid] = f"rk-{tag}"
        return m

    def _out_name(self, d: Doc) -> str:
        parts = d.rel.split("/")
        known = set()
        for rec in d.records:
            src = self.cluster_members.get(rec.cid, [rec]) if rec.cid is not None else [rec]
            for r in src:
                for n in r.ident.names + r.ident.weak_names + r.ident.relatives:
                    known.update(t for t in n if len(t) > 2 and t not in self.lex.generic)
        ctx = self._ctx()
        out = []
        for i, p in enumerate(parts):
            if component_has_pii(p, ctx, known):
                self.counter["FILENAME"] += 1
                out.append(safe_name(p, self.keys.misc, "/".join(parts[:i + 1]), self._ctx(
                    [((t,), "patient") for t in sorted(known)])))
            else:
                out.append(p)
        return "/".join(out)

    # ------------------------------------------------------------------ outputs
    def write_reports(self, out_root: Path, t0: float):
        files, records = [], []
        for d in self.docs:
            if d.status == "sanitized":
                files.append({"input_sha256": d.sha, "output": f"sanitized/{d.out_rel}", "status": "sanitized"})
                for r in d.records:
                    line = {"file": f"sanitized/{d.out_rel}", "loc": r.loc, "patient": r.pid}
                    if r.suppressed:
                        line["status"] = "suppressed"
                    elif r.generalized:
                        line["status"] = "generalized"
                    records.append(line)
            else:
                files.append({"input_sha256": d.sha, "output": None, "status": "quarantined",
                              "reason": d.reason or "processing_error"})
        with open(out_root / "records.jsonl", "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        n_san = sum(1 for f in files if f["status"] == "sanitized")
        ent = {k: v for k, v in sorted(self.counter.items()) if k not in ("HEADER", "FILENAME", "PATH_COMPONENT",
                                                                           "ATTACHMENT")}
        ident_total = sum(ent.values()) + sum(self.counter[k] for k in ("HEADER", "FILENAME", "PATH_COMPONENT",
                                                                        "ATTACHMENT"))
        report = {
            "schema": "raksha-report/1",
            "files": files,
            "counts": {
                "files_total": len(files), "files_sanitized": n_san, "files_quarantined": len(files) - n_san,
                "records_processed": len(records), "identifiers_detected": ident_total,
                "records_linked": sum(1 for r in records if r["patient"] is not None),
                "records_generalized": sum(1 for r in records if r.get("status") in ("generalized", "suppressed")),
                "records_suppressed": sum(1 for r in records if r.get("status") == "suppressed"),
                "records_quarantined": 0,
            },
            "entities": ent,
            "privacy": {
                "age_band_width": self.k_choice["width"], "location_level": self.level,
                "k_target": int(self.policy.get("k_anonymity.k_target", 5)), "k_min": self.k_choice["k_min"],
                "share_below_k": round(self.k_choice["violation_share"], 4),
                "rare_values_generalized": len(getattr(self, "rare", {}).get("codes", {})),
            },
            "timing": {"seconds": round(time.monotonic() - t0, 2)},
            "resources": {"peak_rss_mb": peak_rss_mb()},
        }
        with open(out_root / "report.json", "w", encoding="utf-8") as fh:
            fh.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return report


# ---------------------------------------------------------------------- helpers
def data_get(data, path):
    cur = data
    for p in path:
        try:
            cur = cur[p]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _rebuild(obj, path, pipe: Pipeline, d: Doc, ctx_for, id_map):
    """Iterative-safe (depth is bounded at ingest) rebuild of a JSON tree with sanitised keys and leaves."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            nk = _clean_key(k, path + (k,), pipe, d, ctx_for)
            base, n = nk, 2
            while nk in out:
                nk = f"{base}_{n}"
                n += 1
            out[nk] = _rebuild(v, path + (k,), pipe, d, ctx_for, id_map)
        return out
    if isinstance(obj, list):
        return [_rebuild(v, path + (i,), pipe, d, ctx_for, id_map) for i, v in enumerate(obj)]
    cls, hint = d.leaf_cls.get(path, ("TEXT", None))
    if id_map and isinstance(obj, str) and path and path[-1] in ("id", "fullUrl", "reference"):
        for old, new in id_map.items():
            if old in obj:
                obj = obj.replace(old, new)
        return obj
    rec, view, known, first = ctx_for(path)
    pipe._leaf_key = path[-1] if path else None
    if cls == "IDENT" and d.fmt == "fhir":
        cls = pipe._fhir_ident_cls(d.parsed, path)
    if cls == "TEXT" and isinstance(obj, str) and path and path[-1] == "div":
        return _render_div(obj, pipe, view, known, rec)
    return pipe._render_struct(cls, obj, view, rec, hint, known, first)


def _clean_key(k, path, pipe: Pipeline, d: Doc, ctx_for):
    """A JSON key that holds PII (a name, UHID, phone...) is replaced by the patient's pseudonym or a keyed tag."""
    if not isinstance(k, str) or len(k) < 3:
        return k
    try:
        _, _, known, _ = ctx_for(path)
    except Exception:  # noqa: BLE001
        known = []
    from .detect import names as _N
    if re.fullmatch(r"[a-z][a-z0-9_]*", k) and not any(c.isdigit() for c in k):
        # ordinary schema key: only a known / gazetteer name token inside it can make it PII
        toks = [t for t in k.split("_") if len(t) > 2]
        known_toks = {t for n, _ in known for t in n}
        from .translit.canonical import canon_token as _ct
        if not any(_ct(t) in known_toks or (_N.is_first_gaz(t) and not _N.is_vocab(t)) for t in toks):
            return k
    spans = detect(k.replace("_", " "), pipe._ctx(known))
    pii = [s for s in spans if (s.etype in NAME_TYPES and s.conf >= 0.55) or s.etype in
           ("MRN", "PHONE", "AADHAAR", "EMAIL", "PAN", "ABHA_NUMBER")]
    gaz_hit = any(_N.is_cap(t) and _N.is_first_gaz(t) and not _N.is_vocab(t)
                  for t in re.split(r"[_\s\-]+", k) if len(t) > 2)
    if not pii and not gaz_hit:
        return k
    pipe.counter["KEY"] += 1
    flat = k.replace("_", " ")
    for s in spans:
        if s.etype == "MRN":
            cid = pipe.id_to_cluster.get(norm_id(flat[s.start:s.end]))
            if cid is not None:
                return pipe.cluster_pid[cid]
    tag = hmac.new(pipe.keys.misc, ("key|" + k).encode("utf-8"), hashlib.sha256).hexdigest()[:8]
    return f"[REDACTED-{tag}]"


def _render_div(div: str, pipe: Pipeline, view, known, rec) -> str:
    """Sanitise the text nodes of an XHTML narrative, keeping the markup valid."""
    parts = re.split(r"(<[^>]+>)", div)
    out = []
    for p in parts:
        if p.startswith("<") and p.endswith(">"):
            out.append(p)
        elif p.strip():
            import html as _h
            txt = _h.unescape(p)
            clean = pipe._render_value_text(txt, view, known, rec)
            out.append(_h.escape(clean, quote=False))
        else:
            out.append(p)
    return "".join(out)


def _strip_html(s: str) -> str:
    if "<" in s and ">" in s:
        return re.sub(r"<[^>]+>", " ", s)
    return s


def _normalize_json(obj):
    if isinstance(obj, dict):
        return {(normalize_text(k) if isinstance(k, str) else k): _normalize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_json(v) for v in obj]
    if isinstance(obj, str):
        return normalize_text(obj)
    return obj


def _join_name_parts(parts):
    """Order 'first' before 'last' whatever the column order."""
    first = [v for k, v in parts if re.search(r"(?i)first|given|fname|^name$", k)]
    rest = [v for k, v in parts if not re.search(r"(?i)first|given|fname|^name$", k)]
    return " ".join(first + rest)


def _prefix(rel: str) -> str:
    name = rel.split("/")[-1].lower()
    m = re.match(r"([a-z]+)", name)
    return (rel.split("/")[0] + ":" + m.group(1)) if m else rel.split("/")[0]


def _detect_indent(text: str):
    m = re.search(r"\n( +)\S", text[:2000])
    if m:
        return len(m.group(1))
    return 2 if "\n" in text[:2000] else None


def _shift(key: bytes, msg: str, lo: int, hi: int) -> int:
    v = int.from_bytes(hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()[:4], "big")
    span = hi - lo + 1
    mag = lo + v % span
    return mag if (v >> 16) & 1 else -mag


def peak_rss_mb() -> float:
    try:
        import resource
        import sys
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        c = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        r = max(r, c)
        return round(r / 1024 if sys.platform != "darwin" else r / 1048576, 1)
    except Exception:  # noqa: BLE001
        return 0.0


def run(input_dir: str, output_dir: str, policy: Policy, secret: bytes) -> dict:
    t0 = time.monotonic()
    out = Path(output_dir)
    (out / "sanitized").mkdir(parents=True, exist_ok=True)
    p = Pipeline(policy, secret)
    p.ingest(Path(input_dir))
    p.learn()
    p.analyse()
    p.link()
    p.privacy()
    p.render(out)
    return p.write_reports(out, t0)
