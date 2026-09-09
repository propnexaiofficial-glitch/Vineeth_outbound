"""
call_data_store.py

In-memory store for completed-call data that SchoolKnot pulls via
GET /api/call-details/{call_id}. Swap for a real table (Postgres/Mongo —
you already have both) before production; the two functions below are
the only thing that needs to change.
"""
from typing import Optional

_store: dict[str, dict] = {}


def save_call_data(call_id: str, data: dict) -> None:
    _store[call_id] = data


def get_call_data(call_id: str) -> Optional[dict]:
    return _store.get(call_id)