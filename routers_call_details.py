"""
routers_call_details.py

⭐ This is the API you hand over to SchoolKnot. ⭐
"""
import os
from fastapi import APIRouter, Header, HTTPException

from call_data_store import get_call_data, _store

router = APIRouter()

ORBITEL_INBOUND_API_KEY = os.environ.get("ORBITEL_INBOUND_API_KEY", "")


@router.get("/api/call-details/{call_id}")
async def call_details(call_id: str, authorization: str = Header(None)):
    expected = f"Bearer {ORBITEL_INBOUND_API_KEY}"
    if not ORBITEL_INBOUND_API_KEY or authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    data = get_call_data(call_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"No data found for call_id={call_id}")
    return data


@router.get("/api/debug/calls")
async def debug_list_calls():
    return {"stored_call_ids": list(_store.keys())}