"""
db.py — MongoDB connection singleton.

Collections:
  call_insights  — post-call LLM analysis (insights, scoring, sentiment)
  lead_info      — real-time extracted data during the call
"""
from __future__ import annotations

import logging
from functools import lru_cache

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.database import Database

from config import MONGODB_URI

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_db() -> Database:
    """Return the MongoDB database, creating the client once.

    Tries multiple TLS configurations to handle Atlas SSL issues on Windows.
    """
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI is not set in environment variables.")

    import certifi

    tls_attempts = [
        {"tlsCAFile": certifi.where()},
        {"tlsAllowInvalidCertificates": True, "tlsAllowInvalidHostnames": True},
        {},
    ]

    last_exc: Exception | None = None
    for kwargs in tls_attempts:
        try:
            client = MongoClient(
                MONGODB_URI,
                serverSelectionTimeoutMS=8000,
                connectTimeoutMS=8000,
                socketTimeoutMS=20000,
                **kwargs,
            )
            client.admin.command("ping")
            db = client.get_default_database()
            _ensure_indexes(db)
            logger.info("MongoDB connected: %s", db.name)
            return db
        except Exception as exc:
            last_exc = exc
            logger.warning("MongoDB TLS attempt failed (%s): %s", kwargs, exc)

    raise RuntimeError(f"Could not connect to MongoDB: {last_exc}")


def _ensure_indexes(db: Database) -> None:
    ci = db.call_insights
    ci.create_index([("lead_id", ASCENDING)], unique=True)
    ci.create_index([("client_id", ASCENDING), ("campaign_id", ASCENDING)])
    ci.create_index([("client_id", ASCENDING), ("lead_category", ASCENDING)])
    ci.create_index([("client_id", ASCENDING), ("lead_score", DESCENDING)])
    ci.create_index([("created_at", DESCENDING)])

    li = db.lead_info
    li.create_index([("lead_id", ASCENDING)], unique=True)
    li.create_index([("client_id", ASCENDING), ("campaign_id", ASCENDING)])
