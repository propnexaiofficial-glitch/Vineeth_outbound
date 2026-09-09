"""
Real-time lead info extractor.

Parses transcript text (Hinglish + English) for qualifying signals:
budget, location, timeline, property type, BHK, team size, current CRM,
pain points, callback time, demo requests.

No external API calls — pure regex + keyword matching so it runs inline
on every transcript chunk without adding latency.
"""
from __future__ import annotations

import re
from lead_info import LeadInfo

# ── Budget ────────────────────────────────────────────────────────────────────
# Matches: "50 lakh", "1.5 crore", "50L", "1Cr", "50,000", "budget 30-50 lakh"
_BUDGET_RE = re.compile(
    r"(?:budget|price|cost|kitna|kitne|afford|spend|invest)[^\d]{0,20}"
    r"(\d[\d,\.]*)\s*(?:se\s*(\d[\d,\.]*)\s*)?"
    r"(lakh|lac|l\b|crore|cr\b|k\b|thousand)?",
    re.IGNORECASE,
)
_STANDALONE_BUDGET_RE = re.compile(
    r"(\d[\d,\.]*)\s*(?:se\s*(\d[\d,\.]*)\s*)?"
    r"(lakh|lac|l\b|crore|cr\b)",
    re.IGNORECASE,
)


def _to_inr(value: str, unit: str) -> int:
    v = float(value.replace(",", ""))
    unit = (unit or "").lower().strip()
    if unit in ("crore", "cr"):
        return int(v * 1_00_00_000)
    if unit in ("lakh", "lac", "l"):
        return int(v * 1_00_000)
    if unit in ("k", "thousand"):
        return int(v * 1_000)
    return int(v)


def _extract_budget(text: str) -> tuple[int | None, int | None]:
    for pattern in (_BUDGET_RE, _STANDALONE_BUDGET_RE):
        m = pattern.search(text)
        if m:
            groups = m.groups()
            low_str, high_str, unit = groups[0], groups[1], groups[2]
            try:
                low = _to_inr(low_str, unit)
                high = _to_inr(high_str, unit) if high_str else None
                return (low, high) if high else (low, low)
            except (ValueError, TypeError):
                continue
    return None, None


# ── Location ──────────────────────────────────────────────────────────────────
_LOCATION_KEYWORDS = [
    "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai",
    "pune", "kolkata", "ahmedabad", "surat", "jaipur", "lucknow", "noida",
    "gurgaon", "gurugram", "thane", "navi mumbai", "chandigarh", "indore",
    "bhopal", "nagpur", "vadodara", "coimbatore", "kochi", "vizag",
    "visakhapatnam", "patna", "agra", "varanasi", "meerut", "faridabad",
]
_LOCATION_RE = re.compile(
    r"(?:location|area|city|jagah|kahan|where|place|sector|locality)[^\w]{0,10}"
    r"([A-Za-z][A-Za-z\s]{2,25})",
    re.IGNORECASE,
)


def _extract_location(text: str) -> str | None:
    lower = text.lower()
    for city in _LOCATION_KEYWORDS:
        if city in lower:
            return city.title()
    m = _LOCATION_RE.search(text)
    if m:
        return m.group(1).strip().title()
    return None


# ── Timeline ──────────────────────────────────────────────────────────────────
_TIMELINE_RE = re.compile(
    r"(\d+\s*(?:month|mahine|week|hafte|year|saal|din|day)s?)"
    r"|(?:immediate|abhi|jaldi|urgent|asap|next\s+(?:month|week|quarter))",
    re.IGNORECASE,
)


def _extract_timeline(text: str) -> str | None:
    m = _TIMELINE_RE.search(text)
    return m.group(0).strip() if m else None


# ── Property type ─────────────────────────────────────────────────────────────
_PROPERTY_TYPES = {
    "flat": "Flat", "apartment": "Flat", "flats": "Flat",
    "villa": "Villa", "bungalow": "Villa",
    "plot": "Plot", "land": "Plot",
    "office": "Office", "commercial": "Office", "shop": "Office",
    "warehouse": "Warehouse", "godown": "Warehouse",
    "row house": "Row House", "rowhouse": "Row House",
    "studio": "Studio",
}


def _extract_property_type(text: str) -> str | None:
    lower = text.lower()
    for keyword, label in _PROPERTY_TYPES.items():
        if keyword in lower:
            return label
    return None


# ── BHK ───────────────────────────────────────────────────────────────────────
_BHK_RE = re.compile(r"(\d)\s*(?:bhk|bedroom|bed room|rk)", re.IGNORECASE)


def _extract_bhk(text: str) -> str | None:
    m = _BHK_RE.search(text)
    return f"{m.group(1)}BHK" if m else None


# ── Team size ─────────────────────────────────────────────────────────────────
_TEAM_RE = re.compile(
    r"(\d+)\s*(?:log|logon|member|person|people|employee|staff|sales\s*(?:person|rep))",
    re.IGNORECASE,
)


def _extract_team_size(text: str) -> int | None:
    m = _TEAM_RE.search(text)
    return int(m.group(1)) if m else None


# ── Current CRM ───────────────────────────────────────────────────────────────
_CRM_NAMES = [
    "salesforce", "hubspot", "zoho", "freshsales", "pipedrive",
    "leadsquared", "cratio", "kylas", "excel", "spreadsheet",
    "google sheet", "notion", "tally",
]


def _extract_current_crm(text: str) -> str | None:
    lower = text.lower()
    for crm in _CRM_NAMES:
        if crm in lower:
            return crm.title()
    return None


# ── Pain points ───────────────────────────────────────────────────────────────
_PAIN_KEYWORDS = {
    "follow up": "Follow-up management",
    "follow-up": "Follow-up management",
    "lead track": "Lead tracking",
    "leads track": "Lead tracking",
    "miss": "Missing leads/follow-ups",
    "manual": "Manual processes",
    "excel": "Using Excel/spreadsheets",
    "reporting": "Reporting issues",
    "report": "Reporting issues",
    "slow": "Slow processes",
    "expensive": "Cost concerns",
    "costly": "Cost concerns",
    "team coordination": "Team coordination",
    "reminder": "Reminder management",
    "data loss": "Data loss",
}


def _extract_pain_points(text: str) -> list[str]:
    lower = text.lower()
    found = []
    for keyword, label in _PAIN_KEYWORDS.items():
        if keyword in lower and label not in found:
            found.append(label)
    return found


# ── Callback time ─────────────────────────────────────────────────────────────
_CALLBACK_RE = re.compile(
    r"(?:call\s*(?:me\s*)?(?:back)?|callback|baad\s*mein|phir\s*se)\s*"
    r"((?:tomorrow|kal|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"morning|evening|afternoon|subah|shaam|\d{1,2}(?::\d{2})?\s*(?:am|pm|baje)))",
    re.IGNORECASE,
)


def _extract_callback_time(text: str) -> str | None:
    m = _CALLBACK_RE.search(text)
    return m.group(1).strip() if m else None


# ── Demo request ──────────────────────────────────────────────────────────────
_DEMO_RE = re.compile(
    r"\b(demo|free trial|trial|dikhaiye|dikhao|show me|presentation)\b",
    re.IGNORECASE,
)


def _extract_demo_requested(text: str) -> bool:
    return bool(_DEMO_RE.search(text))


# ── Public API ────────────────────────────────────────────────────────────────

def extract_from_chunk(lead_id: str, text: str) -> LeadInfo:
    """
    Extract all qualifying signals from a single transcript chunk.
    Returns a LeadInfo with only the fields found in this chunk populated.
    Fields not found are left as None / empty so the upsert COALESCE logic
    preserves previously extracted values.
    """
    budget_min, budget_max = _extract_budget(text)
    pain_points = _extract_pain_points(text)

    return LeadInfo(
        lead_id=lead_id,
        budget_min=budget_min,
        budget_max=budget_max,
        location=_extract_location(text),
        timeline=_extract_timeline(text),
        property_type=_extract_property_type(text),
        bhk=_extract_bhk(text),
        team_size=_extract_team_size(text),
        current_crm=_extract_current_crm(text),
        pain_points=pain_points,
        callback_time=_extract_callback_time(text),
        demo_requested=_extract_demo_requested(text),
    )


def missing_fields(info: LeadInfo) -> list[str]:
    """Return a list of field names that are still unknown for this lead."""
    gaps = []
    if info.budget_min is None:
        gaps.append("budget")
    if info.location is None:
        gaps.append("location")
    if info.timeline is None:
        gaps.append("timeline")
    if info.property_type is None:
        gaps.append("property_type")
    if info.team_size is None:
        gaps.append("team_size")
    return gaps
