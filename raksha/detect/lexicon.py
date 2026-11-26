"""Loads the shipped gazetteers once (no network, no dev data)."""
from __future__ import annotations

from functools import lru_cache

from ..config import DATA
from ..translit.canonical import canon_token


def _words(name: str) -> list[str]:
    out = []
    p = DATA / name
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.extend(line.split())
    return out


class Lexicon:
    def __init__(self):
        self.first_raw = set(w.lower() for w in _words("first_names.txt"))
        self.sur_raw = set(w.lower() for w in _words("surnames.txt"))
        self.first = {canon_token(w) for w in self.first_raw}
        self.sur = {canon_token(w) for w in self.sur_raw}
        self.generic = {canon_token(w) for w in _words("generic_name_tokens.txt")}
        self.english = set(_words("english_words.txt"))
        sections: dict[str, set[str]] = {}
        cur = None
        for line in (DATA / "medical_lexicon.txt").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                cur = line[1:-1]
                sections[cur] = set()
            elif cur and line:
                sections[cur].update(w.lower() for w in line.split())
        self.drugs = sections.get("drugs", set())
        self.labs = sections.get("labs", set())
        self.conditions = sections.get("conditions", set())
        self.eponym_heads = sections.get("eponym_heads", set())
        self.org_words = sections.get("org_words", set())
        self.medical = self.drugs | self.labs | self.conditions
        self.district_state: dict[str, str] = {}
        for line in (DATA / "places.txt").read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if "|" in line:
                d, s = line.split("|", 1)
                self.district_state[d.strip().lower()] = s.strip()
        self.deva_district: dict[str, str] = {}
        for line in (DATA / "places_deva.txt").read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if "|" in line:
                d, k = line.split("|", 1)
                self.deva_district[d.strip()] = k.strip()
        self.district_tokens = set()
        for d in self.district_state:
            self.district_tokens.update(d.split())
        self.states = {s.lower() for s in self.district_state.values()}

    # -- token predicates ---------------------------------------------------------------------
    def is_first(self, tok: str) -> bool:
        return canon_token(tok) in self.first

    def is_sur(self, tok: str) -> bool:
        return canon_token(tok) in self.sur

    def is_name_gaz(self, tok: str) -> bool:
        c = canon_token(tok)
        return c in self.first or c in self.sur

    def is_vocab(self, tok: str) -> bool:
        """An ordinary (non-name) word: English, medical, org or place vocabulary."""
        t = tok.lower().strip(".'’")
        return (t in self.english or t in self.medical or t in self.org_words or t in self.district_tokens
                or t in VOCAB_EXTRA)


# Hinglish / Hindi-in-Latin function words and clinical words that are not names.
VOCAB_EXTRA = {
    "ka", "ki", "ke", "ko", "ne", "se", "me", "mein", "hai", "hain", "tha", "thi", "the", "aur", "ya", "nahi", "nahin",
    "bhi", "to", "toh", "par", "pe", "wala", "wali", "kal", "aaj", "raat", "subah", "shaam", "dawai", "dava", "dawa",
    "bukhar", "khana", "pani", "theek", "thik", "accha", "achha", "abhi", "ab", "band", "gayi", "gaya", "rahe", "raha",
    "rahi", "liya", "diya", "diye", "lena", "lene", "dena", "bola", "boli", "karo", "karna", "kar", "koi", "problem",
    "call", "dr", "doctor", "pt", "patient", "pts", "mob", "mobile", "ph", "phone", "uhid", "mrn", "ipd", "opd", "reg",
    "no", "naam", "pata", "gaon", "gram", "tehsil", "distt", "dist", "district", "jila", "zila", "mohalla", "ward",
    "bed", "house", "makan", "near", "opp", "behind", "vill", "village", "pin", "rx", "adv", "advice", "review", "tab",
    "cap", "inj", "syp", "inh", "neend", "chal", "phir", "sakte", "dard", "pet", "sir", "khansi", "ulti", "dast",
    "kamzori", "chakkar", "sujan", "behosh", "attendant", "forwarded", "report", "lab", "labs", "sample", "received",
    "sadan", "seva", "aarogya", "arogya", "jeevan", "jyoti", "sanjeevani", "multispeciality", "charitable", "nursing",
    "notes", "discharge", "summary", "admission", "consultant", "course", "medications", "diagnosis", "history",
    "presenting", "complaints", "procedure", "visitor", "log", "trip", "remarks", "kgs", "yrs", "yr", "years", "y",
    "f", "m", "male", "female", "ji", "sahab", "bhai", "didi", "amma", "behenji", "bhaiya", "na", "haan", "ok",
    "md", "ms", "mbbs", "dnb", "frcs", "mrcp", "medicine", "surgery", "pulmonology", "cardiology", "paediatrics",
    "pediatrics", "orthopaedics", "orthopedics", "gynaecology", "obstetrics", "ent", "ophthalmology", "dermatology",
    "neurology", "nephrology", "urology", "psychiatry", "oncology", "emergency", "casualty", "icu", "nicu", "picu",
    "hdu", "general", "pathkind", "lifeline", "city", "diagnostics", "pradesh", "uttar", "bihar", "india", "bharat",
    "whatsapp", "attachment", "pdf", "jpg", "img", "ward", "bazar", "bazaar", "colony", "nagar", "basti", "tola",
    "mandir", "masjid", "school", "tanki", "chowk", "kotwali", "panchayat", "bhawan", "gurudwara", "primary", "hanuman",
    "kali", "mata", "durga", "shiv", "ram", "jama", "eidgah", "church", "station", "road", "marg", "gali", "kalan",
    "khurd", "purwa", "dih", "ganj", "pur", "mau", "abad", "garh", "o", "s", "w", "d", "c", "h", "k",
}


@lru_cache(maxsize=1)
def get_lexicon() -> Lexicon:
    return Lexicon()
