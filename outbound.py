"""Trigger an outbound call via Exotel Make-a-Call API."""
import re
import httpx
import logging
from config import (
    EXOTEL_API_KEY, EXOTEL_API_TOKEN, EXOTEL_SID,
    EXOTEL_SUBDOMAIN, EXOTEL_CALLER_ID, EXOTEL_APP_ID, PUBLIC_URL,
)

logger = logging.getLogger(__name__)

EXOTEL_CALL_URL = (
    f"https://{EXOTEL_API_KEY}:{EXOTEL_API_TOKEN}"
    f"@{EXOTEL_SUBDOMAIN}/v1/Accounts/{EXOTEL_SID}/Calls/connect"
)
EXOTEL_APP_URL = f"http://my.exotel.in/exoml/start/{EXOTEL_APP_ID}"


async def make_outbound_call(
    to: str,
    from_: str = EXOTEL_CALLER_ID,
    lead_name: str = "there",
    lead_company: str = "",
    call_context: str = "",
    record: bool = True,
    prompt_type: str = "sales",
) -> dict:
    """Place an outbound call via Exotel. Returns {"call_sid": str, "raw": str}."""
    # Normalise to Exotel's 0XXXXXXXXXX format
    if to.startswith("+91"):
        to = "0" + to[3:]
    elif not to.startswith("0") and len(to) == 10:
        to = "0" + to

    exoml_url = (
        f"{PUBLIC_URL}/exoml"
        f"?lead_name={lead_name}&lead_company={lead_company}"
        f"&call_context={call_context}&prompt_type={prompt_type}&outbound=true"
    )

    payload = {
        "From":           to,
        "CallerId":       from_,
        "Url":            EXOTEL_APP_URL,
        "CallType":       "trans",
        "Record":         "true" if record else "false",
        "StatusCallback": f"{PUBLIC_URL}/call-status",
        "CustomField":    f"lead_name={lead_name}&lead_company={lead_company}&outbound=true&prompt_type={prompt_type}",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(EXOTEL_CALL_URL, data=payload)
        resp.raise_for_status()
        sid_match = re.search(r"<Sid>([^<]+)</Sid>", resp.text)
        call_sid = sid_match.group(1) if sid_match else "unknown"
        logger.info(f"Outbound call placed: {call_sid}")
        return {"call_sid": call_sid, "raw": resp.text}
