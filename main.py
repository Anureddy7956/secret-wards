#!/usr/bin/env python3
"""Raksha privacy firewall - CLI entry point.

    python main.py --input <input dir> --output <output dir>

Reads RAKSHA_SECRET from the environment (never printed, logged or written). Errors are reported
with exception class names only, so no record content can leak through a traceback.
"""
from __future__ import annotations

import argparse
import os
import sys


def _quiet_excepthook(exc_type, exc, tb):  # pragma: no cover - last line of defence
    sys.stderr.write(f"raksha: fatal {exc_type.__name__}; aborting\n")


def main() -> int:
    sys.excepthook = _quiet_excepthook
    ap = argparse.ArgumentParser(description="Raksha: offline privacy firewall for hospital records")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--policy", default=None, help="path to policy.yaml (default config/policy.yaml)")
    a = ap.parse_args()

    from raksha.security.safe_log import log
    secret = os.environ.get("RAKSHA_SECRET", "")
    if not secret:
        log("no_secret")
        return 2
    try:
        from raksha.config import load_policy
        from raksha.pipeline import run
        log("start")
        report = run(a.input, a.output, load_policy(a.policy), secret.encode("utf-8"))
        c = report["counts"]
        log("summary", files=c["files_total"], sanitized=c["files_sanitized"], quarantined=c["files_quarantined"],
            records=c["records_processed"], linked=c["records_linked"])
        return 0
    except Exception as exc:  # noqa: BLE001
        log("fatal", exc=type(exc).__name__, stage="main")
        return 1


if __name__ == "__main__":
    sys.exit(main())
