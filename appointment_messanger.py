"""
Appointment Messenger — Sends appointment confirmation / reminder / reschedule /
cancellation messages to patients via WhatsApp or SMS.

This is a standalone module, separate from the voice agent prompt system, so it
can be called from anywhere (voice agent backend, booking API, cron job for
reminders, etc.) whenever a patient's appointment status changes.

Supports four send channels out of the box:
    1. Telegram (Bot API)
    2. Twilio (SMS + WhatsApp)
    3. WhatsApp Cloud API (Meta)

If no API credentials are configured, messages are printed to console in
"DRY RUN" mode — useful for testing without sending real messages.

──────────────────────────────────────────────────────────────────
SETUP
──────────────────────────────────────────────────────────────────
For Telegram:
    Set environment variables:
        TELEGRAM_BOT_TOKEN       (from @BotFather)
    Set MESSENGER_CHANNEL=telegram
    Note: Telegram needs the patient's numeric `chat_id`, not their phone
    number. The patient must have started a chat with your bot at least
    once (sent it any message, e.g. /start) before you can message them —
    this is a Telegram platform requirement, not something this code can
    bypass. Pass the chat_id via Appointment.telegram_chat_id.

For Twilio:
    pip install twilio --break-system-packages
    Set environment variables:
        TWILIO_ACCOUNT_SID
        TWILIO_AUTH_TOKEN
        TWILIO_FROM_NUMBER        (e.g. "+14155551234" or "whatsapp:+14155551234")

For WhatsApp Cloud API (Meta):
    Set environment variables:
        WHATSAPP_PHONE_NUMBER_ID
        WHATSAPP_ACCESS_TOKEN

If neither is configured, the module runs in DRY_RUN mode automatically.
──────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

try:
    from dotenv import load_dotenv, find_dotenv

    _dotenv_path = find_dotenv(usecwd=True)
    print("DEBUG .env file being loaded from:", repr(_dotenv_path) or "NOT FOUND")
    load_dotenv(_dotenv_path, override=True)
except ImportError:
    print("DEBUG python-dotenv not installed, skipping .env load")

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

CLINIC_NAME = "CareWell Clinic"
CLINIC_PHONE = "0731-XXXXXXX"
CLINIC_ADDRESS = "123 Main Road, Indore, MP"

# Channel selection: "telegram", "twilio_sms", "twilio_whatsapp", "whatsapp_cloud", "dry_run"
DEFAULT_CHANNEL = os.environ.get("MESSENGER_CHANNEL", "dry_run")

# NOTE: this must be the *name* of the environment variable, not the token
# itself. Set the real token via: export TELEGRAM_BOT_TOKEN="your-token-here"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if TELEGRAM_BOT_TOKEN:
    TELEGRAM_BOT_TOKEN = TELEGRAM_BOT_TOKEN.strip().strip('"').strip("'")

DEFAULT_TELEGRAM_CHAT_ID = os.environ.get("telegram_chat_id")  # optional, from .env
if DEFAULT_TELEGRAM_CHAT_ID:
    DEFAULT_TELEGRAM_CHAT_ID = DEFAULT_TELEGRAM_CHAT_ID.strip().strip('"').strip("'")

print("DEBUG TELEGRAM_BOT_TOKEN:", repr(TELEGRAM_BOT_TOKEN))
print("DEBUG telegram_chat_id:", repr(DEFAULT_TELEGRAM_CHAT_ID))

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN")


# ─────────────────────────────────────────────────────────────
# DATA MODEL
# ─────────────────────────────────────────────────────────────

MessageType = Literal["confirmation", "reminder", "reschedule", "cancellation"]


@dataclass
class Appointment:
    patient_name: str
    patient_phone: str          # E.164 format recommended, e.g. "+919876543210"
    doctor_name: str
    specialization: str
    day: str                    # e.g. "Saturday, 5th July"
    time: str                   # e.g. "11:00 AM"
    clinic_name: str = CLINIC_NAME
    clinic_address: str = CLINIC_ADDRESS
    clinic_phone: str = CLINIC_PHONE
    telegram_chat_id: Optional[str] = None   # required only if channel="telegram"


# ─────────────────────────────────────────────────────────────
# MESSAGE TEMPLATES (English)
# ─────────────────────────────────────────────────────────────

def build_message(appt: Appointment, message_type: MessageType = "confirmation") -> str:
    """
    Builds the message text for the given appointment and message type.
    Keep messages factual only — no diagnosis, no medicine names, no payment links.
    """

    if message_type == "confirmation":
        return (
            f"Hello {appt.patient_name},\n\n"
            f"Your appointment has been confirmed:\n\n"
            f"Doctor: {appt.doctor_name} ({appt.specialization})\n"
            f"Date/Day: {appt.day}\n"
            f"Time: {appt.time}\n"
            f"Clinic: {appt.clinic_name}\n"
            f"Address: {appt.clinic_address}\n\n"
            f"Please arrive 10 minutes early. For any changes, please call us at "
            f"{appt.clinic_phone}.\n\n"
            f"Thank you,\n{appt.clinic_name}"
        )

    if message_type == "reminder":
        return (
            f"Hello {appt.patient_name}, this is a reminder — "
            f"your appointment with {appt.doctor_name} ({appt.specialization}) is on "
            f"{appt.day} at {appt.time}, at {appt.clinic_name}, {appt.clinic_address}.\n"
            f"For any queries, please contact {appt.clinic_phone}."
        )

    if message_type == "reschedule":
        return (
            f"Hello {appt.patient_name},\n\n"
            f"Your appointment has been rescheduled:\n\n"
            f"Doctor: {appt.doctor_name} ({appt.specialization})\n"
            f"New Date/Day: {appt.day}\n"
            f"New Time: {appt.time}\n\n"
            f"We apologize for the inconvenience. For any queries, please contact "
            f"{appt.clinic_phone}.\n\n"
            f"Thank you,\n{appt.clinic_name}"
        )

    if message_type == "cancellation":
        return (
            f"Hello {appt.patient_name},\n\n"
            f"Your appointment ({appt.doctor_name}, {appt.day} {appt.time}) has been "
            f"cancelled as requested.\n\n"
            f"To book a new appointment, please call us at {appt.clinic_phone}, or "
            f"message us on WhatsApp.\n\n"
            f"Thank you,\n{appt.clinic_name}"
        )

    raise ValueError(f"Unknown message_type: {message_type}")


# ─────────────────────────────────────────────────────────────
# SEND FUNCTIONS (per channel)
# ─────────────────────────────────────────────────────────────

def _send_dry_run(to_phone: str, message: str) -> dict:
    print("─" * 50)
    print(f"[DRY RUN] Message to {to_phone}")
    print("─" * 50)
    print(message)
    print("─" * 50)
    return {"status": "dry_run", "to": to_phone, "message": message}


def _send_telegram(chat_id: str, message: str) -> dict:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "Telegram bot token missing. Set TELEGRAM_BOT_TOKEN environment variable "
            "(get it from @BotFather on Telegram)."
        )
    if not chat_id:
        raise RuntimeError(
            "telegram_chat_id missing on Appointment. Telegram requires the patient's "
            "numeric chat_id, not their phone number — and the patient must have already "
            "messaged your bot at least once (e.g. sent /start) before you can message them."
        )

    import urllib.request
    import urllib.error

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise RuntimeError(f"Telegram API error ({e.code}): {error_body}") from e

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API returned failure: {result}")

    return {"status": "sent", "response": result, "to": chat_id}


def _send_twilio(to_phone: str, message: str, whatsapp: bool = False) -> dict:
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
        raise RuntimeError(
            "Twilio credentials missing. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
            "TWILIO_FROM_NUMBER environment variables."
        )

    from twilio.rest import Client  # lazy import, only needed if this path is used

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    from_number = TWILIO_FROM_NUMBER
    to_number = to_phone

    if whatsapp:
        if not from_number.startswith("whatsapp:"):
            from_number = f"whatsapp:{from_number}"
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"

    msg = client.messages.create(body=message, from_=from_number, to=to_number)
    return {"status": "sent", "sid": msg.sid, "to": to_phone}


def _send_whatsapp_cloud(to_phone: str, message: str) -> dict:
    if not (WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN):
        raise RuntimeError(
            "WhatsApp Cloud API credentials missing. Set WHATSAPP_PHONE_NUMBER_ID, "
            "WHATSAPP_ACCESS_TOKEN environment variables."
        )

    import urllib.request

    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": message},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return {"status": "sent", "response": result, "to": to_phone}


# ─────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────

def send_appointment_message(
    appt: Appointment,
    message_type: MessageType = "confirmation",
    channel: Optional[str] = None,
) -> dict:
    """
    Builds and sends an appointment message to the patient.

    channel: "telegram" | "twilio_sms" | "twilio_whatsapp" | "whatsapp_cloud" | "dry_run"
             Defaults to DEFAULT_CHANNEL (env var MESSENGER_CHANNEL, or "dry_run").

    Returns a dict with the send result/status.
    """
    channel = channel or DEFAULT_CHANNEL
    message = build_message(appt, message_type)

    if channel == "telegram":
        result = _send_telegram(appt.telegram_chat_id, message)
    elif channel == "twilio_sms":
        result = _send_twilio(appt.patient_phone, message, whatsapp=False)
    elif channel == "twilio_whatsapp":
        result = _send_twilio(appt.patient_phone, message, whatsapp=True)
    elif channel == "whatsapp_cloud":
        result = _send_whatsapp_cloud(appt.patient_phone, message)
    else:
        result = _send_dry_run(appt.patient_phone, message)

    result["message_type"] = message_type
    result["timestamp"] = datetime.now().isoformat()
    return result


# ─────────────────────────────────────────────────────────────
# EXAMPLE USAGE
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    appt = Appointment(
        patient_name="Rahul Verma",
        patient_phone="+919876543210",
        doctor_name="Dr. Ramesh Sharma",
        specialization="General Physician",
        day="Saturday, 5th July",
        time="11:00 AM",
        telegram_chat_id=DEFAULT_TELEGRAM_CHAT_ID or "123456789",  # from .env, or fallback
    )

    # Runs in DRY_RUN by default — prints message to console instead of sending.
    #
    # To actually send via Telegram:
    #   1. export TELEGRAM_BOT_TOKEN="your-bot-token-from-BotFather"
    #   2. export MESSENGER_CHANNEL="telegram"
    #   3. run this file again — or call send_appointment_message(appt, channel="telegram")
    #
    # Later, once you have WhatsApp API access, just switch MESSENGER_CHANNEL to
    # "whatsapp_cloud" or "twilio_whatsapp" — no other code changes needed.
    send_appointment_message(appt, message_type="confirmation")