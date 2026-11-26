"""Rare quasi-identifier values (diagnoses / procedures held by very few patients).  Filled in at M5."""
from __future__ import annotations


def plan(pipe, policy) -> dict:
    return {"codes": {}}


def apply(pipe, rec, text: str) -> str:
    return text
