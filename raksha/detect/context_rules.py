"""Context cues: field labels (English / Hinglish / Hindi), relation markers, honorifics, address grammar."""
from __future__ import annotations

import re

SEPC = r"\s*(?:\([^)\n]{0,20}\))?\s*(?::|[\-–](?=\s))\s*"   # label separator, optional '(attendant)' qualifier
OPT = r"\s*(?:(?::|[\-–](?=\s))\s*)?"

# (regex, etype, role, mode, conf). mode: name | id | phone | dob | age | address | village | line | aadhaar
LABELS = [
    (r"\b(?:Patient'?s?\s*Name|Name\s+of\s+(?:the\s+)?Patient|Pt\.?\s*Name|Patient|Pt\.|Naam|Mareez|Mariz|Rogi|"
     r"Name)" + SEPC, "PATIENT_NAME", "patient", "name", 0.95),
    (r"(?:मरीज़?\s*का\s*नाम|रोगी\s*का\s*नाम|नाम|मरीज़?)\s*[:\-–]\s*", "PATIENT_NAME", "patient", "name", 0.95),
    (r"\bReport\s+of\s+", "PATIENT_NAME", "patient", "name", 0.85),
    (r"\b(?:Referral|Referred\s+patient|Pt\s+name)\s*:\s*", "PATIENT_NAME", "patient", "name", 0.8),
    (r"\b(?:Attendant(?:'s)?(?:\s*Name)?|Father'?s?\s*Name|Husband'?s?\s*Name|Mother'?s?\s*Name|Guardian(?:'s)?(?:\s*Name)?|"
     r"Spouse(?:'s)?(?:\s*Name)?|Next\s+of\s+Kin|NOK|Relative(?:'s)?(?:\s*Name)?|Informant|Escort|Brought\s+by|"
     r"Pita(?:\s*ka)?\s*Naam|Pati(?:\s*ka)?\s*Naam|Pita/Pati\s*ka\s*Naam|Kin)" + SEPC,
     "RELATIVE_NAME", "relative", "name", 0.95),
    (r"(?:पिता\s*का\s*नाम|पति\s*का\s*नाम|माता\s*का\s*नाम|अभिभावक(?:\s*का\s*नाम)?|पिता/पति\s*का\s*नाम)\s*[:\-–]\s*",
     "RELATIVE_NAME", "relative", "name", 0.95),
    (r"\b(?:called\s+by|witnessed\s+by|raised\s+by|signed\s+by|informed\s+by|reported\s+by|accompanied\s+by|"
     r"visited\s+by|contact\s+person|caller|visitor|witness)\s*:?\s*", "OTHER_NAME", "other", "name_weak", 0.85),
    (r"\b(?:UHID|U\.H\.I\.D|MRN|MR\s*No|CR\s*No|Reg(?:istration|n)?\.?\s*(?:No|Number|#)?|IPD\s*(?:No|Number)?|"
     r"IP\s*No|Adm(?:ission)?\.?\s*No|Patient\s*ID|Hosp(?:ital)?\.?\s*No|Card\s*No|PID)\.?" + SEPC,
     "MRN", "patient", "id", 0.95),
    (r"(?:पंजीकरण\s*(?:सं\.?|संख्या|नं\.?)|आईपीडी\s*(?:सं\.?|संख्या|नं\.?)|यूएचआईडी|रजि\.?\s*नं\.?)\s*[:\-–]?\s*",
     "MRN", "patient", "id", 0.95),
    (r"\b(?:Mob(?:ile)?|Ph(?:one)?|Tel(?:ephone)?|Cell|Contact(?:\s*No)?|WhatsApp|Callback|Call\s+karo|"
     r"call\s+at|Mobile\s*No)\.?" + OPT, "PHONE", "patient", "phone", 0.95),
    (r"(?:मोबाइल|फोन|फ़ोन|संपर्क)\s*(?:नं\.?)?\s*[:\-–]?\s*", "PHONE", "patient", "phone", 0.95),
    (r"\b(?:DOB|D\.O\.B\.?|Date\s+of\s+Birth|Birth\s*Date|Janm\s*Tithi|Born\s+on)" + OPT, "DOB", "patient", "dob", 0.95),
    (r"(?:जन्म\s*(?:तिथि|तारीख|दिनांक))\s*[:\-–]?\s*", "DOB", "patient", "dob", 0.95),
    (r"\b(?:Age(?:\s*/\s*Sex)?|Umar|Umr)" + SEPC, "AGE", "patient", "age", 0.9),
    (r"(?:आयु|उम्र)\s*[:\-–]?\s*", "AGE", "patient", "age", 0.9),
    (r"\b(?:Address|Addr|Add\.|Residence|Resident\s+of|R/o|Pata|Permanent\s+Address|Present\s+Address)" + SEPC,
     "ADDRESS", "patient", "address", 0.95),
    (r"(?:पता|निवास)\s*[:\-–]\s*", "ADDRESS", "patient", "address", 0.95),
    (r"\b(?:Village|Vill|Gram|Gaon|Mohalla|Locality)\.?\s*[:\-–]\s*", "VILLAGE", "patient", "village", 0.9),
    (r"(?:ग्राम|गांव|गाँव|मोहल्ला)\s*[:\-–]\s*", "VILLAGE", "patient", "village", 0.9),
    (r"\b(?:Aadhaa?r|Adhar|UID)(?:\s*(?:No|Number|Card))?\.?" + OPT, "AADHAAR", "patient", "aadhaar", 0.9),
    (r"आधार\s*(?:सं\.?|नं\.?|संख्या)?\s*[:\-–]?\s*", "AADHAAR", "patient", "aadhaar", 0.9),
    (r"\b(?:ABHA|Health\s*ID)(?:\s*(?:No|Number|Address|ID))?\.?" + OPT, "ABHA_NUMBER", "patient", "token", 0.9),
    (r"\b(?:PAN)(?:\s*(?:No|Number|Card))?\.?" + OPT, "PAN", "patient", "token", 0.9),
    (r"\b(?:Policy|Insurance|PMJAY|Ayushman|Member|Claim\s*ID)(?:\s*(?:No|Number|ID|Card))?\.?" + SEPC,
     "INSURANCE_ID", "patient", "token", 0.85),
    (r"\b(?:PIN(?:\s*Code)?|Pincode|Postal\s*Code|Zip)\.?" + OPT, "PIN", "patient", "pin", 0.9),
    (r"\b(?:E-?mail)" + OPT, "EMAIL", "patient", "token", 0.9),
]
LABELS = [(re.compile(rx, re.I if not any("ऀ" <= c <= "ॿ" for c in rx) else 0), *rest)
          for rx, *rest in LABELS]

# Relation markers: the name AFTER is a relative; the patient is the one BEFORE.
RELATION_RX = re.compile(
    r"(?<![A-Za-z])(S/o|D/o|W/o|H/o|C/o|S/O|D/O|W/O|H/O|C/O|s/o|d/o|w/o|h/o|c/o|S\.O\.|D\.O\.|W\.O\.|"
    r"[Ss]on\s+of|[Dd]aughter\s+of|[Ww]ife\s+of|[Hh]usband\s+of|[Cc]are\s+of)(?![A-Za-z])\s*[:\-]?\s*"
    r"|(?:पुत्र|पुत्री|पत्नी|पति|बेटा|बेटी|सुपुत्र|सुपुत्री)\s*(?:श्री\s*)?(?=[ऀ-ॿ])"
)
GENDER_BY_RELATION = {"s/o": "M", "son of": "M", "h/o": "M", "husband of": "M", "d/o": "F", "w/o": "F",
                      "daughter of": "F", "wife of": "F", "पुत्र": "M", "सुपुत्र": "M", "बेटा": "M", "पुत्री": "F",
                      "सुपुत्री": "F", "बेटी": "F", "पत्नी": "F"}

KINSHIP = {"bhaiya", "bhaiyya", "bhai", "chacha", "chachu", "chachi", "mama", "mami", "mausi", "bua", "dada", "dadi",
           "nana", "nani", "bhabhi", "bhabi", "uncle", "aunty", "auntie", "papa", "mummy", "beta", "beti", "jiju",
           "bhanja", "bhatija", "devar", "jeth", "saala", "sasur", "saas"}
HONORIFIC_SUFFIX_RX = re.compile(
    r"(?<![A-Za-z])(ji|jee|sahab|saheb|sahib|saab|bhai|bhaiya|bhaiyya|behenji|bahenji|behen|didi|amma|ammi|ammaji|"
    r"chacha|chachu|chachi|mama|mami|mausi|bua|dada|dadi|nana|nani|bhabhi|bhabi|uncle|aunty|madam|babu)(?![A-Za-z])",
    re.I)
HONORIFIC_SUFFIX_DEVA_RX = re.compile(r"(?<=[ऀ-ॿ])\s+(जी|साहब|बहनजी|दीदी|भैया|चाचा|अम्मा)(?![ऀ-ॿ])")
HONORIFIC_PREFIX_RX = re.compile(
    r"(?<![A-Za-z])(Shri|Sri|Shree|Smt|Shrimati|Kumari|Kum|Mr|Mrs|Ms|Miss|Master|Baby|Late|Sushri|Janab|Sardar)\.?\s+"
    r"(?=[A-Z])|(?:श्री|श्रीमती|सुश्री|कुमारी|स्व\.)\s*(?=[ऀ-ॿ])")
GENDER_BY_HONORIFIC = {"sahab": "M", "saheb": "M", "sahib": "M", "saab": "M", "bhai": "M", "bhaiya": "M",
                       "bhaiyya": "M", "behenji": "F", "bahenji": "F", "behen": "F", "didi": "F", "amma": "F",
                       "ammi": "F", "ammaji": "F", "bhabhi": "F", "madam": "F", "chacha": "M", "chachu": "M",
                       "mama": "M", "dada": "M", "nana": "M", "uncle": "M", "chachi": "F", "mami": "F", "mausi": "F",
                       "bua": "F", "dadi": "F", "nani": "F", "aunty": "F", "babu": "M", "smt": "F", "shrimati": "F",
                       "kumari": "F", "mrs": "F", "ms": "F", "miss": "F", "mr": "M", "master": "M"}

# Address grammar ------------------------------------------------------------------------------
_W = r"[A-Za-z][A-Za-z.'’]*"
_D = r"[ऀ-ॿ]+"
HOUSE_RX = re.compile(
    r"(?:\bH\.?\s?No\.?|\bHouse(?:\s*No\.?)?|\bMakan(?:\s*No\.?)?|\bPlot(?:\s*No\.?)?|\bFlat(?:\s*No\.?)?|\bQtr\.?(?:\s*No\.?)?|"
    r"\bDoor\s*No\.?|मकान\s*(?:नं\.?|नंबर|संख्या)?|म\.\s?नं\.?)\s*[:\-#]?\s*\d+[A-Za-z]?(?:\s*/\s*\d+)?", re.I)
LOCALITY_RX = re.compile(
    r"\b(?:Mohalla|Mohallah|Muhalla|Locality|Colony|Sector|Gali|Lane)\s+" + _W + r"(?:\s+" + _W + r"){0,3}"
    r"|मोहल्ला\s+" + _D + r"(?:\s+" + _D + r"){0,3}"
    r"|\b(?:Ward)\s*(?:No\.?)?\s*\d+(?!\s*\()", re.I)
LANDMARK_RX = re.compile(
    r"\b(?:near|opp\.?|opposite|behind|beside|in\s+front\s+of|next\s+to)\s+" + _W + r"(?:\s+" + _W + r"){0,4}"
    r"|" + _D + r"(?:\s+" + _D + r"){0,3}\s+के\s+(?:पास|पीछे|सामने|निकट)", re.I)
VILLAGE_RX = re.compile(
    r"\b(?:Vill(?:age)?|Gram|Gaon|Grm)\.?\s*[:\-]?\s*" + _W + r"(?:\s+" + _W + r"){0,2}"
    r"|(?:ग्राम|गांव|गाँव)\s*[:\-]?\s*" + _D + r"(?:\s+" + _D + r"){0,2}", re.I)
TEHSIL_RX = re.compile(r"\b(?:Tehsil|Teh\.?|Tahsil|Taluka|Block)\s*[:\-]?\s*" + _W + r"(?:\s+" + _W + r")?"
                       r"|(?:तहसील|ब्लॉक)\s*[:\-]?\s*" + _D, re.I)
DISTRICT_RX = re.compile(r"\b(?:Distt?\.?|District|Zila|Jila)\s*[:\-]?\s*" + _W + r"(?:\s+" + _W + r")?"
                         r"|(?:जिला|ज़िला|जनपद)\s*[:\-]?\s*" + _D, re.I)
PIN_RX = re.compile(r"(?<![\d])[1-9]\d{5}(?![\d])")
VILLAGE_SUFFIX_RX = re.compile(
    r"(?:pur|ganj|nagar|abad|garh|mau|dih|pura|purwa|gaon|kot|khera|khurd|kalan|patti|tola|bazar|tal|pali)$", re.I)
