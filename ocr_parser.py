"""
OCR and file parsing utilities.
Supports: CSV, PDF (text-based + scanned), Images (JPG, PNG, GIF, BMP, TIFF)

Dependencies (install as needed):
  pip install pdfplumber pytesseract Pillow
  System: tesseract-ocr must be installed
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)


# ── Contact extraction from raw text ─────────────────────────────────────────

_PHONE_PATTERNS = [
    re.compile(r'\+?91[-.\s]?([6-9]\d{9})'),          # Indian mobile
    re.compile(r'\+?1[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'),  # US
    re.compile(r'\+?(\d{1,4}[-.\s]?)?\(?\d{3,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{4}'),  # International
    re.compile(r'\b\d{10}\b'),                          # bare 10-digit
]
_NAME_PATTERN = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
_EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')


def _clean_phone(raw: str) -> str:
    digits = re.sub(r'[^\d+]', '', raw)
    if not digits.startswith('+'):
        if len(digits) == 10:
            digits = '+91' + digits   # assume India
        elif len(digits) > 10:
            digits = '+' + digits
    return digits


def extract_contacts_from_text(text: str) -> list[dict]:
    """Extract name/phone pairs from raw OCR or PDF text."""
    phones: list[str] = []
    seen: set[str] = set()
    for pat in _PHONE_PATTERNS:
        for m in pat.finditer(text):
            cleaned = _clean_phone(m.group(0))
            if len(cleaned) >= 10 and cleaned not in seen:
                seen.add(cleaned)
                phones.append(cleaned)

    if not phones:
        return []

    lines = text.splitlines()
    contacts: list[dict] = []

    for phone in phones:
        raw_digits = re.sub(r'[^\d]', '', phone)
        name = ''
        email = ''
        for i, line in enumerate(lines):
            if raw_digits in re.sub(r'[^\d]', '', line):
                # look for name in same / adjacent lines
                for j in range(max(0, i - 2), min(len(lines), i + 3)):
                    nm = _NAME_PATTERN.search(lines[j])
                    if nm:
                        name = nm.group(0)
                        break
                em = _EMAIL_PATTERN.search(line)
                if em:
                    email = em.group(0)
                break

        contacts.append({'phone': phone, 'name': name, 'email': email, 'source': 'OCR'})

    return contacts


def extract_business_card(text: str) -> dict:
    """Extract structured info from a business card OCR result."""
    info: dict = {'name': '', 'phone': '', 'email': '', 'company': '', 'title': ''}

    em = _EMAIL_PATTERN.search(text)
    if em:
        info['email'] = em.group(0)

    for pat in _PHONE_PATTERNS:
        pm = pat.search(text)
        if pm:
            info['phone'] = _clean_phone(pm.group(0))
            break

    nm = _NAME_PATTERN.search(text)
    if nm:
        info['name'] = nm.group(0)

    company_pat = re.compile(
        r'\b([A-Z][a-zA-Z\s&]+(?:Inc|LLC|Corp|Company|Co\.|Ltd|Limited|Pvt|Technologies|Solutions|Services))\b'
    )
    cm = company_pat.search(text)
    if cm:
        info['company'] = cm.group(0)

    title_pat = re.compile(
        r'\b(CEO|CTO|CFO|COO|President|Director|Manager|VP|Vice President|Senior|Lead|Head of|Founder)[^\n.]*',
        re.IGNORECASE,
    )
    tm = title_pat.search(text)
    if tm:
        info['title'] = tm.group(0).strip()

    return info


# ── PDF parsing ───────────────────────────────────────────────────────────────

def parse_pdf_text(file_bytes: bytes) -> tuple[str, bool]:
    """
    Extract text from a PDF.
    Returns (text, is_image_based).
    is_image_based=True means OCR is needed.
    """
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ''
                text_parts.append(t)
        full_text = '\n'.join(text_parts)
        avg_per_page = len(full_text.strip()) / max(len(text_parts), 1)
        is_image_based = avg_per_page < 50
        return full_text, is_image_based
    except ImportError:
        logger.warning('pdfplumber not installed, falling back to OCR for PDF')
        return '', True
    except Exception as e:
        logger.warning(f'PDF text extraction failed: {e}')
        return '', True


def parse_pdf_with_ocr(file_bytes: bytes) -> str:
    """Convert PDF pages to images and OCR each page."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype='pdf')
        all_text = []
        for page_num, page in enumerate(doc):
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better OCR
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            img_bytes = pix.tobytes('png')
            page_text = _ocr_image_bytes(img_bytes)
            all_text.append(f'--- Page {page_num + 1} ---\n{page_text}')
        return '\n'.join(all_text)
    except ImportError:
        logger.warning('PyMuPDF (fitz) not installed, cannot OCR PDF pages')
        return ''
    except Exception as e:
        logger.error(f'PDF OCR failed: {e}')
        return ''


# ── Image OCR ─────────────────────────────────────────────────────────────────

def _ocr_image_bytes(img_bytes: bytes) -> str:
    """Run Tesseract OCR on raw image bytes."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes))
        # Preprocess: grayscale + resize for better accuracy
        img = img.convert('L')
        w, h = img.size
        if w < 1000:
            scale = 1000 / w
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        return pytesseract.image_to_string(img, lang='eng')
    except ImportError:
        logger.warning('pytesseract or Pillow not installed — OCR unavailable')
        return ''
    except Exception as e:
        logger.error(f'OCR failed: {e}')
        return ''


def ocr_image_file(file_bytes: bytes) -> str:
    """OCR an image file (JPG, PNG, etc.)."""
    return _ocr_image_bytes(file_bytes)


# ── Unified file parser ───────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {'.csv', '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif'}


def parse_file_to_contacts(
    file_bytes: bytes,
    filename: str,
) -> tuple[list[dict], str]:
    """
    Parse any supported file type into a list of contact dicts.
    Returns (contacts, processing_method).
    Each contact: {'phone': str, 'name': str, 'company': str, 'email': str, 'source': str}
    """
    ext = Path(filename).suffix.lower()

    if ext == '.csv':
        return _parse_csv_bytes(file_bytes), 'CSV'

    elif ext == '.pdf':
        text, is_image = parse_pdf_text(file_bytes)
        if is_image or not text.strip():
            logger.info('PDF is image-based, using OCR')
            text = parse_pdf_with_ocr(file_bytes)
            method = 'PDF OCR'
        else:
            method = 'PDF Text'
        contacts = extract_contacts_from_text(text)
        return contacts, method

    elif ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif'}:
        text = ocr_image_file(file_bytes)
        # Check if it looks like a business card (single contact)
        bc = extract_business_card(text)
        if bc['phone'] and bc['name']:
            return [{'phone': bc['phone'], 'name': bc['name'],
                     'company': bc['company'], 'email': bc['email'], 'source': 'BUSINESS_CARD_OCR'}], 'Business Card OCR'
        contacts = extract_contacts_from_text(text)
        return contacts, 'Image OCR'

    else:
        raise ValueError(f'Unsupported file type: {ext}. Supported: CSV, PDF, JPG, PNG, GIF, BMP, TIFF')


def _parse_csv_bytes(file_bytes: bytes) -> list[dict]:
    """Parse CSV bytes into contact dicts."""
    import csv
    text = file_bytes.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(text))
    contacts = []
    for row in reader:
        lower = {k.lower(): v for k, v in row.items()}
        phone = (lower.get('phone') or lower.get('contact_number') or
                 lower.get('phone_number') or lower.get('number') or '').strip()
        if not phone:
            continue
        contacts.append({
            'phone': phone,
            'name': (lower.get('name') or lower.get('first_name') or lower.get('full_name') or '').strip(),
            'company': (lower.get('company') or '').strip(),
            'email': (lower.get('email') or '').strip(),
            'source': 'CSV',
        })
    return contacts
