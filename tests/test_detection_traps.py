"""Meaning / language traps from the problem statement."""
import pytest

from raksha.api import sanitize_text as S


@pytest.mark.parametrize("text", [
    "C/O fever x 3 days", "C/O pain abdomen x 8 days", "C/O: fever x 7 days, body ache",
    "Dolo 650 BD x 5 days", "Ramipril 5 mg 1-0-1", "BP 150/90", "Hb 9.8 g/dL", "SpO2 96%", "PR 88/min",
    "Parkinson's disease", "K/C/O addison's disease", "H/O TB 8 yrs back, completed ATT", "No H/O DM/HTN",
    "Down syndrome", "Hodgkin lymphoma", "Ward 4 (Medicine)", "Ward/Bed: Ward 4 (Medicine) / Bed 24",
    "Referred by ASHA worker of the village.", "Tab Paracetamol 650mg 1-1-1 x 5 days",
    "Inh Salbutamol inhaler 100 mcg 2 puffs x 5 days", "Random Blood Sugar 223 mg/dL",
])
def test_medical_values_unchanged(text):
    assert S(text) == text


@pytest.mark.parametrize("text", ["Dr. Ramesh Gupta reviewed the patient.", "Consultant: Dr. Imtiaz Ahmed (MS Surgery)",
                                  "डॉ. रमेश श्रीवास्तव"])
def test_doctor_kept(text):
    assert S(text) == text


def test_care_of_person_redacted():
    out = S("C/O Ramesh Kumar, Ward 1")
    assert "Ramesh" not in out and "C/O" in out


def test_wife_of_redacted():
    out = S("W/o Ramesh")
    assert "Ramesh" not in out and "[RELATIVE]" in out


def test_doctor_vs_relative_same_first_name():
    out = S("Attendant: Ramesh Patel, Mob. 8599253525\nDr. Ramesh Srivastava reviewed the patient.")
    assert "Patel" not in out and "Dr. Ramesh Srivastava reviewed the patient." in out and "8599253525" not in out


@pytest.mark.parametrize("phone", ["+91 98765 43210", "098765-43210", "9876543210", "९८७६५४३२१०", "0091-98765-43210",
                                   "98765.43210"])
def test_phones_redacted(phone):
    out = S(f"Mobile: {phone}")
    assert "98765" not in out and "43210" not in out and "[PHONE]" in out
    out = S(f"Koi problem ho to call karo {phone}")
    assert "43210" not in out


@pytest.mark.parametrize("text,needle", [
    ("Aadhaar 3972 0583 9628", "9628"), ("ABHA 91-7938-3729-8403", "8403"), ("PAN DCSPS3454E", "DCSPS3454E"),
    ("email anita.sharma8186@example.com", "anita"), ("abha addr ramesh.k@abdm", "ramesh.k"),
    ("XXXX XXXX 5866", "5866"), ("PMJAY-UP-3398744800", "3398744800"),
])
def test_identifiers_redacted(text, needle):
    assert needle not in S(text)


def test_hinglish_honorific_removed_with_name():
    assert S("Arif sahab ka BP 150/90", pid="PSN-7Q2K9D") == "PSN-7Q2K9D ka BP 150/90"


def test_devanagari_name_label():
    out = S("नाम: मोहम्मद शाहिद   आयु: 39 वर्ष")
    assert "शाहिद" not in out and "PSN-TEST01" in out and "आयु: 30-39 वर्ष" in out


def test_relative_label_in_hindi():
    out = S("पिता का नाम: रमेश पटेल")
    assert "रमेश" not in out and "[RELATIVE]" in out


def test_fragment_note():
    out = S("Asha, W/o Kamal, discharged in stable condition.")
    assert "Asha" not in out and "Kamal" not in out


def test_unknown_names_by_context():
    # names that are in no gazetteer (canary style) are still caught by context and shape
    assert "Nambiar" not in S("called by Kaveri Nambiar 94054-71434")
    assert "Wangmo" not in S("Consent witnessed by Tsering Wangmo, phone 8010993510.")
    assert "Qadri" not in S("18:40 - Zorawar Qadri (attendant, bed 12), mob 6910522119")


def test_address_removed():
    out = S("Address: House 364, Ward 20, Mohalla Raja Bazar, near Pani Tanki, Vill. Durgamau Kalan, Tehsil Lalganj, "
            "Distt. Rae Bareli - 229073")
    for w in ("364", "Raja Bazar", "Pani Tanki", "Durgamau", "Lalganj", "229073"):
        assert w not in out


def test_homoglyph_and_zero_width_names():
    out = S("Patient Name: Аsha R​ajput")   # Cyrillic A + zero-width space
    assert "sha" not in out.lower().replace("psn", "")


def test_age_band_contains_true_age():
    out = S("Age/Sex: 47 Yrs/F")
    lo, hi = out.split(":")[1].strip().split(" ")[0].split("-")
    assert int(lo) <= 47 <= int(hi)


# --- found by tools/make_tough.py -----------------------------------------------------------------

@pytest.mark.parametrize("text,phone", [("Attendant mob (853) 7215397.", "7215397"),
                                         ("Call (98765) 43210 after 5", "43210"),
                                         ("+91 (987) 654-3210", "654-3210")])
def test_bracketed_phone_redacted(text, phone):
    assert phone not in S(text)


@pytest.mark.parametrize("text,name", [
    ("Rose Ekka aur Happy Singh dono ka BP 130/80 tha.", "Happy Singh"),
    ("Rose Ekka aur Happy Singh dono ka BP 130/80 tha.", "Rose Ekka"),
    ("Golden Kaur ko Insulin 10 units SC HS.", "Golden"),
    ("Lovely Singh ka sugar 245 mg/dL", "Lovely"),          # not in any list: English word + known surname
    ("Insulin 10 units SC HS. Pinky Rani 23/F, sickle cell trait.", "Pinky"),
])
def test_names_that_are_english_words(text, name):
    out = S(text)
    assert name not in out


@pytest.mark.parametrize("text", ["Rose water gargles advised; patient is happy.", "Golden hour missed, BP 90/60.",
                                  "Golden Temple visit last week", "Insulin 10 units SC HS", "Dr. Lovely Singh reviewed."])
def test_english_words_without_a_name_kept(text):
    assert S(text) == text


def test_identifier_inside_url_path():
    from raksha.api import sanitize_text
    out = sanitize_text("source: http://his.local/UHID/2026/40398")
    assert "40398" not in out and "http://his.local/" in out
