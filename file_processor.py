"""
Unified file processing pipeline for contact extraction.

Supports: CSV, PDF (text-based + scanned), Images (JPG, PNG, GIF, BMP, TIFF)

Pipeline:
    UploadedFile → FileTypeDetector → ContactExtractor → ContactNormalizer → List[Contact]
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from csv_parser import CSVParseError, parse_csv  # re-export CSVParseError for consumers
from ocr_parser import (
    extract_contacts_from_text,
    ocr_image_file,
    parse_pdf_text,
    parse_pdf_with_ocr,
)

logger = logging.getLogger(__name__)

__all__ = [
    "Contact",
    "CSVParseError",
    "FileTypeDetector",
    "ContactExtractor",
    "ContactNormalizer",
    "process_file",
]

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif"}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Contact:
    phone: str          # E.164 normalised
    name: str = ""
    company: str = ""
    email: str = ""
    source: str = ""


# ── File type detection ───────────────────────────────────────────────────────

class FileTypeDetector:
    """Detect the logical type of an uploaded file."""

    def detect(self, filename: str, file_bytes: bytes) -> str:
        """Return one of: 'csv', 'pdf-text', 'pdf-scan', 'image'.

        For PDFs, pdfplumber is used to determine whether the file contains
        extractable text (pdf-text) or is image-based (pdf-scan).
        """
        ext = Path(filename).suffix.lower()

        if ext == ".csv":
            return "csv"

        if ext in _IMAGE_EXTENSIONS:
            return "image"

        if ext == ".pdf":
            _, is_image_based = parse_pdf_text(file_bytes)
            return "pdf-scan" if is_image_based else "pdf-text"

        # Fallback: treat unknown extensions as image (OCR attempt)
        logger.warning("Unknown file extension '%s', treating as image", ext)
        return "image"


# ── Contact extraction ────────────────────────────────────────────────────────

class ContactExtractor:
    """Extract raw Contact objects from various file types."""

    def extract_from_csv(self, file_bytes: bytes) -> tuple[list[Contact], list[str]]:
        """Parse CSV bytes using the existing csv_parser.

        Returns (contacts, warnings).
        Raises CSVParseError on unrecoverable parse failures.
        """
        result = parse_csv(io.BytesIO(file_bytes))
        contacts = [
            Contact(
                phone=lead.phone,
                name=lead.name,
                company=lead.company,
                email=lead.extra.get("email", ""),
                source="csv",
            )
            for lead in result.leads
        ]
        return contacts, result.warnings

    def extract_from_text(self, text: str) -> list[Contact]:
        """Extract contacts from raw OCR / PDF text.

        Uses ocr_parser.extract_contacts_from_text and converts dicts to Contact.
        """
        raw = extract_contacts_from_text(text)
        return [
            Contact(
                phone=d.get("phone", ""),
                name=d.get("name", ""),
                company=d.get("company", ""),
                email=d.get("email", ""),
                source=d.get("source", "ocr"),
            )
            for d in raw
            if d.get("phone")
        ]

    def extract_from_image(self, file_bytes: bytes) -> tuple[list[Contact], list[str]]:
        """OCR an image file and extract contacts.

        Returns (contacts, warnings).
        """
        warnings: list[str] = []
        try:
            text = ocr_image_file(file_bytes)
        except Exception as exc:
            warnings.append(f"Image OCR failed: {exc}")
            return [], warnings

        if not text.strip():
            warnings.append("OCR produced no text from image.")
            return [], warnings

        contacts = self.extract_from_text(text)
        if not contacts:
            warnings.append("No contacts found in OCR text.")
        return contacts, warnings

    def extract_from_pdf(
        self, file_bytes: bytes
    ) -> tuple[list[Contact], list[str], str]:
        """Extract contacts from a PDF, trying text extraction first.

        Falls back to OCR if the PDF is image-based or text extraction yields
        too little content.

        Returns (contacts, warnings, method) where method is 'pdf-text' or 'pdf-scan'.
        """
        warnings: list[str] = []

        text, is_image_based = parse_pdf_text(file_bytes)

        if not is_image_based and text.strip():
            contacts = self.extract_from_text(text)
            if contacts:
                return contacts, warnings, "pdf-text"
            # Text extracted but no contacts found — try OCR as fallback
            warnings.append(
                "PDF text extraction found no contacts; falling back to OCR."
            )

        # OCR path
        try:
            ocr_text = parse_pdf_with_ocr(file_bytes)
        except Exception as exc:
            warnings.append(f"PDF OCR failed: {exc}")
            return [], warnings, "pdf-scan"

        if not ocr_text.strip():
            warnings.append("PDF OCR produced no text.")
            return [], warnings, "pdf-scan"

        contacts = self.extract_from_text(ocr_text)
        if not contacts:
            warnings.append("No contacts found in PDF OCR text.")
        return contacts, warnings, "pdf-scan"


# ── Phone normalisation ───────────────────────────────────────────────────────

def _region_from_language(language: str) -> str:
    """Derive a two-letter region code from a BCP-47 language tag.

    Examples: 'en-IN' → 'IN', 'en-US' → 'US', 'hi' → 'IN' (default).
    """
    if "-" in language:
        return language.split("-")[-1].upper()
    return "IN"


class ContactNormalizer:
    """Normalise phone numbers to E.164 and deduplicate contacts."""

    def normalize(
        self,
        contacts: list[Contact],
        default_region: str | None = None,
    ) -> tuple[list[Contact], list[str]]:
        """Normalise phones to E.164, dedup by phone, return (contacts, warnings).

        default_region defaults to the region derived from config.AGENT_LANGUAGE.
        """
        try:
            import phonenumbers
        except ImportError:
            logger.warning("phonenumbers library not installed; skipping normalisation")
            return contacts, ["phonenumbers library not installed; phones not normalised"]

        if default_region is None:
            default_region = _region_from_language(config.AGENT_LANGUAGE)

        normalised: list[Contact] = []
        warnings: list[str] = []
        seen_phones: set[str] = set()

        for contact in contacts:
            raw_phone = contact.phone.strip()
            if not raw_phone:
                warnings.append(f"Contact '{contact.name}' has an empty phone; skipped.")
                continue

            try:
                parsed = phonenumbers.parse(raw_phone, default_region)
                if not phonenumbers.is_valid_number(parsed):
                    warnings.append(
                        f"Phone '{raw_phone}' is not a valid number; skipped."
                    )
                    continue
                e164 = phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
            except phonenumbers.NumberParseException as exc:
                warnings.append(f"Could not parse phone '{raw_phone}': {exc}; skipped.")
                continue

            if e164 in seen_phones:
                warnings.append(f"Duplicate phone '{e164}'; keeping first occurrence.")
                continue

            seen_phones.add(e164)
            normalised.append(
                Contact(
                    phone=e164,
                    name=contact.name,
                    company=contact.company,
                    email=contact.email,
                    source=contact.source,
                )
            )

        return normalised, warnings


# ── Top-level pipeline ────────────────────────────────────────────────────────

_detector = FileTypeDetector()
_extractor = ContactExtractor()
_normalizer = ContactNormalizer()


def process_file(
    file_bytes: bytes,
    filename: str,
) -> tuple[list[Contact], list[str], str]:
    """Unified file processing pipeline.

    Orchestrates: detect → extract → normalize.

    Returns:
        (contacts, warnings, method) where method is one of:
        'csv', 'pdf-text', 'pdf-scan', 'image'.

    Partial failures surface as warnings, not hard errors.
    """
    all_warnings: list[str] = []

    # 1. Detect file type
    file_type = _detector.detect(filename, file_bytes)

    # 2. Extract contacts
    contacts: list[Contact] = []
    method = file_type

    try:
        if file_type == "csv":
            contacts, extract_warnings = _extractor.extract_from_csv(file_bytes)
            all_warnings.extend(extract_warnings)

        elif file_type in ("pdf-text", "pdf-scan"):
            contacts, extract_warnings, method = _extractor.extract_from_pdf(file_bytes)
            all_warnings.extend(extract_warnings)

        elif file_type == "image":
            contacts, extract_warnings = _extractor.extract_from_image(file_bytes)
            all_warnings.extend(extract_warnings)

        else:
            all_warnings.append(f"Unsupported file type detected: '{file_type}'")
            return [], all_warnings, file_type

    except CSVParseError:
        raise  # let callers handle typed CSV errors
    except Exception as exc:
        all_warnings.append(f"Extraction failed for '{filename}': {exc}")
        return [], all_warnings, method

    # 3. Normalise phones and dedup
    normalised, norm_warnings = _normalizer.normalize(contacts)
    all_warnings.extend(norm_warnings)

    return normalised, all_warnings, method
