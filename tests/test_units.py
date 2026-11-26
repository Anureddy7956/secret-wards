"""Unit tests: transliteration, linkage, pseudonyms, privacy transforms, security helpers."""
import datetime as dt
import re
from pathlib import Path

from raksha.config import load_policy
from raksha.link.cluster import link
from raksha.link.extract_identity import Identity
from raksha.privacy.age_band import band_for, render
from raksha.privacy.dates import find_dates, shift_text_dates
from raksha.pseudo.hmac_ids import assign
from raksha.security.crypto import Keyring, Vault
from raksha.translit.canonical import canon_token, name_tokens, token_match
from raksha.translit.devanagari import transliterate

ROOT = Path(__file__).resolve().parent.parent
POL = load_policy()


def test_transliteration_cross_script():
    assert transliterate("मोहम्मद आरिफ") == "mohammad ariph"  # canonical keys fold ph->f
    assert transliterate("सुनीता पटेल") == "sunita patel"
    assert name_tokens("Md. Arif") == name_tokens("मोहम्मद आरिफ") == name_tokens("Mohammad Arif")
    assert name_tokens("Arif sahab") == ["arif"]
    assert token_match(canon_token("Reena"), canon_token("Rina"))
    assert not token_match(canon_token("Harish"), canon_token("Hemant"))


def ident(name, phone=None, gender=None, age=None, dob=None, rel=None, village=None, mrn=None):
    i = Identity()
    i.add_name(name)
    if phone:
        i.ids.add(("PHONE", phone))
    if mrn:
        i.ids.add(("MRN", mrn))
    if gender:
        i.genders.add(gender)
    if age is not None:
        i.ages.append((age, dt.date(2026, 6, 1)))
    if dob:
        i.dobs.add(dob)
    if rel:
        i.add_relative(rel)
    if village:
        i.villages.add(village)
    return i


def test_language_variants_link_homonyms_do_not():
    ids = [ident("Mohammad Arif", phone="9839011223", gender="M", age=47, mrn="QHS1"),
           ident("मोहम्मद आरिफ", phone="9839011223", age=47),
           ident("Md. Arif", gender="M", age=47, mrn="QHS1"),
           ident("Arif sahab", phone="9839011223"),
           ident("Mohammad Arif", phone="9123456780", gender="M", age=23, mrn="QHS2")]
    c = link(ids, POL)
    assert c[0] == c[1] == c[2] == c[3]
    assert c[4] != c[0]


def test_same_name_without_corroboration_not_linked():
    c = link([ident("Sunita Verma", gender="F", age=40), ident("Sunita Verma", gender="F", age=40)], POL)
    assert c[0] != c[1]


def test_same_name_with_relative_links():
    c = link([ident("Sunita Verma", gender="F", age=40, rel="W/o Raj Verma", mrn="A1"),
              ident("Sunita Verma", gender="F", age=41, rel="Raj Verma")], POL)
    assert c[0] == c[1]


def test_gender_conflict_blocks_shared_phone():
    c = link([ident("Kamal Rajput", phone="9000000001", gender="M"),
              ident("Asha Rajput", phone="9000000001", gender="F")], POL)
    assert c[0] != c[1]


def test_fragment_links_to_unique_match_only():
    i = Identity()
    i.add_name("Meera")
    i.add_relative("Rajan")
    c = link([ident("Meera Devi", gender="F", rel="W/o Rajan Kumar", mrn="M1"), i], POL)
    assert c[0] == c[1]


def test_pseudonyms_keyed_stable_and_collision_free():
    a = assign({1: "MRN:X", 2: "MRN:Y"}, Keyring(b"s1").pseudonym)
    b = assign({2: "MRN:Y", 1: "MRN:X"}, Keyring(b"s1").pseudonym)
    c = assign({1: "MRN:X", 2: "MRN:Y"}, Keyring(b"s2").pseudonym)
    assert a == b and a[1] != c[1]
    assert all(re.fullmatch(r"PSN-[0-9A-HJKMNP-TV-Z]{6}", v) for v in a.values())


def test_shift_preserves_length_of_stay():
    t = "Date of Admission: 2023-03-01\nDate of Discharge: 2023-03-10"
    out, n = shift_text_dates(t, 37, "dmy")
    d = [h.parse() for h in find_dates(out)]
    assert n == 2 and (d[1] - d[0]).days == 9 and d[0] != dt.date(2023, 3, 1)


def test_age_band_contains_age_and_top_code():
    for age in range(0, 100):
        lo, hi = band_for([age], 10, 80)
        assert lo <= age and (hi is None or age <= hi)
    assert render(band_for([47], 5, 80)) == "45-49"
    assert render(band_for([93], 10, 80)) == "80+"
    lo, hi = band_for([49, 50], 10, 80)     # straddling ages share one truthful band
    assert lo <= 49 and 50 <= hi


def test_vault_roundtrip_and_key_separation():
    k = Keyring(b"secret")
    assert len({k.pseudonym, k.shift, k.vault, k.misc}) == 4
    v = Vault(k.vault)
    blob = v.seal(b"intermediate", b"aad")
    assert v.open(blob, b"aad") == b"intermediate" and b"intermediate" not in blob


def test_no_print_or_raw_logging_in_package():
    offenders = []
    for p in (ROOT / "raksha").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        if re.search(r"^\s*print\(", src, re.M) or "traceback" in src or "logging.basicConfig" in src:
            offenders.append(p.name)
    assert offenders == []


def test_safe_log_drops_free_text(capsys):
    from raksha.security.safe_log import log
    log("file_error", sha="abc123def456", stage="detect", exc="Mohammad Arif 9839011223")
    err = capsys.readouterr().err
    assert "Arif" not in err and "9839011223" not in err and "abc123def456" in err


def test_guard_lookup_matches_linear_scan():
    """The sorted guard lookup (fast on long notes) must answer exactly like a plain scan."""
    import random
    from raksha.detect.medical_guard import Guards, inside, overlaps
    r = random.Random(7)
    for _ in range(500):
        g = [(a, a + r.randint(0, 60), r.choice(["dose", "vital", "doctor", "complaint"]))
             for a in (r.randint(0, 200) for _ in range(r.randint(0, 20)))]
        G = Guards(g)
        for _ in range(20):
            s = r.randint(0, 260)
            e = s + r.randint(0, 30)
            k = r.choice([None, {"dose"}, {"doctor", "complaint"}])
            assert inside(G, s, e, k) == any(a <= s and e <= b and (k is None or kk in k) for a, b, kk in g)
            assert overlaps(G, s, e, k) == any(s < b and a < e and (k is None or kk in k) for a, b, kk in g)
