"""Shared data models and enums for the Bulk Lead Dialer Campaign System."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lead_info import LeadInfo


class LeadStatus(str, Enum):
    PENDING     = "Pending"
    DIALING     = "Dialing"
    IN_PROGRESS = "In_Progress"
    COMPLETED   = "Completed"
    FAILED      = "Failed"
    NOT_PICKED  = "Not_Picked"
    CANCELLED   = "Cancelled"


class CampaignStatus(str, Enum):
    IDLE     = "Idle"
    RUNNING  = "Running"
    PAUSED   = "Paused"
    FINISHED = "Finished"


@dataclass
class Lead:
    lead_id: str
    name: str
    phone: str
    company: str
    extra: dict[str, str]
    status: LeadStatus = LeadStatus.PENDING
    classification: Optional[str] = None
    call_sid: Optional[str] = None
    call_duration_seconds: Optional[float] = None
    transcript_summary: Optional[str] = None
    error: Optional[str] = None
    # Live snapshot of extracted info — populated during the call
    collected_info: Optional["LeadInfo"] = None


@dataclass
class ParseResult:
    leads: list[Lead]
    skipped_rows: list[dict]
    warnings: list[str]
    original_columns: list[str]


@dataclass
class CampaignStats:
    # Status counts
    total: int = 0
    pending: int = 0
    dialing: int = 0
    in_progress: int = 0
    completed: int = 0
    failed: int = 0
    not_picked: int = 0
    cancelled: int = 0
    # Classification counts
    hot: int = 0
    warm: int = 0
    cold: int = 0
    not_picked_classification: int = 0


@dataclass
class Campaign:
    campaign_id: str
    name: str
    created_at: datetime
    concurrency_limit: int
    virtual_number: str
    inter_call_delay_ms: int
    status: CampaignStatus
    original_columns: list[str] = field(default_factory=list)
