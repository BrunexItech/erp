"""CSV import/export helpers shared by every module that bulk-loads data.

Imports are deliberately not all-or-nothing: one typo in row 212 shouldn't
throw away 400 good rows. Each row is validated
on its own and the caller gets back a report: how many were created, how many
updated, and exactly which rows failed and why.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, UploadFile, status
from fastapi.responses import Response

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000


@dataclass
class ImportReport:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[dict] = field(default_factory=list)  # [{"row": 12, "error": "..."}]

    def fail(self, row: int, error: str) -> None:
        self.skipped += 1
        if len(self.errors) < 200:
            self.errors.append({"row": row, "error": error})

    def as_dict(self) -> dict:
        return {"created": self.created, "updated": self.updated, "skipped": self.skipped, "errors": self.errors}


async def read_rows(file: UploadFile, required: list[str]) -> list[tuple[int, dict[str, str]]]:
    """Returns [(spreadsheet_row_number, {header: value})]. Headers are matched
    case-insensitively with spaces treated as underscores, so "Sale Price"
    works as well as "sale_price"."""
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file is larger than 5 MB")
    try:
        text = data.decode("utf-8-sig")  # Excel writes a BOM
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        headers = [h.strip().lower().replace(" ", "_") for h in next(reader)]
    except StopIteration:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the file is empty")
    missing = [c for c in required if c not in headers]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"missing column(s): {', '.join(missing)} — download the template to see the expected layout",
        )
    rows = []
    for number, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue
        if len(rows) >= MAX_ROWS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"too many rows — import at most {MAX_ROWS:,} at a time")
        rows.append((number, {h: (values[i].strip() if i < len(values) else "") for i, h in enumerate(headers)}))
    return rows


def decimal_of(value: str, *, default: Decimal | None = None, label: str = "number") -> Decimal:
    value = value.replace(",", "").strip()
    if not value:
        if default is None:
            raise ValueError(f"{label} is required")
        return default
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{label} '{value}' is not a number")
    if number < 0:
        raise ValueError(f"{label} can't be negative")
    return number


def rate_of(value: str, *, default: Decimal = Decimal("0")) -> Decimal:
    """VAT as people write it: "16", "16%" or "0.16" all mean 16%."""
    value = value.replace("%", "").strip()
    if not value:
        return default
    rate = decimal_of(value, label="tax rate")
    if rate > 1:
        rate = rate / 100
    if rate > 1:
        raise ValueError("tax rate can't exceed 100%")
    return rate


def bool_of(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "y", "x")


def csv_response(filename: str, headers: list[str], rows: list[list]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    # BOM so Excel opens UTF-8 (names with accents, KES symbols) correctly.
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
