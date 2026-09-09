"""
outbound_call.py

⭐ This is the API you hand over to SchoolKnot (the client) to trigger
   outbound calls. ⭐

SchoolKnot calls POST /api/outbound/initiate-call with a phone number +
lead context + call objective. This file then calls VoiceLink's
`add_lead` API to place the outbound call. VoiceLink already has your
websocket bot (/ws/voice-agent) pre-configured against your DID number
in their dashboard, so VoiceLink bridges the call to your bot
automatically once it connects — you don't need to build/send a ws_url
yourself.

Flow:
    1. SchoolKnot → POST /api/outbound/initiate-call (this file)
    2. This file builds the VoiceLink `add_lead` request body, packing
       all the lead context (parent_name, student_name, prompt_type,
       etc.) into `custom_parameters`.
    3. This file calls VoiceLink's POST /api/v1/add_lead with that body.
    4. VoiceLink dials the number, and once answered, bridges the call
       to your pre-configured websocket bot. Your bot should read
       `custom_parameters` (VoiceLink will forward it) to know the
       prompt_type / lead context and run the correct outbound flow.

⚠️ THINGS TO CONFIRM / SET:
- VOICELINK_API_TOKEN and VOICELINK_DID_NUMBER below (env vars).
- AUTH header format — currently set to "Bearer <token>". If VoiceLink
  returns 401, try the other formats noted in the comment next to
  AUTH_HEADERS below.
- Confirm with VoiceLink docs / your bot code exactly how
  `custom_parameters` arrives at your websocket (query param? JSON in
  a message after connect?) so ws_call_handler.py reads it correctly.
"""

import logging
import os
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

# ── VoiceLink config ─────────────────────────────────────────────────────

VOICELINK_ADD_LEAD_URL = "https://app.voicelink.co.in/api/v1/add_lead"

# Set these as real environment variables — never hardcode credentials.
VOICELINK_API_TOKEN = os.environ.get("VOICELINK_API_TOKEN", "")
VOICELINK_DID_NUMBER = os.environ.get("VOICELINK_DID_NUMBER", "")

if not VOICELINK_API_TOKEN:
    logger.warning("VOICELINK_API_TOKEN is not set — outbound calls will fail.")
if not VOICELINK_DID_NUMBER:
    logger.warning("VOICELINK_DID_NUMBER is not set — outbound calls will fail.")


# ── Request/response models — this IS the contract you give SchoolKnot ──

class OutboundCallRequest(BaseModel):
    # ── Required ──
    phone_number: str = Field(..., description="Number to dial, e.g. '9550335589' or '+919550335589'.")
    prompt_type: str = Field(
        ...,
        description=(
            "OBJECTIVE of this call — which outbound flow to run. One of: "
            "outbound_new_lead, outbound_follow_up, outbound_admission_reminder, "
            "outbound_event_invite, outbound_reengagement, outbound_reconfirmation."
        ),
    )

    # ── Context — optional, but the more you send, the less the agent
    #    has to ask on the call. Nothing here is required. ──
    parent_name: Optional[str] = None
    student_name: Optional[str] = None
    grade: Optional[str] = None
    branch_name: Optional[str] = None
    enquiry_status: Optional[str] = None
    call_purpose: Optional[str] = Field(
        default=None,
        description="Why this call is happening, e.g. 'enquired online last week'.",
    )
    notes: Optional[str] = None

    # ── Only used when prompt_type = outbound_reconfirmation ──
    appointment_type: Optional[str] = None
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None

    # ── Optional — if SchoolKnot already has an enquiry_id, pass it so
    #    the call is linked back to the right CRM record. ──
    enquiry_id: Optional[int] = None


class OutboundCallResponse(BaseModel):
    success: bool
    call_reference: str
    message: str
    dialer_response: Optional[dict] = None


# ── Helpers ──────────────────────────────────────────────────────────────

def _build_custom_parameters(call_reference: str, req: OutboundCallRequest) -> dict:
    """Packs everything your voice agent needs to know into the
    custom_parameters object sent to VoiceLink. VoiceLink forwards this
    to your pre-configured websocket bot when it bridges the call.
    """
    params = {
        "call_reference": call_reference,
        "prompt_type": req.prompt_type,
        "lead_name": req.parent_name or "there",
        "caller_status": "existing" if (req.enquiry_status or req.enquiry_id) else "new",
        "parent_name": req.parent_name,
        "student_name": req.student_name,
        "grade": req.grade,
        "branch_name": req.branch_name,
        "enquiry_status": req.enquiry_status,
        "call_purpose": req.call_purpose,
        "notes": req.notes,
        "appointment_type": req.appointment_type,
        "appointment_date": req.appointment_date,
        "appointment_time": req.appointment_time,
        "enquiry_id": req.enquiry_id,
    }
    # Drop empty/None values — keeps the payload clean.
    return {k: v for k, v in params.items() if v not in (None, "")}


async def _place_outbound_call(phone_number: str, call_reference: str, req: OutboundCallRequest) -> dict:
    """
    Calls VoiceLink's `add_lead` API to place the outbound call.

    VoiceLink dials `phone_number` using your configured DID
    (VOICELINK_DID_NUMBER) and, once answered, bridges the call to your
    websocket bot — which is already configured against that DID inside
    the VoiceLink dashboard. No ws_url needs to be sent here.
    """
    if not VOICELINK_API_TOKEN or not VOICELINK_DID_NUMBER:
        raise RuntimeError(
            "VOICELINK_API_TOKEN / VOICELINK_DID_NUMBER not configured. "
            "Set them as environment variables before placing calls."
        )

    body = {
        "did_number": VOICELINK_DID_NUMBER,
        "customer_number": phone_number,
        "country_code": "+91",
        "custom_parameters": _build_custom_parameters(call_reference, req),
    }

    # NOTE: Auth header format not yet 100% confirmed against VoiceLink's
    # docs. Currently using "Bearer <token>". If you get 401/403, try:
    #   headers = {"Authorization": VOICELINK_API_TOKEN, ...}
    #   headers = {"X-API-Key": VOICELINK_API_TOKEN, ...}
    headers = {
        "Authorization": f"Bearer {VOICELINK_API_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(VOICELINK_ADD_LEAD_URL, json=body, headers=headers)

    if resp.status_code not in (200, 201):
        logger.error(f"[{call_reference}] VoiceLink error {resp.status_code}: {resp.text}")
        raise RuntimeError(f"VoiceLink API returned {resp.status_code}: {resp.text}")

    return resp.json()


# ── Route — this is what you hand to SchoolKnot ─────────────────────────

@router.post("/api/outbound/initiate-call", response_model=OutboundCallResponse)
async def initiate_outbound_call(req: OutboundCallRequest):
    """
    Trigger an outbound call to a lead.

    SchoolKnot calls this with the lead's phone number, the call's
    objective (prompt_type), and whatever context they have on the lead.
    On success, VoiceLink dials the number and bridges the call to your
    configured voice agent bot.
    """
    call_reference = f"outbound-{uuid.uuid4().hex[:12]}"

    digits = "".join(ch for ch in req.phone_number if ch.isdigit() or ch == "+")
    if len(digits.lstrip("+")) < 7:
        raise HTTPException(status_code=400, detail=f"Invalid phone_number: {req.phone_number!r}")
    # VoiceLink's customer_number field expects digits without the
    # country code prefix (country_code is sent separately) — strip a
    # leading "91"/"+91" if present.
    bare_number = digits.lstrip("+")
    if bare_number.startswith("91") and len(bare_number) > 10:
        bare_number = bare_number[2:]

    valid_prompt_types = {
        "outbound_new_lead", "outbound_follow_up", "outbound_admission_reminder",
        "outbound_event_invite", "outbound_reengagement", "outbound_reconfirmation",
    }
    if req.prompt_type not in valid_prompt_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prompt_type {req.prompt_type!r} — must be one of {sorted(valid_prompt_types)}",
        )

    logger.info(f"[{call_reference}] Outbound call requested for {req.phone_number!r}")

    try:
        dialer_response = await _place_outbound_call(bare_number, call_reference, req)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception(f"[{call_reference}] Failed to place outbound call")
        raise HTTPException(status_code=502, detail=f"Failed to place outbound call: {e}")

    return OutboundCallResponse(
        success=True,
        call_reference=call_reference,
        message=f"Outbound call to {req.phone_number} triggered.",
        dialer_response=dialer_response,
    )