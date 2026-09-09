from __future__ import annotations
import re
from enquiry_info import EnquiryInfo

# ─────────────────────────────────────────────────────────────────────────
# NOTE (fallback role): This regex-based extractor is no longer the
# PRIMARY source of collected_info fields. gemini_bridge.py now has a
# `capture_enquiry_info` tool that asks the LLM itself to report each
# field as the caller states it — that path is script/language-
# independent (it can hear "राहुल", "Rahul", or "rahul" and normalize all
# three the same way), which this regex fundamentally cannot do, since
# the capture group below (`[A-Z][a-zA-Z]+`) only matches Latin-script
# text and silently returns None for anything transcribed in Devanagari
# or another script.
#
# This file is kept running as a FALLBACK / safety net: it still runs on
# every caller transcript chunk in gemini_bridge.py, and _merge_info()
# uses a COALESCE-style merge, so whichever source (LLM tool call or this
# regex) reports a field first wins — this can only fill a gap the LLM
# tool call missed, never overwrite an already-captured value.
#
# FIX: grade_to_code() below is now the SINGLE SHARED source of truth
# for converting a raw grade string (however it was captured — by this
# regex OR by the LLM's capture_enquiry_info tool in gemini_bridge.py)
# into the numeric SchoolKnot admission_opted_for code. Previously
# gemini_bridge.py's capture_enquiry_info handler (the PRIMARY path)
# sent whatever raw grade string the LLM reported (e.g. "11" for
# "Class 11") straight through as admission_opted_for, without ever
# running it through _GRADE_CODE_MAP. Since SchoolKnot's own codes are
# NOT the same as the class number (e.g. code 11 = Class 7, code 15 =
# Class 11), this silently stored the wrong grade for every enquiry that
# went through the LLM path — which, per the comment above, is now most
# of them. Only the regex fallback path was ever actually converting
# correctly, and it only kicks in when the LLM path misses a field.
# ─────────────────────────────────────────────────────────────────────────

_WARD_RE = re.compile(
    # FIX: added optional "'s" after the trigger word — "child's name is
    # Rahul" (a very common phrasing) was being missed because the
    # apostrophe+s sat between the trigger word and "name is", and
    # nothing in the old pattern accounted for it.
    r"(?:bet[ae]|beti|bachch[ea]|son|daughter|child|ward|student)(?:'s)?[^\w]{0,10}"
    r"(?:ka\s+naam|name\s+is|naam)?[^\w]{0,10}"
    r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})",
    re.IGNORECASE,
)
_STUDENT_NAME_RE = re.compile(
    r"(?:student(?:'s)?\s*name|admission\s*(?:for|ke\s*liye))[^\w]{0,10}"
    r"(?:is|hai)?[^\w]{0,5}"
    r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})",
    re.IGNORECASE,
)


def _extract_child_name(text: str) -> str | None:
    for pattern in (_WARD_RE, _STUDENT_NAME_RE):
        m = pattern.search(text)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"\b(hai|is|ka|ki)\b", "", name, flags=re.IGNORECASE).strip()
            if name:
                return name.title()
    return None

_FATHER_RE = re.compile(
    r"(?:father(?:'s)?\s*name|papa\s*ka\s*naam|pita\s*ka\s*naam)[^\w]{0,10}"
    r"(?:is|hai)?[^\w]{0,5}"
    r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})",
    re.IGNORECASE,
)
_MOTHER_RE = re.compile(
    r"(?:mother(?:'s)?\s*name|mummy\s*ka\s*naam|maa\s*ka\s*naam)[^\w]{0,10}"
    r"(?:is|hai)?[^\w]{0,5}"
    r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})",
    re.IGNORECASE,
)

_SELF_NAME_RE = re.compile(
    r"(?:mera\s*naam|my\s*name\s*is)[^\w]{0,10}"
    r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})",
    re.IGNORECASE,
)


def _extract_parent_names(text: str) -> tuple[str | None, str | None]:
    father = _FATHER_RE.search(text)
    mother = _MOTHER_RE.search(text)
    father_name = father.group(1).strip().title() if father else None
    mother_name = mother.group(1).strip().title() if mother else None

    if not father_name and not mother_name:
        self_m = _SELF_NAME_RE.search(text)
        if self_m:

            father_name = self_m.group(1).strip().title()

    return father_name, mother_name


_MONTHS = {
    "jan": "01", "january": "01", "feb": "02", "february": "02",
    "mar": "03", "march": "03", "apr": "04", "april": "04",
    "may": "05", "jun": "06", "june": "06", "jul": "07", "july": "07",
    "aug": "08", "august": "08", "sep": "09", "sept": "09", "september": "09",
    "oct": "10", "october": "10", "nov": "11", "november": "11",
    "dec": "12", "december": "12",
}
_DOB_NUMERIC_RE = re.compile(
    r"(?:dob|date\s*of\s*birth|janam\s*tareekh|birth\s*date)[^\d]{0,15}"
    r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})",
    re.IGNORECASE,
)
_DOB_TEXT_RE = re.compile(
    r"(?:dob|date\s*of\s*birth|janam\s*tareekh|birth\s*date)[^\w]{0,15}"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)


def _extract_dob(text: str) -> str | None:
    m = _DOB_NUMERIC_RE.search(text)
    if m:
        day, month, year = m.groups()
        if len(year) == 2:
            year = "20" + year
        try:
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        except ValueError:
            pass

    m = _DOB_TEXT_RE.search(text)
    if m:
        day, month_name, year = m.groups()
        month = _MONTHS.get(month_name.lower())
        if month:
            return f"{int(year):04d}-{month}-{int(day):02d}"

    return None


_GRADE_RE = re.compile(
    r"(?:grade|class|standard|kaksha)[^\w]{0,5}"
    r"(\d{1,2}|nursery|lkg|ukg|kg|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)",
    re.IGNORECASE,
)
_PLAY_GROUP_RE = re.compile(r"\bplay\s*group\b", re.IGNORECASE)

# SchoolKnot admission_opted_for numeric codes. NOTE: these codes are
# NOT the same number as the class itself (e.g. Class 6 -> code 10,
# Class 10 -> code 14, Class 11 -> code 15) — see the doc's
# "Admission opted for data to be sent" table. Any code that converts a
# caller-stated grade into this field MUST go through this map; never
# pass a raw grade string straight through.
GRADE_CODE_MAP = {
    "play group": "1", "playgroup": "1",
    "nursery": "2",
    "lkg": "3",
    "ukg": "4",
    "1": "5", "one": "5",
    "2": "6", "two": "6",
    "3": "7", "three": "7",
    "4": "8", "four": "8",
    "5": "9", "five": "9",
    "6": "10", "six": "10",
    "7": "11", "seven": "11",
    "8": "12", "eight": "12",
    "9": "13", "nine": "13",
    "10": "14", "ten": "14",
    "11": "15", "eleven": "15",
    "12": "16", "twelve": "16",
}

# Kept as an alias for backwards compatibility with any other module
# that may still import the old private name.
_GRADE_CODE_MAP = GRADE_CODE_MAP


def grade_to_code(raw_grade: str | None) -> str | None:
    """
    Convert a raw grade string — however it was captured, e.g. by the
    LLM's capture_enquiry_info tool ("11", "Class 11", "Nursery") or by
    the regex fallback below — into the numeric SchoolKnot
    admission_opted_for code.

    This is the SINGLE shared source of truth for this conversion. Both
    gemini_bridge.py (primary, LLM-reported grade) and
    extract_from_chunk() (fallback, regex-extracted grade) must call
    this rather than sending a raw grade value straight through, since
    SchoolKnot's codes do not match the class number 1:1 (e.g. code 11
    means Class 7, not Class 11).

    Returns None if raw_grade is empty or doesn't match any known grade
    (better to leave admission_opted_for unset than to silently send a
    wrong code).
    """
    if not raw_grade:
        return None

    val = raw_grade.strip().lower()

    # NOTE: deliberately NOT checking "is val already a valid code" here.
    # Raw grade numbers (e.g. "11" for Class 11) and SchoolKnot codes
    # (e.g. "11" = Class 7) overlap in range, so a value like "11" is
    # ambiguous between "the caller said Class 11" and "this is already
    # code 11" — treating it as an already-converted code silently
    # produces the WRONG class. Callers/LLM/regex always report a raw
    # grade, never a pre-converted code, so we always map through
    # GRADE_CODE_MAP below.

    # Strip common prefixes like "class ", "grade ", "standard " so
    # "Class 11" / "class11" / "11" all normalize to the same lookup key.
    stripped = re.sub(r"^\s*(class|grade|standard|kaksha)\s*", "", val).strip()

    if stripped in GRADE_CODE_MAP:
        return GRADE_CODE_MAP[stripped]
    if val in GRADE_CODE_MAP:
        return GRADE_CODE_MAP[val]

    if _PLAY_GROUP_RE.search(val):
        return "1"

    return None


def _extract_grade(text: str) -> str | None:
    m = _GRADE_RE.search(text)
    if m:
        val = m.group(1).lower()
        code = GRADE_CODE_MAP.get(val)
        if code:
            return code
    if _PLAY_GROUP_RE.search(text):
        return "1"
    return None


# ── FIX: callback/follow-up detection ───────────────────────────────────────
# OLD pattern only allowed whitespace ("\s*") between the trigger word
# ("call me", "follow up", etc.) and the time expression ("tomorrow", "5pm").
# That matched "call me back tomorrow" but MISSED very common real-call
# phrasings like "call me tomorrow at 5pm", "schedule a follow-up call for
# tomorrow", or "follow up karna kal" — all of which have extra words in
# between. Fixed by:
#   1. Adding "follow up" / "follow-up" as a trigger phrase (previously only
#      "call", "callback", "baad mein", "phir se" were recognised).
#   2. Allowing up to ~40 characters of filler text between the trigger and
#      the time expression, instead of requiring them to be adjacent.
_CALLBACK_RE = re.compile(
    # FIX (round 2, confirmed via live test): [^\w]{0,40} can only skip
    # punctuation/spaces, NOT extra words — so "follow up karna kal" was
    # still being missed ("karna" is made of word characters and blocked
    # the skip). Switched to ".{0,40}?" (any character, non-greedy) so
    # filler WORDS in between are skipped too, with \b added before the
    # time-word so it still only matches whole words (not a substring
    # buried inside an unrelated longer word).
    r"(?:call\s*(?:me\s*)?(?:back)?|callback|follow[\s-]?\s*up|"
    r"baad\s*mein|phir\s*se)"
    r".{0,40}?"
    r"\b((?:tomorrow|kal|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"morning|evening|afternoon|subah|shaam|\d{1,2}(?::\d{2})?\s*(?:am|pm|baje)))",
    re.IGNORECASE,
)


def _extract_callback_time(text: str) -> str | None:
    m = _CALLBACK_RE.search(text)
    return m.group(1).strip() if m else None


# ── FIX: visit-request detection ────────────────────────────────────────────
# OLD pattern only matched a fixed two-word phrase ("school visit" /
# "campus visit") in that exact order. Real callers rarely say it that way —
# they say "I want to visit the school", "can we come and see the campus",
# "school aake dekhna hai", "schedule a visit", etc. All of those were being
# missed, which is why visit_requested stayed False even when the caller
# clearly asked for a walk-in. Broadened to cover common natural phrasings
# in both English and Hindi/Hinglish.
_VISIT_RE = re.compile(
    # FIX (round 2, confirmed via live test): the old pattern wrapped
    # EVERYTHING in \b...\b. That works fine for clean English words
    # ("visit", "school") but breaks Hindi verb roots like "dekh", which
    # in real speech almost always carry a suffix ("dekhna", "dekhoge",
    # "dekhein") — \b requires a boundary right after "dekh", but "dekh"
    # + "na" are both word characters, so there's no boundary there and
    # the match silently failed (e.g. "school aake dekhna hai" was
    # missed entirely). \b is now only applied where it's actually safe
    # (after complete English words), not after the Hindi roots.
    r"\b(?:"
    r"campus\s*visit\b|school\s*visit\b|"
    r"visit\s*(?:the\s*|your\s*|ur\s*)?(?:school|campus)\b|"
    r"come\s*(?:and\s*)?(?:see|visit)\b|"
    r"schedule\s*a?\s*visit\b|"
    r"walk[\s-]?in\b|"
    r"dekhne\s*aana|aakar\s*dekh|aake\s*dekh|"
    r"school\s*(?:aake|aa\s*ke)\s*dekh"
    r")",
    re.IGNORECASE,
)


def _extract_visit_requested(text: str) -> bool:
    return bool(_VISIT_RE.search(text))


# ── Probability / enquiry-stage code ────────────────────────────────────────
# SchoolKnot's `probability` field (1-16). Only the states a caller could
# plausibly say something about themselves are detected here:
#   1  Interested / Online / Phone Enquiry   (default — set by ws_call_handler)
#   2  Enquired / School Visit                (via visit_requested, handled
#                                               by ws_call_handler, not here)
#   3  Not Interested
#   4  Closed / Confirmed
#   5  Application Form        (caller is asking FOR the form)
#   6  Reserve Admission
#   9  Online Form Payment Pending
#   11 Application Payment Confirmed
#   15 Form Submitted          (caller says they ALREADY filled/submitted it)
#
# Deliberately NOT handled (these are staff/admin actions a caller would
# never say about themselves — guessing at them risks mis-filing a real
# enquiry): 7 Orientation Schedule, 8 Orientation Complete, 10 Deleted,
# 12 Rejected by School, 13 Duplicate, 14 No Vacancy, 16 Invalid.
_NOT_INTERESTED_RE = re.compile(
    r"\b(not\s*interested|no\s*interest|nahi\s*chahiye|interested\s*nahi|"
    r"nahi\s*karna|not\s*looking|humein\s*nahi\s*karna)\b",
    re.IGNORECASE,
)
_PAYMENT_CONFIRMED_RE = re.compile(
    r"\b(payment\s*(?:is\s*|has\s*been\s*)?(?:done|confirmed|complete)|"
    r"fees?\s*(?:paid|payment\s*done)|paisa\s*de\s*diya|payment\s*kar\s*diya|"
    r"maine\s*payment\s*kar\s*diya)\b",
    re.IGNORECASE,
)
_PAYMENT_PENDING_RE = re.compile(
    r"\b(payment\s*(?:is\s*)?pending|payment\s*(?:abhi\s*)?(?:nahi|baaki)|"
    r"payment\s*karna\s*baaki|payment\s*abhi\s*tak\s*nahi\s*kiya)\b",
    re.IGNORECASE,
)
_FORM_SUBMITTED_RE = re.compile(
    r"\b(form\s*(?:submit|fill|bhar)\s*(?:kar\s*diya|diya|kiya)|"
    r"already\s*submitted|form\s*submitted|maine\s*form\s*bhar\s*diya)\b",
    re.IGNORECASE,
)
_FORM_REQUEST_RE = re.compile(
    r"\b(application\s*form|admission\s*form)\b",
    re.IGNORECASE,
)
_RESERVE_RE = re.compile(
    r"\b(reserve\s*(?:the\s*)?(?:seat|admission)|seat\s*reserve|"
    r"admission\s*reserve)\b",
    re.IGNORECASE,
)
_CLOSED_CONFIRMED_RE = re.compile(
    r"\b(admission\s*(?:is\s*)?confirmed|admission\s*ho\s*gaya|"
    r"admission\s*complete|admission\s*done)\b",
    re.IGNORECASE,
)


def _extract_probability(text: str) -> str | None:
    """Returns a SchoolKnot probability code as a string if this chunk
    contains a clear, unambiguous signal, else None. Checked in priority
    order (most specific/decisive first) so a single chunk containing
    multiple loose keywords doesn't pick the wrong one."""
    if _NOT_INTERESTED_RE.search(text):
        return "3"
    if _PAYMENT_CONFIRMED_RE.search(text):
        return "11"
    if _PAYMENT_PENDING_RE.search(text):
        return "9"
    if _FORM_SUBMITTED_RE.search(text):
        return "15"
    if _RESERVE_RE.search(text):
        return "6"
    if _CLOSED_CONFIRMED_RE.search(text):
        return "4"
    if _FORM_REQUEST_RE.search(text):
        return "5"
    return None


# ── Secondary Outcomes — informational requests ─────────────────────────────
_SECONDARY_KEYWORDS = {
    "fee structure": "Requested Fee Structure",
    "fees": "Requested Fee Structure",
    "brochure": "Requested Brochure",
    "curriculum": "Requested Curriculum",
    "syllabus": "Requested Curriculum",
    "address": "Requested School Address",
    "location of school": "Requested School Address",
    "transport": "Requested Transport Details",
    "bus facility": "Requested Transport Details",
    "documents": "Requested Documents",
    "document list": "Requested Documents",
}


def _extract_secondary_requests(text: str) -> list[str]:
    lower = text.lower()
    found = []
    for kw, label in _SECONDARY_KEYWORDS.items():
        if kw in lower and label not in found:
            found.append(label)
    return found


# ── Tertiary Outcomes — CRM intelligence signals ────────────────────────────
_TERTIARY_KEYWORDS = {
    "admission": "Interested in Admission",
    "enroll": "Interested in Admission",
    "cbse": "Interested in CBSE",
    "icse": "Interested in ICSE",
    "ib board": "Interested in IB",
    "expensive": "Budget Sensitive",
    "afford": "Budget Sensitive",
    "discount": "Budget Sensitive",
    "scholarship": "Budget Sensitive",
    "think about it": "Decision Pending",
    "soch ke": "Decision Pending",
    "discuss with": "Decision Pending",
    "husband se baat": "Decision Pending",
    "wife se baat": "Decision Pending",
}
_LANGUAGE_RE = re.compile(
    r"\b(hindi|english|telugu|tamil|kannada|marathi|gujarati|bengali)\b\s*(?:mein|me)?\s*(?:baat|speak|bolna)",
    re.IGNORECASE,
)
_VISIT_TIME_RE = re.compile(
    r"(?:visit|aana)[^\w]{0,10}(morning|evening|afternoon|subah|shaam|dopahar)",
    re.IGNORECASE,
)


def _extract_tertiary_signals(text: str) -> list[str]:
    lower = text.lower()
    found = []
    for kw, label in _TERTIARY_KEYWORDS.items():
        if kw in lower and label not in found:
            found.append(label)

    lang_m = _LANGUAGE_RE.search(text)
    if lang_m:
        found.append(f"Preferred Language: {lang_m.group(1).title()}")

    visit_m = _VISIT_TIME_RE.search(text)
    if visit_m:
        found.append(f"Preferred Visit Time: {visit_m.group(1).title()}")

    return found


# ── Public API ───────────────────────────────────────────────────────────────

def extract_from_chunk(lead_id: str, text: str) -> EnquiryInfo:
    """
    Extract all admissions signals from a single transcript chunk.
    Returns an EnquiryInfo with only the fields found in THIS chunk
    populated — enquiry_info.upsert() preserves previously extracted
    values for anything left None/empty here (same COALESCE pattern
    as the original real-estate extractor).

    FALLBACK ROLE: this is now a safety net that runs alongside the
    LLM's capture_enquiry_info tool call in gemini_bridge.py. See the
    module docstring at the top of this file for why.
    """
    father_name, mother_name = _extract_parent_names(text)

    return EnquiryInfo(
        lead_id=lead_id,
        child_name=_extract_child_name(text),
        father_name=father_name,
        mother_name=mother_name,
        dob=_extract_dob(text),
        admission_opted_for=_extract_grade(text),
        callback_time=_extract_callback_time(text),
        visit_requested=_extract_visit_requested(text),
        probability_code=_extract_probability(text),
        requests=_extract_secondary_requests(text),
        tertiary_signals=_extract_tertiary_signals(text),
    )


def missing_fields(info: EnquiryInfo) -> list[str]:
    """Return field names still unknown for this enquiry — useful if you
    want the agent to proactively ask for them before the call ends."""
    gaps = []
    if info.child_name is None:
        gaps.append("child_name")
    if info.father_name is None and info.mother_name is None:
        gaps.append("parent_name")
    if info.dob is None:
        gaps.append("dob")
    if info.admission_opted_for is None:
        gaps.append("grade")
    return gaps