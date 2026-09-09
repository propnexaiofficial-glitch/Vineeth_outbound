"""
EnquiryInfo -- school-admissions equivalent of the real-estate LeadInfo.

Holds everything extracted live from a call transcript that eventually
needs to reach SchoolKnot via insert_enquiry_service (r_type 1-4), plus
the Secondary/Tertiary outcome signals from the integration spec that
don't have a dedicated field on the real API yet (fee/brochure requests,
budget-sensitive, preferred language, etc.) -- those get folded into
`requests` / `tertiary_signals` and can be summarised into the r_type=4
"requested_for" free-text field until SchoolKnot exposes real outcome
codes.

NOTE: I don't have your actual lead_info.py in front of me, so `upsert()`
below is a minimal in-memory version that mirrors the COALESCE-style
merge behaviour implied by gemini_bridge.py's _merge_info() (new value
overwrites old, None/empty leaves the old value alone). If lead_info.py
persists to a real DB (Mongo/Postgres/etc.), swap the body of upsert()
for the same storage call lead_info.upsert() makes -- the shape of
EnquiryInfo is designed to drop in the same way LeadInfo does.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

# ── in-memory store (swap for your real DB call — see module docstring) ────
_STORE: dict[str, "EnquiryInfo"] = {}


@dataclass
class EnquiryInfo:
    lead_id: str = ""  # kept as lead_id (not enquiry_id) to match the
                        # internal-tracking-only pattern used elsewhere;
                        # this is YOUR call_sid/lead key, not SchoolKnot's
                        # numeric enquiry_id (that lives on WsCallHandler
                        # as self._enquiry_id once known).

    # ── core fields needed for insert_enquiry_service r_type=1 ─────────────
    child_name: Optional[str] = None          # student name
    father_name: Optional[str] = None
    mother_name: Optional[str] = None
    dob: Optional[str] = None                # normalised "YYYY-MM-DD" where possible
    admission_opted_for: Optional[str] = None  # grade/class, numeric CODE per doc ("14")
    email: Optional[str] = None
    mother_mobile: Optional[str] = None

    # Branch the caller said they want (e.g. "Attapur", "Katedan") — used
    # by ws_call_handler.py (via schoolknot_api.resolve_branch()) to pick
    # the correct SchoolKnot school_id + api_key for this call's insert.
    # Raw as stated by the caller/LLM; normalization happens at resolve
    # time, not here.
    branch_name: Optional[str] = None

    # ── r_type=2 / r_type=3 support ─────────────────────────────────────────
    callback_time: Optional[str] = None      # -> follow_up_date / schedule_walkin_date
    visit_requested: bool = False

    # ── probability (SchoolKnot enquiry-stage code, "1"-"16") ──────────────
    # Only set when the caller's own words gave a clear, unambiguous signal
    # (see school_extractor.py's _extract_probability). Codes that are
    # inherently staff/admin-driven (Orientation Schedule/Complete, Deleted,
    # Rejected by School, Duplicate, No Vacancy, Invalid) are intentionally
    # never produced here — a caller can't meaningfully say those about
    # themselves, so leaving this None for those cases (falling back to the
    # default 1/2 logic in ws_call_handler) is the safe behaviour.
    probability_code: Optional[str] = None

    # ── Secondary Outcomes (spec) — no dedicated SchoolKnot field yet ──────
    requests: list[str] = field(default_factory=list)
    # e.g. "Requested Fee Structure", "Requested Brochure", "Requested Curriculum",
    #      "Requested School Address", "Requested Transport Details", "Requested Documents"

    # ── Tertiary Outcomes (spec) — CRM intelligence, also no field yet ─────
    tertiary_signals: list[str] = field(default_factory=list)
    # e.g. "Interested in Admission", "Budget Sensitive", "Decision Pending",
    #      "Preferred Language: Hindi", "Preferred Visit Time: Morning"

    def to_dict(self) -> dict:
        return asdict(self)


def upsert(info: EnquiryInfo) -> EnquiryInfo:
    """Merge `info` into the stored record for info.lead_id.
    Non-None / non-empty fields on `info` overwrite the stored value;
    everything else is left as-is (same COALESCE semantics gemini_bridge.py
    already relies on via GeminiBridge._merge_info()).
    """
    existing = _STORE.get(info.lead_id)
    if existing is None:
        _STORE[info.lead_id] = info
        return info

    for f in (
        "child_name", "father_name", "mother_name", "dob",
        "admission_opted_for", "email", "mother_mobile", "branch_name",
        "callback_time", "probability_code",
    ):
        val = getattr(info, f)
        if val:
            setattr(existing, f, val)

    if info.visit_requested:
        existing.visit_requested = True

    for r in info.requests:
        if r not in existing.requests:
            existing.requests.append(r)

    for t in info.tertiary_signals:
        if t not in existing.tertiary_signals:
            existing.tertiary_signals.append(t)

    _STORE[info.lead_id] = existing
    return existing


def get(lead_id: str) -> Optional[EnquiryInfo]:
    return _STORE.get(lead_id)