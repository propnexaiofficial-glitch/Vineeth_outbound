"""
outbound_api.py -- REST API the CLIENT'S system calls to trigger an
outbound AI call.

FLOW:
  1. Client's system calls POST /api/calls/outbound with:
       - mobile_number  (who to call)
       - parent_name    (optional, used for a personal greeting)
       - context        (free-form object: child_name, grade, branch,
                          reason for calling, anything the agent should
                          know to carry the conversation forward)
  2. We generate a reference_id, stash the context under it, and ask
     Orbitel to place the call (see _orbitel_originate_call below).
  3. When the callee answers, Orbitel opens the SAME WebSocket your
     inbound calls already use, and sends a 'start' event. That event
     must carry our reference_id back to us (see the "TODO: ORBITEL"
     marker below) so ws_call_handler.py can look up which context
     belongs to this specific call and hand it to GeminiBridge.

This file only handles steps 1-2 (the REST trigger + storing context).
The corresponding change to ws_call_handler.py (step 3, reading the
reference_id back out of the 'start' event) is in a separate file/diff.
"""

import logging
import re
import time
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# TODO: ORBITEL — fill these in from Orbitel's outbound/"originate call" API
# docs. This is the one genuinely vendor-specific piece of this whole design
# — everything else here (the REST endpoint, the context store, the
# ws_call_handler.py change) is fixed regardless of vendor.
#
# What you specifically need from Orbitel's docs/support:
#   1. The originate-call endpoint URL and auth method (API key? Basic auth?
#      a token you fetch first?).
#   2. The exact request field names for: destination number, the number/
#      trunk to call FROM, and — most important — whether they support a
#      "custom data" / "reference id" / "user-to-user info" field that gets
#      echoed back to you in the WebSocket 'start' event once the call
#      connects. Every telephony vendor calls this something different.
#   3. If they do NOT support echoing a reference id back, ask them what
#      DOES come back in the 'start' event that's unique per call (e.g. a
#      vendor-side call_id) — we can still correlate using that instead,
#      by recording it right after we place the call (see
#      _orbitel_originate_call's return value below).
# ---------------------------------------------------------------------------
_ORBITEL_ORIGINATE_URL = "https://REPLACE-ME.orbitel.example/api/originate"
_ORBITEL_API_KEY = "REPLACE-ME"


class OutboundCallRequest(BaseModel):
    mobile_number: str = Field(
        ..., description="Number to call, e.g. '9876543210' or '+919876543210'."
    )
    parent_name: Optional[str] = Field(
        default=None, description="Used for a personal greeting, e.g. 'Hello Mr. Sharma'."
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Free-form. Recognised keys get mapped onto the same fields the "
            "inbound 'returning caller' flow already uses (student_name, "
            "grade, branch_name, enquiry_status). Anything else you put here "
            "(reason for calling, a note, a callback context) is still "
            "passed to the agent as background — see build_outbound_context() "
            "in prompts.py."
        ),
    )

    @field_validator("mobile_number")
    @classmethod
    def _validate_mobile(cls, v: str) -> str:
        digits = re.sub(r"[^\d]", "", v)
        if len(digits) < 10 or len(digits) > 13:
            raise ValueError(f"mobile_number {v!r} doesn't look like a valid phone number.")
        return v


class OutboundCallResponse(BaseModel):
    status: str
    reference_id: str


# ---------------------------------------------------------------------------
# Pending-context store.
#
# NOTE: this is an in-memory dict, which only works if you're running a
# SINGLE server process/worker. The moment you scale to multiple workers or
# machines (common with FastAPI + gunicorn/uvicorn --workers N, or multiple
# pods), the worker that received the WebSocket connection from Orbitel
# might not be the same one that stored the context here, and the lookup
# will fail. If that's your deployment, swap this dict for Redis (or your
# existing MongoDB) — same get/set/pop shape, just backed by a shared store
# instead of process memory. Flagging this now so it doesn't surprise you
# later when the app scales.
# ---------------------------------------------------------------------------
_PENDING_OUTBOUND_CONTEXTS: Dict[str, dict] = {}
_PENDING_CONTEXT_TTL_SECONDS = 15 * 60  # stale entries older than this are dropped


def _cleanup_stale_contexts():
    now = time.monotonic()
    stale = [
        ref for ref, entry in _PENDING_OUTBOUND_CONTEXTS.items()
        if now - entry["_stored_at"] > _PENDING_CONTEXT_TTL_SECONDS
    ]
    for ref in stale:
        _PENDING_OUTBOUND_CONTEXTS.pop(ref, None)
    if stale:
        logger.info(f"Cleaned up {len(stale)} stale pending outbound context(s).")


def pop_pending_outbound_context(reference_id: str) -> Optional[dict]:
    """
    Called from ws_call_handler.py once the WebSocket 'start' event for an
    outbound call arrives and reports this reference_id. Pops (not just
    reads) the context, since it's only ever needed once per call.
    """
    entry = _PENDING_OUTBOUND_CONTEXTS.pop(reference_id, None)
    if entry is None:
        return None
    entry.pop("_stored_at", None)
    return entry


async def _orbitel_originate_call(mobile_number: str, reference_id: str) -> None:
    """
    TODO: ORBITEL — replace this body with the actual call to Orbitel's
    originate/click-to-call API once you have their docs. The shape below
    (a plain POST with a JSON body) is a reasonable guess but WILL need
    adjusting to match their real request/response format and auth scheme.
    """
    payload = {
        "destination": mobile_number,
        # TODO: ORBITEL — this is the field that needs to survive the round
        # trip and come back in the WebSocket 'start' event. Confirm the
        # real field name with Orbitel (could be "custom_data",
        # "reference_id", "user_data", "metadata", etc.) and rename here.
        "reference_id": reference_id,
    }
    headers = {"Authorization": f"Bearer {_ORBITEL_API_KEY}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(_ORBITEL_ORIGINATE_URL, json=payload, headers=headers)
        resp.raise_for_status()


@router.post("/api/calls/outbound", response_model=OutboundCallResponse)
async def trigger_outbound_call(payload: OutboundCallRequest):
    """
    The client's system calls this endpoint whenever it wants the AI agent
    to call someone. Returns immediately with a reference_id — placing the
    actual call and having it answered happens asynchronously; this
    endpoint does not wait for the call to complete.
    """
    _cleanup_stale_contexts()

    reference_id = str(uuid.uuid4())

    _PENDING_OUTBOUND_CONTEXTS[reference_id] = {
        "mobile_number": payload.mobile_number,
        "parent_name": payload.parent_name,
        "context": payload.context,
        "_stored_at": time.monotonic(),
    }

    try:
        await _orbitel_originate_call(payload.mobile_number, reference_id)
    except Exception as e:
        _PENDING_OUTBOUND_CONTEXTS.pop(reference_id, None)
        logger.error(f"Failed to originate outbound call to {payload.mobile_number}: {e}")
        raise HTTPException(status_code=502, detail=f"Could not place the call: {e}")

    logger.info(
        f"Outbound call queued — reference_id={reference_id}, "
        f"mobile_number={payload.mobile_number}, parent_name={payload.parent_name!r}"
    )

    return OutboundCallResponse(status="queued", reference_id=reference_id)