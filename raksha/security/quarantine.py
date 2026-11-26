"""Quarantine decisions. Quarantined files are never copied anywhere; only their hash and a
reason code from this fixed list go into report.json."""
REASONS = {
    "unsupported_format", "empty_file", "undecodable_text", "malformed_json", "nesting_too_deep",
    "binary_content", "too_large", "processing_error", "malformed_csv",
}


class Quarantine(Exception):
    def __init__(self, reason: str):
        super().__init__(reason if reason in REASONS else "processing_error")
        self.reason = reason if reason in REASONS else "processing_error"
