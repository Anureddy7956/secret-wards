"""Small helpers for tests and interactive checks (not used by the pipeline)."""
from __future__ import annotations

from collections import Counter

from .config import load_policy
from .detect.normalize import normalize_text
from .detect.text_detector import Context, Learned, detect
from .write.render import RecordView, render_text


def sanitize_text(text: str, pid: str | None = "PSN-TEST01", shift: int = 10, order: str = "dmy",
                  learned: Learned | None = None, level: str = "state") -> str:
    text = normalize_text(text)
    spans = detect(text, Context(learned or Learned()))
    view = RecordView(pid, shift, None, order, level, load_policy(), [], Counter())
    return render_text(text, spans, view)
