# """
# Bonvoice Auto Call Bridging (Call Initiate) API Wrapper - FastAPI
# Client: SchoolKnot

# This service wraps Bonvoice's Auto Call Bridging API and exposes a rich
# endpoint for SchoolKnot to trigger outbound calls with full lead context
# (parent name, student name, appointment details, etc.) — mirroring the
# same contract used for the VoiceLink integration.

# Upstream Bonvoice docs: https://backend.pbx.bonvoice.com/autoDialManagement/autoCallBridging/

# ------------------------------------------------------------------------
# HOW LEAD CONTEXT REACHES YOUR VOICE AGENT:
# ------------------------------------------------------------------------
# Bonvoice's API does NOT have a `custom_parameters` field like VoiceLink
# does. Instead, its `voicebotURL` parameter can be set dynamically per
# call. So we take all the lead-context fields SchoolKnot sends us and
# encode them as QUERY PARAMETERS on the voicebotURL we pass to Bonvoice.

# Example voicebotURL sent to Bonvoice:
#     wss://your-bot.onrender.com/ws/voice-agent?call_reference=...&prompt_type=outbound_reconfirmation&parent_name=Anita&...

# Your websocket bot (ws_call_handler.py) should read these query
# parameters as soon as the connection is established, the same way it
# would have read `custom_parameters` from VoiceLink.

# ------------------------------------------------------------------------
# EXPOSED ENDPOINT (this is the contract given to SchoolKnot):
# ------------------------------------------------------------------------
# POST /api/call/initiate

# Required:
#     phone_number   (str)  Number to dial, e.g. '9550335589' or '+919550335589'
#     prompt_type    (str)  One of: outbound_new_lead, outbound_follow_up,
#                           outbound_admission_reminder, outbound_event_invite,
#                           outbound_reengagement, outbound_reconfirmation

# Optional lead context (send whatever you have):
#     parent_name, student_name, grade, branch_name, enquiry_status,
#     call_purpose, notes, enquiry_id

# Optional — only used when prompt_type = outbound_reconfirmation:
#     appointment_type, appointment_date, appointment_time

# Response codes:
#     200  -> Call successfully triggered (does NOT mean it was answered)
#     400  -> Missing/invalid phone_number or invalid prompt_type
#     500  -> Server misconfiguration (env vars not set)
#     502  -> Bonvoice/upstream error (e.g. "DID is not configured")

# ------------------------------------------------------------------------

# ENV VARIABLES REQUIRED (create a .env file in the project root):
#     BONVOICE_AUTH_TOKEN=your_auth_token_here
#     BONVOICE_VOICEBOT_PROVIDER=BONVOICE
#     BONVOICE_VOICEBOT_BASE_URL=wss://your-bot.onrender.com/ws/voice-agent
#     BONVOICE_DID_NUMBER=7946350797   # your Bonvoice-configured outbound DID

# INSTALL DEPENDENCIES:
#     pip install fastapi uvicorn httpx python-dotenv pydantic

# RUN:
#     uvicorn bonvoice_call_initiate:app --reload --port 8000

# TEST:
#     curl --location 'http://localhost:8000/api/call/initiate' \
#     --header 'Content-Type: application/json' \
#     --data '{
#         "phone_number": "9846098460",
#         "prompt_type": "outbound_reconfirmation",
#         "parent_name": "Anita Sharma",
#         "student_name": "Riya Sharma",
#         "appointment_type": "Campus Visit",
#         "appointment_date": "2026-09-15",
#         "appointment_time": "11:00 AM"
#     }'
# """

# import os
# import uuid
# import logging
# from typing import Optional
# from urllib.parse import urlencode

# import httpx
# from dotenv import load_dotenv
# from fastapi import FastAPI, HTTPException, Request
# from fastapi.exceptions import RequestValidationError
# from fastapi.responses import JSONResponse
# from pydantic import BaseModel, Field, field_validator

# load_dotenv()

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger("bonvoice")

# app = FastAPI(title="SchoolKnot - Bonvoice Call Initiate API")


# @app.exception_handler(RequestValidationError)
# async def validation_exception_handler(request: Request, exc: RequestValidationError):
#     """
#     Converts FastAPI's default 422 validation errors into a clean 400
#     response with a simple 'detail' message, matching what we've
#     documented for SchoolKnot's integration team.
#     """
#     first_error = exc.errors()[0]
#     field = ".".join(str(loc) for loc in first_error["loc"] if loc != "body")
#     message = f"{field}: {first_error['msg']}" if field else first_error["msg"]
#     logger.warning("Validation failed: %s", message)
#     return JSONResponse(status_code=400, content={"detail": message})


# BONVOICE_BASE_URL = "https://backend.pbx.bonvoice.com/autoDialManagement/autoCallBridging/"

# BONVOICE_AUTH_TOKEN = os.getenv("BONVOICE_AUTH_TOKEN")
# BONVOICE_VOICEBOT_PROVIDER = os.getenv("BONVOICE_VOICEBOT_PROVIDER", "BONVOICE")
# BONVOICE_VOICEBOT_BASE_URL = os.getenv("BONVOICE_VOICEBOT_BASE_URL")
# BONVOICE_DID_NUMBER = os.getenv("BONVOICE_DID_NUMBER")

# VALID_PROMPT_TYPES = {
#     "outbound_new_lead", "outbound_follow_up", "outbound_admission_reminder",
#     "outbound_event_invite", "outbound_reengagement", "outbound_reconfirmation",
# }


# # ── Request/response models — this IS the contract given to SchoolKnot ──

# class CallInitiateRequest(BaseModel):
#     # ── Required ──
#     phone_number: str = Field(..., description="Number to dial, e.g. '9550335589' or '+919550335589'")
#     prompt_type: str = Field(..., description=f"One of: {sorted(VALID_PROMPT_TYPES)}")

#     # ── Context — optional, but the more you send, the less the agent
#     #    has to ask on the call ──
#     parent_name: Optional[str] = None
#     student_name: Optional[str] = None
#     grade: Optional[str] = None
#     branch_name: Optional[str] = None
#     enquiry_status: Optional[str] = None
#     call_purpose: Optional[str] = Field(
#         default=None, description="Why this call is happening, e.g. 'enquired online last week'."
#     )
#     notes: Optional[str] = None
#     enquiry_id: Optional[int] = None

#     # ── Only used when prompt_type = outbound_reconfirmation ──
#     appointment_type: Optional[str] = None
#     appointment_date: Optional[str] = None
#     appointment_time: Optional[str] = None

#     @field_validator("phone_number")
#     @classmethod
#     def validate_phone_number(cls, value: str) -> str:
#         digits = "".join(ch for ch in value if ch.isdigit())
#         if digits.startswith("91") and len(digits) > 10:
#             digits = digits[2:]
#         if len(digits) != 10:
#             raise ValueError("must be a valid 10-digit number (with or without +91 prefix)")
#         return digits

#     @field_validator("prompt_type")
#     @classmethod
#     def validate_prompt_type(cls, value: str) -> str:
#         if value not in VALID_PROMPT_TYPES:
#             raise ValueError(f"must be one of {sorted(VALID_PROMPT_TYPES)}")
#         return value


# class CallInitiateResponse(BaseModel):
#     success: bool
#     call_reference: str
#     responseCode: Optional[int] = None
#     responseDescription: Optional[str] = None
#     responseType: Optional[str] = None


# def _build_voicebot_url(call_reference: str) -> str:
#     """
#     Bonvoice enforces a 255-character limit on voicebotURL (backend DB
#     column constraint), so we can't pack full lead context into the URL
#     like we first tried. Instead, we send only a short call_reference,
#     and store the full context in CALL_CONTEXT_STORE (below) so the
#     websocket bot can fetch it via GET /api/call-context/{call_reference}
#     right after connecting.
#     """
#     return f"{BONVOICE_VOICEBOT_BASE_URL}?call_reference={call_reference}"


# # ── Temporary in-memory store for lead context ──────────────────────────
# # NOTE: This resets if the server restarts, and won't work across
# # multiple server instances. For production, replace this with a
# # proper store (Redis, or a Postgres table — you already have a
# # Postgres connection in main.py, so a `call_context` table there
# # would be the more robust long-term fix).
# CALL_CONTEXT_STORE: dict[str, dict] = {}


# def _build_call_context(call_reference: str, req: CallInitiateRequest) -> dict:
#     context = {
#         "call_reference": call_reference,
#         "prompt_type": req.prompt_type,
#         "lead_name": req.parent_name or "there",
#         "caller_status": "existing" if (req.enquiry_status or req.enquiry_id) else "new",
#         "parent_name": req.parent_name,
#         "student_name": req.student_name,
#         "grade": req.grade,
#         "branch_name": req.branch_name,
#         "enquiry_status": req.enquiry_status,
#         "call_purpose": req.call_purpose,
#         "notes": req.notes,
#         "appointment_type": req.appointment_type,
#         "appointment_date": req.appointment_date,
#         "appointment_time": req.appointment_time,
#         "enquiry_id": req.enquiry_id,
#     }
#     return {k: v for k, v in context.items() if v not in (None, "")}


# @app.get("/api/call-context/{call_reference}")
# async def get_call_context(call_reference: str):
#     """
#     Your websocket bot calls this right after a call connects, using
#     the call_reference it received as a query param on the voicebotURL,
#     to fetch the full lead context for this call.
#     """
#     context = CALL_CONTEXT_STORE.get(call_reference)
#     if not context:
#         raise HTTPException(status_code=404, detail="No context found for this call_reference.")
#     return context


# @app.post("/api/call/initiate", response_model=CallInitiateResponse)
# async def initiate_call(payload: CallInitiateRequest):
#     if not all([BONVOICE_AUTH_TOKEN, BONVOICE_VOICEBOT_BASE_URL, BONVOICE_DID_NUMBER]):
#         raise HTTPException(
#             status_code=500,
#             detail="Server misconfiguration: check BONVOICE_AUTH_TOKEN, "
#                    "BONVOICE_VOICEBOT_BASE_URL, and BONVOICE_DID_NUMBER env vars.",
#         )

#     call_reference = f"SCHOOLKNOT-{uuid.uuid4().hex[:12]}"
#     voicebot_url = _build_voicebot_url(call_reference)
#     CALL_CONTEXT_STORE[call_reference] = _build_call_context(call_reference, payload)

#     logger.info(
#         "Call initiate requested | ref=%s phone=%s prompt_type=%s",
#         call_reference, payload.phone_number, payload.prompt_type,
#     )

#     body = {
#         "autocallType": "5",
#         "destination": payload.phone_number,
#         "legACallerID": BONVOICE_DID_NUMBER,
#         "eventID": call_reference,
#         "voicebotProvider": BONVOICE_VOICEBOT_PROVIDER,
#         "voicebotURL": voicebot_url,
#     }

#     headers = {
#         "Authorization": f"Token {BONVOICE_AUTH_TOKEN}",
#         "Content-Type": "application/json",
#     }

#     try:
#         async with httpx.AsyncClient(timeout=10.0) as client:
#             response = await client.post(BONVOICE_BASE_URL, json=body, headers=headers)
#             logger.info("Bonvoice raw response [%s]: %s", response.status_code, response.text)
#             response.raise_for_status()
#             data = response.json()

#         # Bonvoice sometimes returns HTTP 200 with an error payload instead
#         # of a proper error status code. We've seen two formats so far:
#         #   {"error": "DID is not configured"}
#         #   {"status": "error", "message": "value too long for type character varying(255)"}
#         if "error" in data or data.get("status") == "error":
#             error_message = data.get("error") or data.get("message") or str(data)
#             logger.error("[%s] Bonvoice returned an error payload: %s", call_reference, data)
#             raise HTTPException(status_code=502, detail=f"Bonvoice API error: {error_message}")

#         return CallInitiateResponse(
#             success=data.get("responseCode") == 200,
#             call_reference=call_reference,
#             responseCode=data.get("responseCode"),
#             responseDescription=data.get("responseDescription"),
#             responseType=data.get("responseType"),
#         )

#     except httpx.HTTPStatusError as e:
#         logger.error("[%s] Bonvoice returned error: %s", call_reference, e.response.text)
#         raise HTTPException(status_code=e.response.status_code, detail=f"Bonvoice API error: {e.response.text}")
#     except httpx.RequestError as e:
#         logger.error("[%s] Network error calling Bonvoice: %s", call_reference, str(e))
#         raise HTTPException(status_code=502, detail=f"Could not reach Bonvoice API: {str(e)}")
"""
Bonvoice Auto Call Bridging (Call Initiate) API Wrapper - FastAPI Router
Client: SchoolKnot

This service wraps Bonvoice's Auto Call Bridging API and exposes a rich
endpoint for SchoolKnot to trigger outbound calls with full lead context
(parent name, student name, appointment details, etc.) — mirroring the
same contract used for the VoiceLink integration.

Upstream Bonvoice docs: https://backend.pbx.bonvoice.com/autoDialManagement/autoCallBridging/

------------------------------------------------------------------------
HOW LEAD CONTEXT REACHES YOUR VOICE AGENT:
------------------------------------------------------------------------
Bonvoice's API does NOT have a `custom_parameters` field like VoiceLink
does. Instead, its `voicebotURL` parameter can be set dynamically per
call. So we take all the lead-context fields SchoolKnot sends us and
encode them as QUERY PARAMETERS on the voicebotURL we pass to Bonvoice.

Example voicebotURL sent to Bonvoice:
    wss://your-bot.onrender.com/ws/voice-agent?call_reference=...

Your websocket bot (ws_call_handler.py) should read the call_reference
query parameter as soon as the connection is established, then fetch
the full lead context via GET /api/call-context/{call_reference}.

------------------------------------------------------------------------
EXPOSED ENDPOINT (this is the contract given to SchoolKnot):
------------------------------------------------------------------------
POST /api/call/initiate

Required:
    phone_number   (str)  Number to dial, e.g. '9550335589' or '+919550335589'
    prompt_type    (str)  One of: outbound_new_lead, outbound_follow_up,
                          outbound_admission_reminder, outbound_event_invite,
                          outbound_reengagement, outbound_reconfirmation

Optional lead context (send whatever you have):
    parent_name, student_name, grade, branch_name, enquiry_status,
    call_purpose, notes, enquiry_id

Optional — only used when prompt_type = outbound_reconfirmation:
    appointment_type, appointment_date, appointment_time

Response codes:
    200  -> Call successfully triggered (does NOT mean it was answered)
    400  -> Missing/invalid phone_number or invalid prompt_type
    500  -> Server misconfiguration (env vars not set)
    502  -> Bonvoice/upstream error (e.g. "DID is not configured")

------------------------------------------------------------------------

ENV VARIABLES REQUIRED (add to your existing .env, same one main.py reads):
    BONVOICE_AUTH_TOKEN=your_auth_token_here
    BONVOICE_VOICEBOT_PROVIDER=BONVOICE
    BONVOICE_VOICEBOT_BASE_URL=wss://your-bot.onrender.com/ws/voice-agent
    BONVOICE_DID_NUMBER=7946350797   # your Bonvoice-configured outbound DID

------------------------------------------------------------------------
INTEGRATION NOTE (why this file changed from before):
------------------------------------------------------------------------
This used to be its own standalone `FastAPI()` app, which meant it never
actually ran together with main.py (uvicorn main:app only serves main.py's
app). It's now an `APIRouter`, included directly into main.py's app via:

    from bonvoice_call_initiate import router as bonvoice_router
    app.include_router(bonvoice_router)

So do NOT run this file directly with uvicorn anymore — it's not a
standalone entry point. Run `main.py` as before; this router now rides
along inside it.
"""

import os
import uuid
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("bonvoice")

router = APIRouter(tags=["Bonvoice Call Initiate"])


BONVOICE_BASE_URL = "https://backend.pbx.bonvoice.com/autoDialManagement/autoCallBridging/"

BONVOICE_AUTH_TOKEN = os.getenv("BONVOICE_AUTH_TOKEN")
BONVOICE_VOICEBOT_PROVIDER = os.getenv("BONVOICE_VOICEBOT_PROVIDER", "BONVOICE")
BONVOICE_VOICEBOT_BASE_URL = os.getenv("BONVOICE_VOICEBOT_BASE_URL")
BONVOICE_DID_NUMBER = os.getenv("BONVOICE_DID_NUMBER")

VALID_PROMPT_TYPES = {
    "outbound_new_lead", "outbound_follow_up", "outbound_admission_reminder",
    "outbound_event_invite", "outbound_reengagement", "outbound_reconfirmation",
}


# ── Request/response models — this IS the contract given to SchoolKnot ──

class CallInitiateRequest(BaseModel):
    # ── Required ──
    phone_number: str = Field(..., description="Number to dial, e.g. '9550335589' or '+919550335589'")
    prompt_type: str = Field(..., description=f"One of: {sorted(VALID_PROMPT_TYPES)}")

    # ── Context — optional, but the more you send, the less the agent
    #    has to ask on the call ──
    parent_name: Optional[str] = None
    student_name: Optional[str] = None
    grade: Optional[str] = None
    branch_name: Optional[str] = None
    enquiry_status: Optional[str] = None
    call_purpose: Optional[str] = Field(
        default=None, description="Why this call is happening, e.g. 'enquired online last week'."
    )
    notes: Optional[str] = None
    enquiry_id: Optional[int] = None

    # ── Only used when prompt_type = outbound_reconfirmation ──
    appointment_type: Optional[str] = None
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits.startswith("91") and len(digits) > 10:
            digits = digits[2:]
        if len(digits) != 10:
            raise ValueError("must be a valid 10-digit number (with or without +91 prefix)")
        return digits

    @field_validator("prompt_type")
    @classmethod
    def validate_prompt_type(cls, value: str) -> str:
        if value not in VALID_PROMPT_TYPES:
            raise ValueError(f"must be one of {sorted(VALID_PROMPT_TYPES)}")
        return value


class CallInitiateResponse(BaseModel):
    success: bool
    call_reference: str
    responseCode: Optional[int] = None
    responseDescription: Optional[str] = None
    responseType: Optional[str] = None


def _build_voicebot_url(call_reference: str) -> str:
    """
    Bonvoice enforces a 255-character limit on voicebotURL (backend DB
    column constraint), so we can't pack full lead context into the URL
    like we first tried. Instead, we send only a short call_reference,
    and store the full context in CALL_CONTEXT_STORE (below) so the
    websocket bot can fetch it via GET /api/call-context/{call_reference}
    right after connecting.
    """
    return f"{BONVOICE_VOICEBOT_BASE_URL}?call_reference={call_reference}"


# ── Temporary in-memory store for lead context ──────────────────────────
# NOTE: This resets if the server restarts, and won't work across
# multiple server instances. For production, replace this with a
# proper store (Redis, or a Postgres table — you already have a
# Postgres connection in main.py, so a `call_context` table there
# would be the more robust long-term fix).
CALL_CONTEXT_STORE: dict[str, dict] = {}


def _build_call_context(call_reference: str, req: CallInitiateRequest) -> dict:
    context = {
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
    return {k: v for k, v in context.items() if v not in (None, "")}


@router.get("/api/call-context/{call_reference}")
async def get_call_context(call_reference: str):
    """
    Your websocket bot calls this right after a call connects, using
    the call_reference it received as a query param on the voicebotURL,
    to fetch the full lead context for this call.
    """
    context = CALL_CONTEXT_STORE.get(call_reference)
    if not context:
        raise HTTPException(status_code=404, detail="No context found for this call_reference.")
    return context


@router.post("/api/call/initiate", response_model=CallInitiateResponse)
async def initiate_call(payload: CallInitiateRequest):
    if not all([BONVOICE_AUTH_TOKEN, BONVOICE_VOICEBOT_BASE_URL, BONVOICE_DID_NUMBER]):
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: check BONVOICE_AUTH_TOKEN, "
                   "BONVOICE_VOICEBOT_BASE_URL, and BONVOICE_DID_NUMBER env vars.",
        )

    call_reference = f"SCHOOLKNOT-{uuid.uuid4().hex[:12]}"
    voicebot_url = _build_voicebot_url(call_reference)
    CALL_CONTEXT_STORE[call_reference] = _build_call_context(call_reference, payload)

    logger.info(
        "Call initiate requested | ref=%s phone=%s prompt_type=%s",
        call_reference, payload.phone_number, payload.prompt_type,
    )

    body = {
        "autocallType": "5",
        "destination": payload.phone_number,
        "legACallerID": BONVOICE_DID_NUMBER,
        "eventID": call_reference,
        "voicebotProvider": BONVOICE_VOICEBOT_PROVIDER,
        "voicebotURL": voicebot_url,
    }

    headers = {
        "Authorization": f"Token {BONVOICE_AUTH_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(BONVOICE_BASE_URL, json=body, headers=headers)
            logger.info("Bonvoice raw response [%s]: %s", response.status_code, response.text)
            response.raise_for_status()
            data = response.json()

        # Bonvoice sometimes returns HTTP 200 with an error payload instead
        # of a proper error status code. We've seen two formats so far:
        #   {"error": "DID is not configured"}
        #   {"status": "error", "message": "value too long for type character varying(255)"}
        if "error" in data or data.get("status") == "error":
            error_message = data.get("error") or data.get("message") or str(data)
            logger.error("[%s] Bonvoice returned an error payload: %s", call_reference, data)
            raise HTTPException(status_code=502, detail=f"Bonvoice API error: {error_message}")

        return CallInitiateResponse(
            success=data.get("responseCode") == 200,
            call_reference=call_reference,
            responseCode=data.get("responseCode"),
            responseDescription=data.get("responseDescription"),
            responseType=data.get("responseType"),
        )

    except httpx.HTTPStatusError as e:
        logger.error("[%s] Bonvoice returned error: %s", call_reference, e.response.text)
        raise HTTPException(status_code=e.response.status_code, detail=f"Bonvoice API error: {e.response.text}")
    except httpx.RequestError as e:
        logger.error("[%s] Network error calling Bonvoice: %s", call_reference, str(e))
        raise HTTPException(status_code=502, detail=f"Could not reach Bonvoice API: {str(e)}")