"""Shared AR/AP aging buckets (Sage's 'Current / 1-30 / 31-60 / 61-90 / Over 90')."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

BUCKETS = ("current", "days_1_30", "days_31_60", "days_61_90", "over_90")


def bucket_for(due_date: date | None, as_of: date) -> str:
    if due_date is None or due_date >= as_of:
        return "current"
    overdue = (as_of - due_date).days
    if overdue <= 30:
        return "days_1_30"
    if overdue <= 60:
        return "days_31_60"
    if overdue <= 90:
        return "days_61_90"
    return "over_90"


def empty_buckets() -> dict[str, Decimal]:
    return {b: Decimal("0") for b in BUCKETS}
