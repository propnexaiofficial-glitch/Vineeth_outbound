"""In-memory store for call params and pre-started Gemini bridges, keyed by CallSid."""
from typing import Any

_call_params: dict[str, dict] = {}
_call_bridges: dict[str, Any] = {}


def store(call_sid: str, params: dict) -> None:
    _call_params[call_sid] = params


def pop(call_sid: str) -> dict:
    return _call_params.pop(call_sid, {})


def store_bridge(call_sid: str, bridge: Any) -> None:
    _call_bridges[call_sid] = bridge


def pop_bridge(call_sid: str) -> Any:
    return _call_bridges.pop(call_sid, None)
