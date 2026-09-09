"""
org_config.py — Per-organisation (tenant) configuration store.

Provides an in-memory store keyed by org_id with optional PostgreSQL
persistence.  Falls back to the global config.py defaults when no
org-specific config exists.

Usage:
    from org_config import get_org_config, upsert_org_config, list_orgs, delete_org

    # Get config for a tenant (returns merged dict: org overrides + global defaults)
    cfg = get_org_config("acme-corp")

    # Create / update an org
    upsert_org_config("acme-corp", {"company_name": "Acme Corp", "agent_name": "Priya"})

    # List all registered orgs
    orgs = list_orgs()
"""
from __future__ import annotations

import logging
import time
from copy import deepcopy
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# ── In-memory store ───────────────────────────────────────────────────────────
# Structure: { org_id: { ...config fields... } }
_ORG_STORE: dict[str, dict[str, Any]] = {}

# ── Fields that can be configured per org ────────────────────────────────────
ORG_CONFIG_FIELDS = [
    # Agent identity
    "agent_name",
    "company_name",
    "product_name",
    "agent_language",
    "gemini_voice",
    "gemini_speaking_rate",
    # Business details
    "business_type",
    "operating_city",
    "company_email",
    "company_legal_name",
    "industry_experience",
    "sales_manager_name",
    "product_restrictions",
    "business_context",
    # Prompt customisation
    "opening_question",
    "qualify_questions",
    "pitch_lines",
    # Calling window
    "calling_window_start",
    "calling_window_end",
    "calling_window_tz",
    # Quality
    "min_connection_rate",
]


def _global_defaults() -> dict[str, Any]:
    """Return current global config values as a dict (read live so hot-patches apply)."""
    import config as _cfg
    return {
        "agent_name":           _cfg.AGENT_NAME,
        "company_name":         _cfg.COMPANY_NAME,
        "product_name":         _cfg.PRODUCT_NAME,
        "agent_language":       _cfg.AGENT_LANGUAGE,
        "gemini_voice":         _cfg.GEMINI_VOICE,
        "gemini_speaking_rate": _cfg.GEMINI_SPEAKING_RATE,
        "business_type":        _cfg.BUSINESS_TYPE,
        "operating_city":       _cfg.OPERATING_CITY,
        "company_email":        _cfg.COMPANY_EMAIL,
        "company_legal_name":   _cfg.COMPANY_LEGAL_NAME,
        "industry_experience":  _cfg.INDUSTRY_EXPERIENCE,
        "sales_manager_name":   _cfg.SALES_MANAGER_NAME,
        "product_restrictions": _cfg.PRODUCT_RESTRICTIONS,
        "business_context":     _cfg.BUSINESS_CONTEXT,
        "opening_question":     _cfg.OPENING_QUESTION,
        "qualify_questions":    _cfg.QUALIFY_QUESTIONS,
        "pitch_lines":          _cfg.PITCH_LINES,
        "calling_window_start": _cfg.CALLING_WINDOW_START,
        "calling_window_end":   _cfg.CALLING_WINDOW_END,
        "calling_window_tz":    _cfg.CALLING_WINDOW_TZ,
        "min_connection_rate":  _cfg.MIN_CONNECTION_RATE,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def get_org_config(org_id: str) -> dict[str, Any]:
    """
    Return the merged config for an org.
    Org-specific values override global defaults; missing keys fall back to globals.
    Returns global defaults if org_id is not registered.
    """
    defaults = _global_defaults()
    org = _ORG_STORE.get(org_id)
    if not org:
        return defaults
    # Merge: org values win, globals fill gaps
    return {**defaults, **{k: v for k, v in org.items() if v not in (None, "")}}


def upsert_org_config(org_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """
    Create or update an org's config.
    Only recognised ORG_CONFIG_FIELDS are stored; unknown keys are ignored.
    Returns the full merged config after the update.
    """
    existing = _ORG_STORE.get(org_id, {})
    # Keep only known fields, strip None values so they fall back to defaults
    updates = {k: v for k, v in data.items() if k in ORG_CONFIG_FIELDS}
    existing.update(updates)

    # Ensure metadata fields are present
    if "_org_id" not in existing:
        existing["_org_id"] = org_id
    if "_created_at" not in existing:
        existing["_created_at"] = time.time()
    existing["_updated_at"] = time.time()

    _ORG_STORE[org_id] = existing
    logger.info("org_config upserted: org_id=%r fields=%r", org_id, list(updates.keys()))
    return get_org_config(org_id)


def delete_org(org_id: str) -> bool:
    """Remove an org's config from the store. Returns True if it existed."""
    existed = org_id in _ORG_STORE
    _ORG_STORE.pop(org_id, None)
    return existed


def list_orgs() -> list[dict[str, Any]]:
    """Return a list of all registered orgs with their stored (non-default) fields."""
    return [
        {
            "org_id":     v["_org_id"],
            "created_at": v.get("_created_at"),
            "updated_at": v.get("_updated_at"),
            **{k: val for k, val in v.items() if not k.startswith("_")},
        }
        for v in _ORG_STORE.values()
    ]


def get_raw_org(org_id: str) -> Optional[dict[str, Any]]:
    """Return only the stored (non-default) fields for an org, or None if not found."""
    entry = _ORG_STORE.get(org_id)
    if not entry:
        return None
    return {k: v for k, v in entry.items() if not k.startswith("_")}
