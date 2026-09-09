"""
call_insights.py — MongoDB-backed storage for per-call LLM insights.

Public API (unchanged from SQLite version):
  upsert_insight(data: dict) -> None
  get_insight(lead_id: str) -> dict | None
  get_insights_by_campaign(campaign_id: str) -> list[dict]
  get_insights_by_category(category: str, campaign_id: str = '') -> list[dict]
  get_dashboard_summary(campaign_id: str = '') -> dict

All documents are scoped by client_id for multi-tenant isolation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from pymongo import DESCENDING

from db import get_db
from config import CLIENT_ID

logger = logging.getLogger(__name__)


def _col():
    return get_db().call_insights


def upsert_insight(data: dict) -> None:
    """Insert or update a call insight. Merges nested extracted_data fields."""
    extracted = data.get("extracted_data", {})
    sentiment = data.get("sentiment", {})
    intent = data.get("buying_intent", {})

    doc = {
        "client_id":               CLIENT_ID,
        "campaign_id":             data.get("campaign_id", ""),
        "lead_score":              data.get("lead_score", 0),
        "lead_category":           data.get("lead_category", ""),
        "provider":                data.get("provider", ""),
        # Sentiment
        "sentiment": {
            "overall":   sentiment.get("overall", ""),
            "score":     sentiment.get("score", 0.0),
            "reasoning": sentiment.get("reasoning", ""),
        },
        # Buying intent
        "buying_intent": {
            "level":      intent.get("level", ""),
            "timeline":   intent.get("timeline", ""),
            "indicators": intent.get("indicators", []),
        },
        "interest_level":      data.get("interest_level", 0),
        "engagement_score":    data.get("engagement_score", 0),
        "key_topics":          data.get("key_topics", []),
        "objections":          data.get("objections", []),
        "follow_up_required":  data.get("follow_up_required", False),
        "conversation_summary": data.get("conversation_summary", ""),
        "next_action":         data.get("next_action", ""),
        "detected_language":   data.get("detected_language", ""),
        # Extracted business data
        "extracted": {
            "company_name":     extracted.get("companyName"),
            "industry":         extracted.get("industry"),
            "budget":           extracted.get("budget"),
            "decision_maker":   extracted.get("decisionMaker"),
            "pain_points":      extracted.get("painPoints", []),
            "requirements":     extracted.get("requirements", []),
            "current_solution": extracted.get("currentSolution"),
        },
        "updated_at": datetime.now(timezone.utc),
    }

    _col().update_one(
        {"lead_id": data["lead_id"]},
        {
            "$set": doc,
            "$setOnInsert": {
                "lead_id":    data["lead_id"],
                "created_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
    )
    logger.debug("Upserted insight for lead %s (score=%s, category=%s)",
                 data["lead_id"], doc["lead_score"], doc["lead_category"])


def get_insight(lead_id: str) -> Optional[dict]:
    doc = _col().find_one({"lead_id": lead_id}, {"_id": 0})
    return doc


def get_insights_by_campaign(campaign_id: str) -> list[dict]:
    query = {"client_id": CLIENT_ID, "campaign_id": campaign_id}
    return list(_col().find(query, {"_id": 0}).sort("lead_score", DESCENDING))


def get_insights_by_category(category: str, campaign_id: str = "") -> list[dict]:
    query: dict = {"client_id": CLIENT_ID, "lead_category": category}
    if campaign_id:
        query["campaign_id"] = campaign_id
    return list(_col().find(query, {"_id": 0}).sort("lead_score", DESCENDING))


def get_dashboard_summary(campaign_id: str = "") -> dict:
    match: dict = {"client_id": CLIENT_ID}
    if campaign_id:
        match["campaign_id"] = campaign_id

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "total_calls":        {"$sum": 1},
            "avg_score":          {"$avg": "$lead_score"},
            "hot_leads":          {"$sum": {"$cond": [{"$eq": ["$lead_category", "Hot"]}, 1, 0]}},
            "warm_leads":         {"$sum": {"$cond": [{"$eq": ["$lead_category", "Warm"]}, 1, 0]}},
            "cold_leads":         {"$sum": {"$cond": [{"$eq": ["$lead_category", "Cold"]}, 1, 0]}},
            "not_interested":     {"$sum": {"$cond": [{"$eq": ["$lead_category", "Not_Interested"]}, 1, 0]}},
            "follow_ups_required":{"$sum": {"$cond": ["$follow_up_required", 1, 0]}},
            "high_intent":        {"$sum": {"$cond": [{"$eq": ["$buying_intent.level", "high"]}, 1, 0]}},
            "positive_sentiment": {"$sum": {"$cond": [{"$eq": ["$sentiment.overall", "positive"]}, 1, 0]}},
        }},
    ]
    result = list(_col().aggregate(pipeline))
    summary = result[0] if result else {}
    summary.pop("_id", None)
    if summary.get("avg_score") is not None:
        summary["avg_score"] = round(summary["avg_score"], 1)

    # Top topics across all matched docs
    topic_pipeline = [
        {"$match": match},
        {"$unwind": "$key_topics"},
        {"$group": {"_id": "$key_topics", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    topics = list(_col().aggregate(topic_pipeline))
    top_topics = [{"topic": t["_id"], "count": t["count"]} for t in topics]

    return {"summary": summary, "top_topics": top_topics}
