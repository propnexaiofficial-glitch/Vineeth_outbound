# # import os
# # import re
# # import logging
# # from datetime import datetime, timezone
# # from typing import Optional

# # from pymongo import MongoClient
# # from pymongo.errors import PyMongoError

# # logger = logging.getLogger(__name__)

# # _MONGO_URI = os.environ.get("MONGODB_URI")
# # _DB_NAME = os.environ.get("MONGODB_DB_NAME", "voice_agent_db")

# # _client: Optional[MongoClient] = None
# # _calls_collection = None


# # def _get_collection():
# #     """Lazy connection — pehli baar call hone par hi connect karta hai."""
# #     global _client, _calls_collection
# #     if _calls_collection is not None:
# #         return _calls_collection

# #     if not _MONGO_URI:
# #         raise RuntimeError(
# #             "MONGODB_URI environment variable set nahi hai. "
# #             "Render -> Environment tab me MONGODB_URI add karo."
# #         )

# #     _client = MongoClient(_MONGO_URI)
# #     db = _client[_DB_NAME]
# #     _calls_collection = db["calls"]
# #     logger.info(f"Connected to MongoDB — db={_DB_NAME!r}, collection='calls'")
# #     return _calls_collection


# # _SPEAKER_LINE_RE = re.compile(r"^\s*(caller|customer|agent|user|assistant)\s*:\s*(.*)$", re.IGNORECASE)

# # _SPEAKER_NORMALIZE = {
# #     "caller": "caller",
# #     "customer": "caller",
# #     "user": "caller",
# #     "agent": "agent",
# #     "assistant": "agent",
# # }


# # def _parse_transcript_string(raw: str) -> list[dict]:
# #     """FALLBACK ONLY — plain transcript string ko best-effort turn-wise todta hai."""
# #     turns: list[dict] = []
# #     if not raw:
# #         return turns

# #     current_speaker = None
# #     current_lines: list[str] = []

# #     def flush():
# #         if current_speaker and current_lines:
# #             text = " ".join(current_lines).strip()
# #             if text:
# #                 turns.append({"speaker": current_speaker, "text": text, "timestamp": None})

# #     for line in raw.splitlines():
# #         match = _SPEAKER_LINE_RE.match(line)
# #         if match:
# #             flush()
# #             current_speaker = _SPEAKER_NORMALIZE.get(match.group(1).lower(), match.group(1).lower())
# #             current_lines = [match.group(2)]
# #         else:
# #             if line.strip():
# #                 current_lines.append(line.strip())

# #     flush()
# #     return turns


# # def _normalize_transcript(transcript) -> tuple[list[dict], str]:
# #     """
# #     Returns (structured_turns, raw_text).
# #     Primary path: transcript already a list of dicts (from structured_transcript()).
# #     Fallback path: transcript is a plain string (from full_transcript()).
# #     """
# #     if isinstance(transcript, list):
# #         structured = []
# #         raw_parts = []
# #         for item in transcript:
# #             speaker = item.get("speaker") or item.get("role") or "unknown"
# #             text = item.get("text") or item.get("content") or ""
# #             ts = item.get("timestamp")
# #             structured.append({
# #                 "speaker": _SPEAKER_NORMALIZE.get(str(speaker).lower(), str(speaker).lower()),
# #                 "text": text,
# #                 "timestamp": ts,
# #             })
# #             raw_parts.append(f"{speaker}: {text}")
# #         return structured, "\n".join(raw_parts)

# #     raw_text = transcript or ""
# #     structured = _parse_transcript_string(raw_text)
# #     return structured, raw_text


# # # ──────────────────────────────────────────────────────────────────────────
# # # Public API
# # # ──────────────────────────────────────────────────────────────────────────

# # def save_call_record(
# #     call_id: str,
# #     caller_number: str,
# #     channel_id: str,
# #     caller_context: dict,
# #     enquiry_id: Optional[int],
# #     transcript,
# #     collected_info,
# #     recording_reference: Optional[str],
# #     call_start_time: Optional[datetime],
# #     transfer_requested: bool,
# #     transfer_reason: str,
# #     prompt_type: str,
# #     is_outbound: bool,
# # ):
# #     """Har completed call ke liye ek document `calls` collection me insert karta hai."""
# #     try:
# #         collection = _get_collection()

# #         structured_transcript, raw_transcript = _normalize_transcript(transcript)

# #         collected_info_dict = {}
# #         if collected_info is not None:
# #             collected_info_dict = {
# #                 k: v for k, v in vars(collected_info).items()
# #                 if not k.startswith("_")
# #             }

# #         now = datetime.now(timezone.utc)

# #         doc = {
# #             "call_id": call_id,
# #             "caller_number": caller_number,
# #             "channel_id": channel_id,
# #             "prompt_type": prompt_type,
# #             "is_outbound": is_outbound,
# #             "caller_status": (caller_context or {}).get("caller_status"),
# #             "caller_context": caller_context or {},
# #             "enquiry_id": enquiry_id,

# #             # Transcript — dono forms save karte hain:
# #             "transcript": structured_transcript,  
# #             "transcript_raw": raw_transcript,     

# #             "collected_info": collected_info_dict,
# #             "recording_reference": recording_reference,
# #             "transfer_requested": transfer_requested,
# #             "transfer_reason": transfer_reason,
# #             "call_start_time": call_start_time,
# #             "call_end_time": now,
# #             "duration_seconds": (
# #                 (now - call_start_time).total_seconds() if call_start_time else None
# #             ),
# #             "created_at": now,
# #         }

# #         result = collection.insert_one(doc)
# #         logger.info(f"[{call_id}] Call record saved to MongoDB, _id={result.inserted_id}")
# #         return result.inserted_id

# #     except PyMongoError as e:
# #         logger.error(f"[{call_id}] MongoDB error while saving call record: {e}")
# #         return None
# #     except Exception as e:
# #         logger.error(f"[{call_id}] Failed to save call record: {e}")
# #         return None
# import os
# import re
# import logging
# from datetime import datetime, timezone
# from typing import Optional

# from pymongo import MongoClient
# from pymongo.errors import PyMongoError

# logger = logging.getLogger(__name__)

# _MONGO_URI = os.environ.get("MONGODB_URI")
# _DB_NAME = os.environ.get("MONGODB_DB_NAME", "voice_agent_db")

# _client: Optional[MongoClient] = None
# _calls_collection = None


# def _get_collection():
#     """Lazy connection — pehli baar call hone par hi connect karta hai."""
#     global _client, _calls_collection
#     if _calls_collection is not None:
#         return _calls_collection

#     if not _MONGO_URI:
#         raise RuntimeError(
#             "MONGODB_URI environment variable set nahi hai. "
#             "Render -> Environment tab me MONGODB_URI add karo."
#         )

#     _client = MongoClient(_MONGO_URI)
#     db = _client[_DB_NAME]
#     _calls_collection = db["calls"]
#     logger.info(f"Connected to MongoDB — db={_DB_NAME!r}, collection='calls'")

#     # ── FIX: stale 'conversation_id' unique index ───────────────────────
#     # This collection has a leftover unique index on `conversation_id`
#     # from an earlier schema. The current code never wrote that field,
#     # so every inserted document had conversation_id missing -> Mongo
#     # treats a missing field as null for indexing purposes -> the 2nd,
#     # 3rd, ... call of the day all collided on the same null value and
#     # got rejected with E11000 duplicate key error, silently dropping
#     # the call record.
#     #
#     # Fix applied here: we now always write `conversation_id` (set equal
#     # to call_id, which is already unique per call — see save_call_record
#     # below), so every document gets a real, distinct value and never
#     # collides on null again. This makes the existing unique index safe
#     # to keep as-is; no index changes needed on the MongoDB side.
#     try:
#         existing_indexes = _calls_collection.index_information()
#         if "conversation_id_1" in existing_indexes:
#             logger.info(
#                 "'calls' collection has a unique index on conversation_id — "
#                 "save_call_record() now populates that field on every "
#                 "insert (set to call_id) to avoid null-collisions."
#             )
#     except PyMongoError as e:
#         logger.warning(f"Could not inspect indexes on 'calls' collection: {e}")

#     return _calls_collection


# _SPEAKER_LINE_RE = re.compile(r"^\s*(caller|customer|agent|user|assistant)\s*:\s*(.*)$", re.IGNORECASE)

# _SPEAKER_NORMALIZE = {
#     "caller": "caller",
#     "customer": "caller",
#     "user": "caller",
#     "agent": "agent",
#     "assistant": "agent",
# }


# def _parse_transcript_string(raw: str) -> list[dict]:
#     """FALLBACK ONLY — plain transcript string ko best-effort turn-wise todta hai."""
#     turns: list[dict] = []
#     if not raw:
#         return turns

#     current_speaker = None
#     current_lines: list[str] = []

#     def flush():
#         if current_speaker and current_lines:
#             text = " ".join(current_lines).strip()
#             if text:
#                 turns.append({"speaker": current_speaker, "text": text, "timestamp": None})

#     for line in raw.splitlines():
#         match = _SPEAKER_LINE_RE.match(line)
#         if match:
#             flush()
#             current_speaker = _SPEAKER_NORMALIZE.get(match.group(1).lower(), match.group(1).lower())
#             current_lines = [match.group(2)]
#         else:
#             if line.strip():
#                 current_lines.append(line.strip())

#     flush()
#     return turns


# def _normalize_transcript(transcript) -> tuple[list[dict], str]:
#     """
#     Returns (structured_turns, raw_text).
#     Primary path: transcript already a list of dicts (from structured_transcript()).
#     Fallback path: transcript is a plain string (from full_transcript()).
#     """
#     if isinstance(transcript, list):
#         structured = []
#         raw_parts = []
#         for item in transcript:
#             speaker = item.get("speaker") or item.get("role") or "unknown"
#             text = item.get("text") or item.get("content") or ""
#             ts = item.get("timestamp")
#             structured.append({
#                 "speaker": _SPEAKER_NORMALIZE.get(str(speaker).lower(), str(speaker).lower()),
#                 "text": text,
#                 "timestamp": ts,
#             })
#             raw_parts.append(f"{speaker}: {text}")
#         return structured, "\n".join(raw_parts)

#     raw_text = transcript or ""
#     structured = _parse_transcript_string(raw_text)
#     return structured, raw_text


# # ──────────────────────────────────────────────────────────────────────────
# # Public API
# # ──────────────────────────────────────────────────────────────────────────

# def save_call_record(
#     call_id: str,
#     caller_number: str,
#     channel_id: str,
#     caller_context: dict,
#     enquiry_id: Optional[int],
#     transcript,
#     collected_info,
#     recording_reference: Optional[str],
#     call_start_time: Optional[datetime],
#     transfer_requested: bool,
#     transfer_reason: str,
#     prompt_type: str,
#     is_outbound: bool,
#     conversation_id: Optional[str] = None,
# ):
#     """Har completed call ke liye ek document `calls` collection me insert karta hai.

#     FIX: `conversation_id` ab hamesha likha jaata hai (default = call_id,
#     jo already unique per-call hai). Pehle ye field kabhi likha hi nahi
#     jaata tha jabki collection par isi field par ek unique index laga
#     hua tha — har naye call record ka `conversation_id` Mongo ke liye
#     'missing' (== null) ban jaata tha, aur doosri call se hi
#     E11000 duplicate key error aakar poora record save hone se rok deta
#     tha. Ab har record ko apna distinct conversation_id milta hai, to
#     ye collision dobara nahi hoga.
#     """
#     try:
#         collection = _get_collection()

#         structured_transcript, raw_transcript = _normalize_transcript(transcript)

#         collected_info_dict = {}
#         if collected_info is not None:
#             collected_info_dict = {
#                 k: v for k, v in vars(collected_info).items()
#                 if not k.startswith("_")
#             }

#         now = datetime.now(timezone.utc)

#         doc = {
#             "call_id": call_id,
#             # FIX: was missing entirely — collided with the unique index
#             # on every call after the first. Defaults to call_id, which
#             # is already guaranteed unique per call by the caller.
#             "conversation_id": conversation_id or call_id,
#             "caller_number": caller_number,
#             "channel_id": channel_id,
#             "prompt_type": prompt_type,
#             "is_outbound": is_outbound,
#             "caller_status": (caller_context or {}).get("caller_status"),
#             "caller_context": caller_context or {},
#             "enquiry_id": enquiry_id,

#             # Transcript — dono forms save karte hain:
#             "transcript": structured_transcript,
#             "transcript_raw": raw_transcript,

#             "collected_info": collected_info_dict,
#             "recording_reference": recording_reference,
#             "transfer_requested": transfer_requested,
#             "transfer_reason": transfer_reason,
#             "call_start_time": call_start_time,
#             "call_end_time": now,
#             "duration_seconds": (
#                 (now - call_start_time).total_seconds() if call_start_time else None
#             ),
#             "created_at": now,
#         }

#         result = collection.insert_one(doc)
#         logger.info(f"[{call_id}] Call record saved to MongoDB, _id={result.inserted_id}")
#         return result.inserted_id

#     except PyMongoError as e:
#         logger.error(f"[{call_id}] MongoDB error while saving call record: {e}")
#         return None
#     except Exception as e:
#         logger.error(f"[{call_id}] Failed to save call record: {e}")
#         return None
import os
import re
import logging
from datetime import datetime, timezone
from typing import Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

_MONGO_URI = os.environ.get("MONGODB_URI")
_DB_NAME = os.environ.get("MONGODB_DB_NAME", "voice_agent_db")

_client: Optional[MongoClient] = None
_calls_collection = None


def _get_collection():
    """Lazy connection — pehli baar call hone par hi connect karta hai."""
    global _client, _calls_collection
    if _calls_collection is not None:
        return _calls_collection

    if not _MONGO_URI:
        raise RuntimeError(
            "MONGODB_URI environment variable set nahi hai. "
            "Render -> Environment tab me MONGODB_URI add karo."
        )

    _client = MongoClient(_MONGO_URI)
    db = _client[_DB_NAME]
    _calls_collection = db["calls"]
    logger.info(f"Connected to MongoDB — db={_DB_NAME!r}, collection='calls'")

    try:
        existing_indexes = _calls_collection.index_information()
        if "conversation_id_1" in existing_indexes:
            logger.info(
                "'calls' collection has a unique index on conversation_id — "
                "save_call_record() now populates that field on every "
                "insert (set to call_id) to avoid null-collisions."
            )
    except PyMongoError as e:
        logger.warning(f"Could not inspect indexes on 'calls' collection: {e}")

    return _calls_collection


_SPEAKER_LINE_RE = re.compile(r"^\s*(caller|customer|agent|user|assistant)\s*:\s*(.*)$", re.IGNORECASE)

_SPEAKER_NORMALIZE = {
    "caller": "caller",
    "customer": "caller",
    "user": "caller",
    "agent": "agent",
    "assistant": "agent",
}


def _parse_transcript_string(raw: str) -> list[dict]:
    """FALLBACK ONLY — plain transcript string ko best-effort turn-wise todta hai."""
    turns: list[dict] = []
    if not raw:
        return turns

    current_speaker = None
    current_lines: list[str] = []

    def flush():
        if current_speaker and current_lines:
            text = " ".join(current_lines).strip()
            if text:
                turns.append({"speaker": current_speaker, "text": text, "timestamp": None})

    for line in raw.splitlines():
        match = _SPEAKER_LINE_RE.match(line)
        if match:
            flush()
            current_speaker = _SPEAKER_NORMALIZE.get(match.group(1).lower(), match.group(1).lower())
            current_lines = [match.group(2)]
        else:
            if line.strip():
                current_lines.append(line.strip())

    flush()
    return turns


def _normalize_transcript(transcript) -> tuple[list[dict], str]:
    if isinstance(transcript, list):
        structured = []
        raw_parts = []
        for item in transcript:
            speaker = item.get("speaker") or item.get("role") or "unknown"
            text = item.get("text") or item.get("content") or ""
            ts = item.get("timestamp")
            structured.append({
                "speaker": _SPEAKER_NORMALIZE.get(str(speaker).lower(), str(speaker).lower()),
                "text": text,
                "timestamp": ts,
            })
            raw_parts.append(f"{speaker}: {text}")
        return structured, "\n".join(raw_parts)

    raw_text = transcript or ""
    structured = _parse_transcript_string(raw_text)
    return structured, raw_text


# ──────────────────────────────────────────────────────────────────────────
# Public API — WRITE
# ──────────────────────────────────────────────────────────────────────────

def save_call_record(
    call_id: str,
    caller_number: str,
    channel_id: str,
    caller_context: dict,
    enquiry_id: Optional[int],
    transcript,
    collected_info,
    recording_reference: Optional[str],
    call_start_time: Optional[datetime],
    transfer_requested: bool,
    transfer_reason: str,
    prompt_type: str,
    is_outbound: bool,
    conversation_id: Optional[str] = None,
    # ── NEW fields for API 3 (Call Completion Event) ──────────────────
    call_status: Optional[str] = None,
    language: Optional[str] = None,
    ai_summary: Optional[str] = None,
    primary_outcomes: Optional[list[str]] = None,
    secondary_outcomes: Optional[list[str]] = None,
    tertiary_outcomes: Optional[dict] = None,
):
    """Har completed call ke liye ek document `calls` collection me insert karta hai.

    NEW (for API 3): call_status, language, ai_summary aur teeno outcome
    lists/dicts ab is document ke saath hi store hote hain, taaki
    api3_router.get_call_record() ko alag se kuch compute na karna pade —
    seedha yahi document return ho jaaye.
    """
    try:
        collection = _get_collection()

        structured_transcript, raw_transcript = _normalize_transcript(transcript)

        collected_info_dict = {}
        if collected_info is not None:
            collected_info_dict = {
                k: v for k, v in vars(collected_info).items()
                if not k.startswith("_")
            }

        now = datetime.now(timezone.utc)

        doc = {
            "call_id": call_id,
            "conversation_id": conversation_id or call_id,
            "caller_number": caller_number,
            "channel_id": channel_id,
            "prompt_type": prompt_type,
            "is_outbound": is_outbound,
            "caller_status": (caller_context or {}).get("caller_status"),
            "caller_context": caller_context or {},
            "enquiry_id": enquiry_id,

            "transcript": structured_transcript,
            "transcript_raw": raw_transcript,

            "collected_info": collected_info_dict,
            "recording_reference": recording_reference,
            "transfer_requested": transfer_requested,
            "transfer_reason": transfer_reason,
            "call_start_time": call_start_time,
            "call_end_time": now,
            "duration_seconds": (
                (now - call_start_time).total_seconds() if call_start_time else None
            ),
            "created_at": now,

            # ── NEW — API 3 fields ──────────────────────────────────
            "call_status": call_status,
            "language": language,
            "ai_summary": ai_summary,
            "primary_outcomes": primary_outcomes or [],
            "secondary_outcomes": secondary_outcomes or [],
            "tertiary_outcomes": tertiary_outcomes or {},
            # SchoolKnot ko event bheja ja chuka hai ya nahi — taaki
            # webhook/retry logic isko track kar sake.
            "schoolknot_notified": False,
            "schoolknot_notified_at": None,
        }

        result = collection.insert_one(doc)
        logger.info(f"[{call_id}] Call record saved to MongoDB, _id={result.inserted_id}")
        return result.inserted_id

    except PyMongoError as e:
        logger.error(f"[{call_id}] MongoDB error while saving call record: {e}")
        return None
    except Exception as e:
        logger.error(f"[{call_id}] Failed to save call record: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────
# Public API — READ (new — needed for API 3, SchoolKnot calls this
# indirectly through api3_router.py)
# ──────────────────────────────────────────────────────────────────────────

def get_call_record(call_id: str) -> Optional[dict]:
    """Fetch a single call document by call_id. Returns None if not found
    or on any DB error (caller/router turns that into a 404)."""
    try:
        collection = _get_collection()
        doc = collection.find_one({"call_id": call_id})
        if doc is None:
            return None
        doc["_id"] = str(doc["_id"])  # ObjectId isn't JSON-serializable
        return doc
    except PyMongoError as e:
        logger.error(f"[{call_id}] MongoDB error while fetching call record: {e}")
        return None
    except Exception as e:
        logger.error(f"[{call_id}] Failed to fetch call record: {e}")
        return None


def mark_schoolknot_notified(call_id: str) -> bool:
    """Marks a call as successfully delivered to SchoolKnot (webhook
    notify step). Used so retries don't double-notify."""
    try:
        collection = _get_collection()
        result = collection.update_one(
            {"call_id": call_id},
            {"$set": {
                "schoolknot_notified": True,
                "schoolknot_notified_at": datetime.now(timezone.utc),
            }},
        )
        return result.modified_count > 0
    except PyMongoError as e:
        logger.error(f"[{call_id}] MongoDB error while marking notified: {e}")
        return False