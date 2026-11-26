"""FHIR R4 path rules: which element of which resource holds what. Falls back to generic key rules."""
from __future__ import annotations

DATE_KEYS = {"effectiveDateTime", "authoredOn", "recordedDate", "performedDateTime", "onsetDateTime", "issued",
             "date", "timestamp", "lastUpdated", "start", "end", "occurrenceDateTime", "abatementDateTime",
             "created", "birthDate", "deceasedDateTime", "valueDateTime", "dateAsserted", "whenHandedOver"}
KEEP_KEYS = {"id", "fullUrl", "reference", "system", "code", "url", "status", "use", "resourceType", "type",
             "intent", "unit", "contentType", "language", "profile", "versionId", "div_status", "gender"}
KEEP_RESOURCES = {"Practitioner", "PractitionerRole", "Organization", "Location", "Medication", "HealthcareService"}


def fhir_class(resource_type: str | None, rpath: tuple, resource: dict | None = None) -> str | None:
    """rpath is the path inside the resource (strings only, list indices removed)."""
    if not rpath:
        return None
    last = rpath[-1]
    if last in ("lastUpdated",) or (rpath[:1] == ("meta",) and last != "source"):
        return "KEEP" if last != "lastUpdated" else "DATE_META"
    if rpath[:1] == ("meta",) and last == "source":
        return "TEXT"
    if last in ("id", "fullUrl", "reference", "system", "url", "resourceType", "status", "intent", "use",
                "contentType", "language", "profile", "unit") or (last == "code" and "attachment" not in rpath):
        return "KEEP"
    if rpath[-2:] == ("text", "div"):
        return "TEXT"
    if last == "data" and "attachment" in rpath:
        return "BASE64"
    if resource_type in KEEP_RESOURCES:
        return "DATE" if last in DATE_KEYS else "KEEP"
    if last == "display" and len(rpath) >= 2 and rpath[-2] in ("subject", "patient", "beneficiary"):
        return "PATIENT_NAME"
    if last == "display" and len(rpath) >= 2 and rpath[-2] in ("author", "performer", "requester", "practitioner",
                                                                 "serviceProvider", "custodian", "organization"):
        return "KEEP"
    if resource_type in ("Patient", "RelatedPerson", "Person"):
        rel = resource_type == "RelatedPerson"
        if "contact" in rpath:
            if "name" in rpath:
                return "RELATIVE_NAME"
            if "telecom" in rpath and last == "value":
                return "PHONE"
            if "address" in rpath:
                return "ADDRESS"
            if "relationship" in rpath:
                return "KEEP"
        if "extension" in rpath:
            if last.startswith("value") and resource is not None:
                return "EXT"
            return "KEEP"
        if rpath[0] == "name":
            if last == "text":
                return "RELATIVE_NAME" if rel else "PATIENT_NAME"
            if last in ("given", "family", "prefix", "suffix"):
                return "RELATIVE_NAME" if rel else "NAME_PART"
        if rpath[0] == "telecom" and last == "value":
            return "PHONE"
        if rpath[0] == "identifier" and last == "value":
            return "IDENT"
        if rpath[0] == "address":
            return {"line": "ADDRESS", "text": "ADDRESS", "city": "VILLAGE", "district": "DISTRICT",
                    "postalCode": "PIN", "state": "STATE", "country": "KEEP"}.get(last, "ADDRESS")
        if last == "birthDate":
            return "DOB"
        if last == "gender":
            return "GENDER"
    if rpath[0] == "identifier" and last == "value":
        return "IDENT"
    if last in DATE_KEYS:
        return "DATE"
    return None


def ident_class(system: str | None, type_code: str | None) -> str:
    s = (system or "").lower()
    t = (type_code or "").upper()
    if "abdm" in s or "healthid" in s or "abha" in s or "ndhm" in s:
        return "ABHA_NUMBER"
    if "aadhaar" in s or "aadhar" in s or "uidai" in s:
        return "AADHAAR"
    if "pan" in s.split("/")[-1:] or t == "TAX":
        return "PAN"
    if "insurance" in s or "pmjay" in s or "policy" in s:
        return "INSURANCE_ID"
    if "phone" in s or "mobile" in s:
        return "PHONE"
    return "MRN"
