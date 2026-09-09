"""CSV parsing utilities for the Bulk Lead Dialer Campaign System."""

from __future__ import annotations

import csv
import io
import uuid
from typing import IO

from campaign_models import Lead, LeadStatus, ParseResult


class CSVParseError(Exception):
    """Raised when the uploaded file cannot be parsed as a valid CSV."""


def parse_csv(file: IO[bytes]) -> ParseResult:
    """Parse a CSV file-like object into a ParseResult.

    Args:
        file: A binary file-like object containing CSV data.

    Returns:
        ParseResult with leads, skipped_rows, warnings, and original_columns.

    Raises:
        CSVParseError: If the file cannot be decoded or parsed as CSV,
                       or if the required `phone` column is missing.
    """
    try:
        raw = file.read()
        text = raw.decode("utf-8-sig")  # handle optional BOM
    except (UnicodeDecodeError, Exception) as exc:
        raise CSVParseError(f"File could not be decoded as UTF-8 text: {exc}") from exc

    try:
        reader = csv.DictReader(io.StringIO(text))
        # Force reading the fieldnames to detect parse issues early
        fieldnames = reader.fieldnames
    except Exception as exc:
        raise CSVParseError(f"File could not be parsed as CSV: {exc}") from exc

    if fieldnames is None:
        raise CSVParseError("CSV file is empty or has no header row.")

    original_columns: list[str] = list(fieldnames)

    # Build a case-insensitive mapping from lowercased header → original header
    lower_to_original: dict[str, str] = {col.lower(): col for col in original_columns}

    phone_key = lower_to_original.get("phone")
    if phone_key is None:
        raise CSVParseError(
            "Required column 'phone' is missing from the CSV header."
        )

    name_key = lower_to_original.get("name")
    company_key = lower_to_original.get("company")

    # Columns that are handled explicitly; the rest go into `extra`
    known_keys = {k for k in (phone_key, name_key, company_key) if k is not None}

    leads: list[Lead] = []
    skipped_rows: list[dict] = []
    warnings: list[str] = []

    try:
        rows = list(reader)
    except Exception as exc:
        raise CSVParseError(f"Error reading CSV rows: {exc}") from exc

    for row_index, row in enumerate(rows, start=2):  # row 1 is the header
        phone_value = (row.get(phone_key) or "").strip()
        if not phone_value:
            skipped_rows.append(dict(row))
            warnings.append(
                f"Row {row_index}: skipped because 'phone' value is empty or missing."
            )
            continue

        name_value = (row.get(name_key) or "").strip() if name_key else ""
        company_value = (row.get(company_key) or "").strip() if company_key else ""

        extra: dict[str, str] = {
            col: (row.get(col) or "")
            for col in original_columns
            if col not in known_keys
        }

        lead = Lead(
            lead_id=str(uuid.uuid4()),
            name=name_value,
            phone=phone_value,
            company=company_value,
            extra=extra,
            status=LeadStatus.PENDING,
        )
        leads.append(lead)

    return ParseResult(
        leads=leads,
        skipped_rows=skipped_rows,
        warnings=warnings,
        original_columns=original_columns,
    )
