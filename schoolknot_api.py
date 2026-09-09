from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

try:
    from config import (
        SCHOOLKNOT_BASE_URL,
        SCHOOLKNOT_API_KEY,
        SCHOOLKNOT_INSERT_API_KEY,
        SCHOOLKNOT_CHANNEL_ID,
        SCHOOLKNOT_SCHOOL_ID,
        SCHOOLKNOT_ORGANIZATION_ID,
        SCHOOLKNOT_BRANCH_CONFIG,
    )
except ImportError:
    SCHOOLKNOT_BASE_URL = os.environ.get(
        "SCHOOLKNOT_BASE_URL", "https://analytics.schoolknot.com/ai_calling_agent"
    )
  
    # Get-enquiry-details API key — SAME key used across all branches.
    SCHOOLKNOT_API_KEY = os.environ.get("SCHOOLKNOT_API_KEY", "8KQZ7MPLX4VNC2RHT9YD")
    SCHOOLKNOT_INSERT_API_KEY = os.environ.get("SCHOOLKNOT_INSERT_API_KEY", "")
    SCHOOLKNOT_CHANNEL_ID = os.environ.get("SCHOOLKNOT_CHANNEL_ID", "")
    SCHOOLKNOT_SCHOOL_ID = os.environ.get("SCHOOLKNOT_SCHOOL_ID", "")
    SCHOOLKNOT_ORGANIZATION_ID = os.environ.get("SCHOOLKNOT_ORGANIZATION_ID", "")
    # Fallback per-branch credentials if config.py's SCHOOLKNOT_BRANCH_CONFIG
    # couldn't be imported for some reason — kept in sync with config.py.
    # insert_enquiry_service uses the branch-specific key below (resolved
    # via resolve_branch()) instead of SCHOOLKNOT_INSERT_API_KEY whenever
    # the caller's branch is known.
    SCHOOLKNOT_BRANCH_CONFIG = {
        "attapur": {"school_id": "SC1001", "api_key": "G8DKABCRE543EW21FT"},
        "katedan": {"school_id": "SC1005", "api_key": "K7MPX9QW3RTA6VY2N8LC"},
    }

try:
    from config import SCHOOLKNOT_DEFAULT_PROBABILITY
except ImportError:
    SCHOOLKNOT_DEFAULT_PROBABILITY = os.environ.get("SCHOOLKNOT_DEFAULT_PROBABILITY", "1")

_GET_ENQUIRY_URL = f"{SCHOOLKNOT_BASE_URL}/get_enquiry_details"
_INSERT_ENQUIRY_URL = f"{SCHOOLKNOT_BASE_URL}/insert_enquiry_service"

_TIMEOUT_SECONDS = 20.0

# FIX: insert_enquiry_service() previously made a single attempt and
# raised immediately on any non-2xx response (via raise_for_status())
# or network error. In production this surfaced as, e.g., HTTP 522
# ("Connection timed out") from Cloudflare in front of
# stage.schoolknot.com — a transient origin-server issue, not a bug in
# this code. A single 522 was enough to lose a transfer note or an
# enquiry insert for that call. Now insert_enquiry_service() retries
# transient failures (5xx / network errors) a few times with a short
# backoff before giving up. 4xx errors (bad request, auth, etc.) are
# NOT retried, since retrying won't fix a client-side problem.
_INSERT_MAX_ATTEMPTS = 3
_INSERT_RETRY_BACKOFF_SECONDS = 1.5  # multiplied by attempt number


_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
}



async def get_enquiry_details(mobile_number: str) -> dict:
    """
    Look up an enquiry by mobile number.

    Returns (per the doc):
        {"type": 1}                       -- new caller, no existing enquiry
        {"type": 2, "data": [ {...}, ... ]}  -- existing caller, one record
                                                 per enquiry (siblings /
                                                 multiple branches possible)

    Raises on network/HTTP errors — caller (ws_call_handler._handle_start)
    is expected to catch this and NOT silently treat a failed lookup as
    "new caller".
    """
    payload = {
        "api_key": SCHOOLKNOT_API_KEY,
        "mobile_number": mobile_number,
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        resp = await client.post(_GET_ENQUIRY_URL, json=payload, headers=_DEFAULT_HEADERS)
        resp.raise_for_status()
        return resp.json()




async def insert_enquiry_service(blocks: list[dict], api_key: str | None = None) -> dict:
    """
    Send one or more r_type blocks in a single request, per the doc's
    "data": [ {...}, {...} ] batch format. `blocks` is the list itself —
    caller assembles it with the build_*_block() helpers below.

    NOTE: this service uses SCHOOLKNOT_INSERT_API_KEY by default, which
    is a DIFFERENT key from the one get_enquiry_details uses
    (SCHOOLKNOT_API_KEY) — confirmed with SchoolKnot, not a typo.

    `api_key`: optional per-call override. Pass the branch-specific key
    (from resolve_branch() below) when the caller stated which branch
    they want, so the insert goes in under that branch's own key instead
    of the global default. Falls back to SCHOOLKNOT_INSERT_API_KEY when
    not given (e.g. branch wasn't mentioned/resolved).

    Auth: sent both as `api_key` in the body (matching the doc's sample
    payload) and as a Bearer header (in case the endpoint expects that
    instead). Harmless to send both; SchoolKnot's server will just ignore
    whichever one it doesn't check for.

    Retries transient failures (5xx responses, connection/timeout
    errors) up to _INSERT_MAX_ATTEMPTS times with a short backoff, since
    these are often momentary origin-server issues (e.g. Cloudflare 522)
    rather than something wrong with the request itself. 4xx responses
    are raised immediately without retrying, since those indicate a
    client-side problem (bad payload, bad auth) that a retry won't fix.
    """
    effective_api_key = api_key or SCHOOLKNOT_INSERT_API_KEY

    payload = {"data": blocks}
    if effective_api_key:
        payload["api_key"] = effective_api_key

    headers = dict(_DEFAULT_HEADERS)
    if effective_api_key:
        headers["Authorization"] = f"Bearer {effective_api_key}"

    logger.info(f"insert_enquiry_service payload being sent: {payload}")

    last_exc: Optional[Exception] = None

    for attempt in range(1, _INSERT_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(_INSERT_ENQUIRY_URL, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()

        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else None
            # Only retry server-side errors (5xx, including Cloudflare's
            # 522/524/etc). 4xx means the request itself is bad —
            # retrying identical bad input won't help.
            if status is not None and 400 <= status < 500:
                logger.error(
                    f"insert_enquiry_service got client error {status} — "
                    f"not retrying: {e}"
                )
                raise
            last_exc = e
            logger.warning(
                f"insert_enquiry_service attempt {attempt}/{_INSERT_MAX_ATTEMPTS} "
                f"failed with status {status}: {e}"
            )

        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            logger.warning(
                f"insert_enquiry_service attempt {attempt}/{_INSERT_MAX_ATTEMPTS} "
                f"failed with network error: {e}"
            )

        if attempt < _INSERT_MAX_ATTEMPTS:
            await asyncio.sleep(_INSERT_RETRY_BACKOFF_SECONDS * attempt)

    logger.error(
        f"insert_enquiry_service FAILED after {_INSERT_MAX_ATTEMPTS} attempts — giving up."
    )
    raise last_exc

def build_new_enquiry_block(
    child_name: str,
    father_name: str = "",
    mobile: str = "",
    enquiry_date: str = "",
    mother_name: str = "",
    mother_mobile: str = "",
    email: str = "",
    dob: str = "",
    residence_mobile: str = "",
    enquiry_number: str = "",
    admission_opted_for: str = "",
    probability: str = "",
    school_id: str = "",
) -> dict:
    """r_type=1 — new enquiry insert.

    `school_id`: pass the branch-specific school_id (from
    resolve_branch() below) when the caller stated which branch they
    want. Omitted from the payload entirely when not given (empty
    string), matching the previous "no school_id" behaviour for calls
    where the branch couldn't be determined.

    `admission_opted_for` must be the SchoolKnot numeric class CODE
    (see school_extractor.py's _GRADE_CODE_MAP / grade_to_code()), not a
    raw grade name — e.g. Class 10 -> "14", Nursery -> "2". Double-check
    this mapping; sending a raw grade name here (e.g. "10" when the real
    code differs) will silently store the wrong grade rather than
    erroring.

    `enquiry_date` is the date the enquiry/call happened (e.g.
    "2026-08-14"), not an academic year.

    `probability` defaults to SCHOOLKNOT_DEFAULT_PROBABILITY (config/env,
    "1" = Interested / Online / Phone Enquiry) if not passed explicitly.
    Pass "2" (Enquired / School Visit) when the caller asked for a
    campus visit.
    """

    block = {
        "r_type": 1,
        "child_name": child_name,
        "father_name": father_name,
        "mother_name": mother_name,
        "mobile": mobile,
        "probability": probability or SCHOOLKNOT_DEFAULT_PROBABILITY,
    }

    if admission_opted_for:
        block["admission_opted_for"] = admission_opted_for
    if dob:
        block["dob"] = dob
    if enquiry_date:
        block["enquiry_date"] = enquiry_date
    if mother_mobile:
        block["mother_mobile"] = mother_mobile
    if residence_mobile:
        block["residence_mobile"] = residence_mobile
    if email:
        block["email"] = email
    if enquiry_number:
        block["enquiry_number"] = enquiry_number
    if school_id:
        block["school_id"] = school_id

    return block


def build_walkin_block(
    schedule_walkin_date: str,
    comments: str = "",
    commented_by: str = "",
    enquiry_id: Optional[int] = None,
) -> dict:
    """r_type=2 — schedule a walk-in.
    Omit enquiry_id when this rides in the SAME batch as a new r_type=1
    insert (new caller); include it when editing an existing enquiry.
    """
    block = {
        "r_type": 2,
        "schedule_walkin_date": schedule_walkin_date,
        "comments": comments,
    }
    if commented_by:
        block["commented_by"] = commented_by
    if enquiry_id is not None:
        block["enquiry_id"] = enquiry_id
    return block


def build_followup_block(
    follow_up_date: str,
    enquiry_id: Optional[int] = None,
) -> dict:
    """r_type=3 — schedule/update a follow-up date."""
    block = {
        "r_type": 3,
        "follow_up_date": follow_up_date,
    }
    if enquiry_id is not None:
        block["enquiry_id"] = enquiry_id
    return block


def build_other_request_block(
    requested_for: str,
    enquiry_id: Optional[int] = None,
) -> dict:
    """r_type=4 — any other request / free-text note against an enquiry
    (used here for warm-transfer notes and the Secondary/Tertiary outcome
    summary — see ws_call_handler._build_insert_enquiry_blocks)."""
    block = {
        "r_type": 4,
        "requested_for": requested_for,
    }
    if enquiry_id is not None:
        block["enquiry_id"] = enquiry_id
    return block


def resolve_branch(raw_branch: str | None) -> dict | None:
    """
    Normalize a caller-stated branch name (e.g. "Attapur", "attapur
    branch", "Katedan campus") to its school_id/api_key config from
    SCHOOLKNOT_BRANCH_CONFIG (config.py).

    Returns None if no match — caller (ws_call_handler.py) should then
    fall back to the default single-branch behaviour (global
    SCHOOLKNOT_INSERT_API_KEY, no school_id) rather than guessing wrong,
    and should log a warning so it can be followed up manually.
    """
    if not raw_branch:
        return None

    key = raw_branch.strip().lower()
    for branch_key, cfg in SCHOOLKNOT_BRANCH_CONFIG.items():
        if branch_key in key or key in branch_key:
            return {"branch_name": branch_key, **cfg}
    return None