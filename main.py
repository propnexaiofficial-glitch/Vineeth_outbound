"""
Endpoints:
  GET  /health              — health check
  POST /livekit/create-room — create LiveKit room (if USE_LIVEKIT=true)
  POST /campaign/upload     — upload CSV/PDF/image of leads
  POST /campaign/start      — start campaign
  POST /campaign/pause      — pause campaign
  POST /campaign/resume     — resume campaign
  POST /campaign/stop       — stop campaign
  GET  /campaign/status     — campaign status + per-lead data
  GET  /campaign/results    — download results CSV
  GET  /leads/{id}/info     — extracted lead info
  GET  /api/insights/*      — call insights API
  GET  /api/credits/*       — credits API
  GET  /api/analytics/*     — analytics API
  GET  /api/events/stream   — SSE real-time event stream
  GET  /dashboard           — simple HTML monitoring dashboard
  GET  /api/call-details/{call_id}  — ⭐ API handed over to SchoolKnot
  POST /api/call/initiate           — ⭐ Bonvoice call-initiate API handed over to SchoolKnot
  GET  /api/call-context/{call_reference} — internal, used by ws bot to fetch lead context
"""
import asyncio
import hashlib
import importlib
import json
import logging
import os
import re
import time as _time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import psycopg2.extras
import uvicorn
from fastapi import FastAPI, WebSocket, Request, HTTPException, UploadFile, File
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from config import (
    SERVER_HOST, SERVER_PORT, PUBLIC_URL,
    AGENT_NAME, COMPANY_NAME, USE_LIVEKIT, CLIENT_ID,
    ALLOWED_ORIGINS,
)
from auth_middleware import APIKeyMiddleware
from rate_limiter import RateLimitMiddleware
from campaign_orchestrator_pg import orchestrator
from campaign_models import Lead, LeadStatus
from csv_parser import CSVParseError
from lead_info import get as get_lead_info
from ocr_parser import parse_file_to_contacts, SUPPORTED_EXTENSIONS
from call_insights import (
    get_insight, get_insights_by_campaign,
    get_insights_by_category, get_dashboard_summary,
)
import credit_service
from credit_service import DuplicateIdempotencyKeyError
import pg_db
from event_bus import bus

from ws_call_handler import WsCallHandler

# ── SchoolKnot integration ──────────────────────────────────────────────────
from routers_call_details import router as call_details_router
from outbound_call import router as outbound_call_router
from bonvoice_call_initiate import router as bonvoice_router
from call_data_store import save_call_data
# ─────────────────────────────────────────────────────────────────────────────

if USE_LIVEKIT:
    from livekit_handler import create_livekit_room

import structlog
import uuid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()

_TRANSCRIPT_DIR = os.path.join(os.path.dirname(__file__), "transcripts")
os.makedirs(_TRANSCRIPT_DIR, exist_ok=True)


async def _standalone_call_end(call_sid: str, transcript: str, collected_info, recording_path: str = None):
    """Save transcript + collected info to a timestamped file after every standalone call."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_call_sid = re.sub(r'[<>:"/\\|?*]', "_", call_sid)
    filename = os.path.join(_TRANSCRIPT_DIR, f"{ts}_{safe_call_sid}.txt")
    lines = [
        f"Call SID : {call_sid}",
        f"Time     : {datetime.now(timezone.utc).isoformat()}",
        f"Recording: {recording_path or '(not recorded)'}",
        f"",
        f"─── TRANSCRIPT ───────────────────────────────────────────",
        transcript.strip() if transcript.strip() else "(no transcript captured)",
        f"",
        f" COLLECTED INFO ",
        str(collected_info) if collected_info else "(none)",
    ]
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"[{call_sid}] Transcript saved → {filename}")

    school_id = getattr(collected_info, "school_id", "") or ""

    try:
        save_call_data(call_sid, {
            "call_id": call_sid,
            "school_id": school_id,
            "channel_id": school_id,
            "caller_number": getattr(collected_info, "mobile", "") or "",
            "call_direction": "inbound",
            "call_status": "completed",
            "start_time": None,
            "end_time": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": None,
            "language": "en",
            "recording_url": recording_path,
            "transcript": transcript,
            "ai_summary": None,
            "sentiment": None,
            "conversation_quality_score": None,
            "key_topics": [],
            "primary_outcomes": [],
            "secondary_outcomes": getattr(collected_info, "requests", []) or [],
            "tertiary_outcomes": getattr(collected_info, "tertiary_signals", []) or [],
            "linked_enquiry_id": None,
        })
        logger.info(f"[{call_sid}] Call data saved for SchoolKnot pickup (school_id={school_id!r}).")
    except Exception as e:
        logger.error(f"[{call_sid}] Failed to save SchoolKnot call data: {e}")


async def _on_call_end(call_sid: str, transcript: str, collected_info, recording_path: str = None):

    if orchestrator._current_campaign_id is not None:
        campaign = pg_db.get_campaign(orchestrator._current_campaign_id)
        if campaign and campaign["status"] in ("Running", "Paused"):
            await orchestrator.on_call_end_callback(call_sid, transcript, collected_info)
            return
    await _standalone_call_end(call_sid, transcript, collected_info, recording_path)


_on_ws_call_end = _on_call_end


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        pg_db.init_db()
        logger.info("PostgreSQL initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize PostgreSQL", error=str(e))
        raise

    logger.info("/ws/voice-agent is active (SIP handled externally)")

    yield

    logger.info("Shutting down — closing DB pool")
    try:
        pool = pg_db._pool
        if pool:
            pool.closeall()
            logger.info("PostgreSQL connection pool closed")
    except Exception as e:
        logger.error("Error closing DB pool", error=str(e))


app = FastAPI(
    title=f"{COMPANY_NAME} Sales Voice Agent",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(APIKeyMiddleware)
app.add_middleware(RateLimitMiddleware)


# ── Clean 400 response for validation errors ────────────────────────────
# Converts FastAPI's default 422 into a simple 400 + "detail" message,
# matching what's documented for SchoolKnot's integration team
# (e.g. bad/missing phone_number or prompt_type on /api/call/initiate).
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    first_error = exc.errors()[0]
    field = ".".join(str(loc) for loc in first_error["loc"] if loc != "body")
    message = f"{field}: {first_error['msg']}" if field else first_error["msg"]
    logger.warning("Validation failed", path=str(request.url.path), message=message)
    return JSONResponse(status_code=400, content={"detail": message})


app.include_router(call_details_router)
app.include_router(outbound_call_router)
app.include_router(bonvoice_router)


_START_TIME = _time.time()


# ── Health

@app.get("/health")
async def health():
    uptime = int(_time.time() - _START_TIME)

    postgres_status = "ok"
    try:
        pg_db.get_pool()
        with pg_db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception:
        postgres_status = "error"

    mongo_status = "ok"
    try:
        from db import get_db
        get_db().command("ping")
    except Exception:
        mongo_status = "error"

    from config import GEMINI_API_KEY
    gemini_status = "ok" if GEMINI_API_KEY else "not_configured"

    return {
        "status": "ok",
        "postgres": postgres_status,
        "mongo": mongo_status,
        "gemini": gemini_status,
        "version": "2.0.0",
        "uptime_seconds": uptime,
        "agent": AGENT_NAME,
        "company": COMPANY_NAME,
    }


@app.websocket("/ws/voice-agent")
async def voice_agent_ws(websocket: WebSocket):
    await websocket.accept()
    logger.info(f"Voice agent WebSocket connection accepted from {websocket.client}")

    qp = websocket.query_params
    handler = WsCallHandler(
        websocket,
        on_call_end=_on_call_end,
        lead_name=qp.get("lead_name", "there"),
        lead_company=qp.get("lead_company", ""),
        prompt_type=qp.get("prompt_type", "sales"),
        call_context=qp.get("call_context", ""),
        is_outbound=qp.get("is_outbound", "false").lower() == "true",
    )
    await handler.run()


# Recordings

@app.get("/api/recordings")
async def list_recordings_api(page: int = 1, limit: int = 50):
    """List all call recordings, most recent first. Each item includes a
    'play_url' you can open directly in a browser or embed in an <audio> tag."""
    from mongo_recording_store import list_recordings, count_recordings
    skip = (page - 1) * limit
    recordings = list_recordings(limit=limit, skip=skip)
    for r in recordings:
        r["play_url"] = f"/api/recordings/{r['call_id']}"
    total = count_recordings()
    return {
        "success": True,
        "data": recordings,
        "page": page,
        "limit": limit,
        "total": total,
    }


@app.get("/recordings")
async def recordings_dashboard():
    """Browsable page listing every call recording with an inline player.
    No need to remember/type individual call_id URLs."""
    html = """<!doctype html><html><body><h3>Recordings</h3>
    <p>See /api/recordings for the JSON list.</p></body></html>"""

    return Response(content=html, media_type="text/html")


@app.get("/api/recordings/export")
async def export_recordings_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from io import BytesIO
    from mongo_recording_store import list_all_recordings
    from config import PUBLIC_URL

    recordings = list_all_recordings()

    wb = Workbook()
    ws = wb.active
    ws.title = "Recordings"

    headers = ["Call ID", "Recording URL", "Recorded At", "Size (KB)"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    base_url = (PUBLIC_URL or "").rstrip("/")
    for rec in recordings:
        path = f"/api/recordings/{rec['call_id']}"
        url = f"{base_url}{path}" if base_url else path
        size_kb = round(rec["size_bytes"] / 1024, 1) if rec.get("size_bytes") else ""
        row = [rec["call_id"], url, rec.get("uploaded_at", ""), size_kb]
        ws.append(row)
        # Make the URL cell a clickable hyperlink
        url_cell = ws.cell(row=ws.max_row, column=2)
        url_cell.hyperlink = url
        url_cell.style = "Hyperlink"

    for col, width in zip("ABCD", [22, 55, 24, 12]):
        ws.column_dimensions[col].width = width

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="recordings_export.xlsx"'},
    )


@app.get("/api/recordings/{call_id}")
async def get_recording(call_id: str):
    """Stream back the WAV recording for a call, stored in MongoDB GridFS.
    Client can open this URL directly in a browser to play it, or download it."""
    from mongo_recording_store import get_recording_bytes
    data = get_recording_bytes(call_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Recording not found for this call_id")
    return Response(
        content=data,
        media_type="audio/wav",
        headers={"Content-Disposition": f'inline; filename="{call_id}.wav"'},
    )


# Entry point

if __name__ == "__main__":
    workers = int(os.getenv("SERVER_WORKERS", "1"))
    uvicorn.run(
        "main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        workers=workers,
        reload=False,
        log_level="info",
    )