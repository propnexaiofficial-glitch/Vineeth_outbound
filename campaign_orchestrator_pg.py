"""CampaignOrchestrator — manages campaigns with PostgreSQL persistence."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from campaign_models import Campaign, CampaignStatus, LeadStatus
import pg_db
import event_bus
from outbound import make_outbound_call
from classifier import classify_and_analyze
from config import CLIENT_ID, MIN_CONNECTION_RATE
from scheduler import CallingWindowChecker
import credit_service
from credit_service import InsufficientCreditsError

logger = logging.getLogger(__name__)

# Terminal statuses used for CSV export filtering
_TERMINAL_STATUSES = {
    LeadStatus.COMPLETED,
    LeadStatus.FAILED,
    LeadStatus.NOT_PICKED,
    LeadStatus.CANCELLED,
}


class CampaignOrchestratorPG:
    def __init__(self) -> None:
        self._current_campaign_id: Optional[str] = None
        self._pause_event: asyncio.Event = asyncio.Event()
        self._stop_event: asyncio.Event = asyncio.Event()
        self._dispatch_task: Optional[asyncio.Task] = None
        self._pending_leads: list = []
        self._pending_columns: list[str] = []

    def store_pending_leads(self, leads: list, original_columns: list[str]) -> str:
        """Store parsed leads temporarily until /campaign/start is called. Returns an upload_id."""
        self._pending_leads = leads
        self._pending_columns = original_columns
        return str(uuid4())

    # ------------------------------------------------------------------
    # Campaign creation
    # ------------------------------------------------------------------

    def create(
        self,
        name: str,
        concurrency_limit: int,
        virtual_number: str,
        inter_call_delay_ms: int,
        leads: list,
        original_columns: list[str],
        calling_window: Optional[dict] = None,
        min_connection_rate: Optional[float] = None,
    ) -> dict:
        """Validate parameters, reject if a campaign is active, create and persist a new Campaign."""
        if not (1 <= concurrency_limit <= 50):
            raise ValueError(
                f"concurrency_limit must be between 1 and 50 inclusive, got {concurrency_limit}"
            )
        if not (0 <= inter_call_delay_ms <= 5000):
            raise ValueError(
                f"inter_call_delay_ms must be between 0 and 5000 inclusive, got {inter_call_delay_ms}"
            )
        
        # Check if there's an active campaign
        if self._current_campaign_id:
            existing = pg_db.get_campaign(self._current_campaign_id)
            if existing and existing["status"] in ("Running", "Paused"):
                raise ValueError(
                    f"Cannot create a new campaign while campaign '{existing['name']}' "
                    f"is {existing['status']}. Stop or finish it first."
                )

        campaign_id = str(uuid4())
        
        # Create campaign in Postgres
        pg_db.create_campaign(
            campaign_id=campaign_id,
            client_id=CLIENT_ID,
            name=name,
            concurrency_limit=concurrency_limit,
            virtual_number=virtual_number,
            inter_call_delay_ms=inter_call_delay_ms,
            original_columns=original_columns,
            calling_window=calling_window,
            min_connection_rate=min_connection_rate,
        )

        # Insert all contacts
        contacts = []
        for lead in leads:
            contacts.append({
                "lead_id": lead.lead_id,
                "campaign_id": campaign_id,
                "client_id": CLIENT_ID,
                "name": lead.name,
                "phone": lead.phone,
                "company": lead.company,
                "extra": lead.extra,
                "status": lead.status.value,
            })
        pg_db.insert_contacts(contacts)

        self._current_campaign_id = campaign_id
        
        return {
            "campaign_id": campaign_id,
            "name": name,
            "status": "Idle",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Dispatch loop
    # ------------------------------------------------------------------

    async def _dial_lead(self, lead_dict: dict, sem: asyncio.Semaphore, campaign: dict) -> None:
        """Dial a single lead with timeout and retry; always release the semaphore."""
        lead_id = lead_dict["lead_id"]
        campaign_id = campaign["campaign_id"]
        try:
            async with asyncio.timeout(300):
                # Requirements 3.3, 3.4 — credit gate before dialling.
                # Step 1: Check balance first (chicken-and-egg: we need the call_sid
                # to reserve, but we don't have it until after the call is placed).
                balance = credit_service.get_balance(CLIENT_ID)
                if balance == 0:
                    raise InsufficientCreditsError(
                        f"Tenant '{CLIENT_ID}' has insufficient credits."
                    )

                pg_db.update_contact_status(lead_id, LeadStatus.DIALING.value)
                
                # Exponential backoff retry (3 attempts)
                last_exc: Exception | None = None
                for attempt in range(3):
                    try:
                        result = await make_outbound_call(
                            to=lead_dict["phone"],
                            from_=campaign["virtual_number"],
                            lead_name=lead_dict["name"],
                            lead_company=lead_dict["company"],
                        )
                        call_sid = result.get("call_sid") or result.get("Call", {}).get("Sid")
                        if call_sid and call_sid != "unknown":
                            pg_db.update_contact_call_sid(lead_id, call_sid)
                            # Step 2: Reserve 1 credit using the real call_sid.
                            # Slightly racy (balance could drop to 0 between check and
                            # reserve) but acceptable — check_and_reserve will raise
                            # InsufficientCreditsError if another concurrent call consumed
                            # the last credit.
                            try:
                                credit_service.check_and_reserve(CLIENT_ID, call_sid)
                            except InsufficientCreditsError:
                                # Balance was consumed between check and reserve — log but
                                # don't fail the call since it's already been placed.
                                logger.warning(
                                    "Credits exhausted between balance check and reserve for "
                                    "call_sid=%r — call already placed, continuing",
                                    call_sid,
                                )
                            except credit_service.DuplicateReservationError:
                                # Already reserved (shouldn't happen for a fresh call_sid).
                                pass
                        last_exc = None
                        break
                    except Exception as exc:
                        last_exc = exc
                        if attempt < 2:
                            wait = 2 ** attempt
                            logger.warning(
                                "Dial attempt %d failed for lead %s: %s — retrying in %ds",
                                attempt + 1, lead_id, exc, wait,
                            )
                            await asyncio.sleep(wait)
                if last_exc is not None:
                    raise last_exc
        except asyncio.TimeoutError:
            logger.warning("Lead %s timed out after 300s", lead_id)
            pg_db.update_contact_call_result(
                lead_id, LeadStatus.FAILED.value, error="Call timed out"
            )
        except InsufficientCreditsError:
            # Requirements 3.3, 3.4 — pause campaign and emit credits_exhausted event.
            logger.warning(
                "Insufficient credits for lead %s in campaign %s — pausing campaign",
                lead_id, campaign_id,
            )
            pg_db.update_contact_status(lead_id, LeadStatus.CANCELLED.value)
            self._pause_event.clear()
            pg_db.update_campaign_status(campaign_id, CampaignStatus.PAUSED.value)
            event_bus.bus.publish(CLIENT_ID, {
                "type": "credits_exhausted",
                "tenant_id": CLIENT_ID,
                "campaign_id": campaign_id,
            })
        except Exception as exc:
            logger.exception("Failed to dial lead %s: %s", lead_id, exc)
            pg_db.update_contact_call_result(
                lead_id, LeadStatus.FAILED.value, error=str(exc)
            )
        finally:
            sem.release()

    async def _dispatch_loop(self) -> None:
        """Iterate over pending leads, gate concurrency with a semaphore."""
        campaign = pg_db.get_campaign(self._current_campaign_id)
        if not campaign:
            return
        
        sem = asyncio.Semaphore(campaign["concurrency_limit"])
        tasks: set[asyncio.Task] = set()
        _window_checker = CallingWindowChecker()

        # Connection rate tracking
        _calls_since_check: int = 0
        _connected_calls: int = 0

        def _task_done(t: asyncio.Task) -> None:
            tasks.discard(t)

        pending_leads = pg_db.list_contacts(self._current_campaign_id, status="Pending")
        
        for lead in pending_leads:
            if self._stop_event.is_set():
                break
            await self._pause_event.wait()

            # Calling window check
            calling_window = campaign.get("calling_window")
            if calling_window:
                tz = calling_window.get("tz", "UTC")
                start = calling_window.get("start", "00:00")
                end = calling_window.get("end", "23:59")
                while not _window_checker.is_within_window(tz, start, end):
                    wait_secs = _window_checker.get_seconds_until_window_open(tz, start, end)
                    logger.info(
                        "Outside calling window [%s–%s %s]; sleeping %.0fs",
                        start, end, tz, wait_secs,
                    )
                    await asyncio.sleep(min(wait_secs, 60))
                    if self._stop_event.is_set():
                        break
                if self._stop_event.is_set():
                    break

            await asyncio.sleep(campaign["inter_call_delay_ms"] / 1000)
            await sem.acquire()
            task = asyncio.create_task(self._dial_lead(lead, sem, campaign))
            tasks.add(task)
            task.add_done_callback(_task_done)

            # Track connection rate every 50 calls
            _calls_since_check += 1
            lead_after = pg_db.get_contact(lead["lead_id"])
            if lead_after and lead_after.get("status") == LeadStatus.COMPLETED.value:
                _connected_calls += 1

            if _calls_since_check >= 50:
                connection_rate = _connected_calls / _calls_since_check
                threshold = campaign.get("min_connection_rate") or MIN_CONNECTION_RATE
                if connection_rate < threshold:
                    logger.warning(
                        "Connection rate %.2f below threshold %.2f — auto-pausing campaign %s",
                        connection_rate, threshold, self._current_campaign_id,
                    )
                    self._pause_event.clear()
                    pg_db.update_campaign_status(
                        self._current_campaign_id, CampaignStatus.PAUSED.value
                    )
                    event_bus.bus.publish(CLIENT_ID, {
                        "type": "campaign.auto_paused",
                        "campaign_id": self._current_campaign_id,
                        "connection_rate": connection_rate,
                        "threshold": threshold,
                    })
                _calls_since_check = 0
                _connected_calls = 0

        await asyncio.gather(*tasks, return_exceptions=True)
        pg_db.update_campaign_status(
            self._current_campaign_id, 
            CampaignStatus.FINISHED.value,
            finished_at=datetime.now(timezone.utc)
        )

    # ------------------------------------------------------------------
    # Control methods
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Set events, mark campaign RUNNING, launch dispatch loop."""
        if not self._current_campaign_id:
            raise ValueError("No campaign to start. Create one first.")
        self._pause_event.set()
        self._stop_event.clear()
        pg_db.update_campaign_status(self._current_campaign_id, CampaignStatus.RUNNING.value)
        event_bus.bus.publish(CLIENT_ID, {
            "type": "campaign.status_changed",
            "campaign_id": self._current_campaign_id,
            "status": "Running",
        })
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())

    async def pause(self) -> None:
        """Pause dispatching new calls (in-progress calls continue)."""
        if not self._current_campaign_id:
            raise ValueError("No active campaign.")
        self._pause_event.clear()
        pg_db.update_campaign_status(self._current_campaign_id, CampaignStatus.PAUSED.value)
        event_bus.bus.publish(CLIENT_ID, {
            "type": "campaign.status_changed",
            "campaign_id": self._current_campaign_id,
            "status": "Paused",
        })

    async def resume(self) -> None:
        """Resume dispatching after a pause."""
        if not self._current_campaign_id:
            raise ValueError("No active campaign.")
        self._pause_event.set()
        pg_db.update_campaign_status(self._current_campaign_id, CampaignStatus.RUNNING.value)
        event_bus.bus.publish(CLIENT_ID, {
            "type": "campaign.status_changed",
            "campaign_id": self._current_campaign_id,
            "status": "Running",
        })

    async def stop(self) -> None:
        """Stop dispatching, cancel all pending leads."""
        if not self._current_campaign_id:
            raise ValueError("No active campaign.")
        self._stop_event.set()
        self._pause_event.set()
        pg_db.update_campaign_status(self._current_campaign_id, CampaignStatus.FINISHED.value)
        event_bus.bus.publish(CLIENT_ID, {
            "type": "campaign.status_changed",
            "campaign_id": self._current_campaign_id,
            "status": "Finished",
        })
        
        # Mark all still-pending leads as CANCELLED
        pending = pg_db.list_contacts(self._current_campaign_id, status="Pending")
        for lead in pending:
            pg_db.update_contact_status(lead["lead_id"], LeadStatus.CANCELLED.value)

    # ------------------------------------------------------------------
    # Exotel /call-status callback
    # ------------------------------------------------------------------

    async def on_call_status_callback(
        self, call_sid: str, status: str, duration: float
    ) -> None:
        """Handle Exotel status callback and update the matching lead."""
        lead = pg_db.get_contact_by_call_sid(call_sid)
        if lead is None:
            logger.warning("on_call_status_callback: unknown call_sid %s", call_sid)
            return

        lead_id = lead["lead_id"]
        status_lower = status.lower()
        
        if status_lower == "completed":
            pg_db.update_contact_call_result(
                lead_id, LeadStatus.COMPLETED.value, duration=duration
            )
        elif status_lower == "no-answer":
            pg_db.update_contact_call_result(
                lead_id, LeadStatus.NOT_PICKED.value, 
                duration=duration, classification="Not_Picked"
            )
        elif status_lower in ("failed", "busy", "canceled"):
            pg_db.update_contact_call_result(
                lead_id, LeadStatus.FAILED.value, duration=duration
            )
        else:
            logger.debug("Unhandled Exotel status '%s' for call_sid %s", status, call_sid)

        # Requirements 4.2, 4.3 — finalise credit deduction for this call.
        try:
            credit_service.finalize_call(CLIENT_ID, call_sid, duration)
        except Exception as exc:
            logger.warning(
                "credit_service.finalize_call failed for call_sid=%r: %s", call_sid, exc
            )

    # ------------------------------------------------------------------
    # Results CSV
    # ------------------------------------------------------------------

    def get_results_csv(self) -> str:
        """Return campaign results as a CSV string."""
        if not self._current_campaign_id:
            return ""

        campaign = pg_db.get_campaign(self._current_campaign_id)
        if not campaign:
            return ""

        original_columns = campaign.get("original_columns", [])
        result_columns = [
            "status",
            "classification",
            "call_duration_seconds",
            "transcript_summary",
        ]
        fieldnames = list(original_columns) + result_columns

        # Build case-insensitive lookup
        lower_to_col = {col.lower(): col for col in original_columns}
        name_col = lower_to_col.get("name")
        phone_col = lower_to_col.get("phone")
        company_col = lower_to_col.get("company")

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        is_finished = campaign["status"] == "Finished"
        all_leads = pg_db.list_contacts(self._current_campaign_id)

        for lead in all_leads:
            if not is_finished and lead["status"] not in [s.value for s in _TERMINAL_STATUSES]:
                continue

            row: dict = {}
            # Original columns
            if name_col:
                row[name_col] = lead["name"]
            if phone_col:
                row[phone_col] = lead["phone"]
            if company_col:
                row[company_col] = lead["company"]
            for key, val in (lead.get("extra") or {}).items():
                row[key] = val
            # Result columns
            row["status"] = lead["status"] or ""
            row["classification"] = lead["classification"] or ""
            row["call_duration_seconds"] = lead["call_duration_seconds"] if lead["call_duration_seconds"] is not None else ""
            row["transcript_summary"] = lead["transcript_summary"] or ""
            writer.writerow(row)

        return output.getvalue()

    # ------------------------------------------------------------------
    # on_call_end callback
    # ------------------------------------------------------------------

    async def on_call_end_callback(self, call_sid: str, transcript: str, collected_info=None) -> None:
        """Called by ExotelCallHandler._cleanup when a call ends with a transcript."""
        lead = pg_db.get_contact_by_call_sid(call_sid)
        if lead is None:
            logger.warning("on_call_end_callback: unknown call_sid %s", call_sid)
            return

        lead_id = lead["lead_id"]
        
        # Use LLM-powered analysis
        classification, summary, score = await classify_and_analyze(
            transcript=transcript,
            duration=lead["call_duration_seconds"] or 0,
            status=lead["status"] or '',
            lead_id=lead_id,
            campaign_id=lead["campaign_id"],
        )
        
        if lead["status"] not in ("Failed", "Not_Picked", "Cancelled"):
            pg_db.update_contact_call_result(
                lead_id,
                LeadStatus.COMPLETED.value,
                classification=classification,
                transcript_summary=summary,
            )
        else:
            pg_db.update_contact_call_result(
                lead_id,
                lead["status"],
                classification=classification,
                transcript_summary=summary,
            )

        event_bus.bus.publish(CLIENT_ID, {
            "type": "lead.call_completed",
            "lead_id": lead_id,
            "campaign_id": lead["campaign_id"],
            "classification": classification,
            "score": score,
        })

    # ------------------------------------------------------------------
    # get_status helper
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return campaign metadata, stats, and per-lead list."""
        if not self._current_campaign_id:
            return {}

        campaign = pg_db.get_campaign(self._current_campaign_id)
        if not campaign:
            return {}

        stats = pg_db.get_campaign_stats(self._current_campaign_id)
        leads = []
        
        for lead in pg_db.list_contacts(self._current_campaign_id):
            # Get collected_info from MongoDB lead_info if available
            collected_info = {}
            try:
                from db import get_db
                lead_info_doc = get_db().lead_info.find_one({"lead_id": lead["lead_id"]})
                if lead_info_doc:
                    collected_info = {k: v for k, v in lead_info_doc.items() 
                                    if k not in ("_id", "lead_id", "client_id", "campaign_id") 
                                    and v not in (None, [], False)}
            except Exception:
                pass

            leads.append({
                "lead_id": lead["lead_id"],
                "name": lead["name"],
                "phone": lead["phone"],
                "status": lead["status"],
                "classification": lead["classification"],
                "call_duration_seconds": lead["call_duration_seconds"],
                "collected_info": collected_info,
            })

        return {
            "campaign_id": campaign["campaign_id"],
            "name": campaign["name"],
            "status": campaign["status"],
            "stats": {
                "total": stats.get("total", 0),
                "pending": stats.get("pending", 0),
                "dialing": stats.get("dialing", 0),
                "in_progress": stats.get("in_progress", 0),
                "completed": stats.get("completed", 0),
                "failed": stats.get("failed", 0),
                "not_picked": stats.get("not_picked", 0),
                "cancelled": stats.get("cancelled", 0),
                "hot": stats.get("hot", 0),
                "warm": stats.get("warm", 0),
                "cold": stats.get("cold", 0),
                "not_picked_classification": stats.get("not_picked_classification", 0),
            },
            "leads": leads,
        }


# Module-level singleton
orchestrator = CampaignOrchestratorPG()
