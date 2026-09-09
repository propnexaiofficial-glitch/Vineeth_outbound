"""
Classifier for lead call transcripts.
Uses Gemini-powered insights_analyzer when available, falls back to keywords.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

KEYWORD_MAP = {
    "NOT_INTERESTED": "Cold",
    "DEMO_BOOKED": "Hot",
    "CALLBACK_REQUESTED": "Warm",
    "NOT_NOW": "Warm",
    "INTERESTED": "Hot",
}


def classify_transcript(transcript: str) -> str:
    """Return Hot/Warm/Cold based on keyword presence; default Cold."""
    upper = transcript.upper()
    for keyword, label in KEYWORD_MAP.items():
        if keyword in upper:
            return label
    return "Cold"


def summarise_transcript(transcript: str, max_words: int = 200) -> str:
    """Truncate transcript to at most max_words words."""
    words = transcript.split()
    return " ".join(words[:max_words])


async def classify_and_analyze(
    transcript: str,
    duration: float,
    status: str,
    lead_id: str,
    campaign_id: str = '',
) -> tuple[str, str, dict]:
    """Full LLM-powered analysis. Returns (classification, summary, insights_dict)."""
    try:
        from insights_analyzer import analyze_call
        from call_insights import upsert_insight

        insights = await analyze_call(
            transcript=transcript,
            duration=duration,
            status=status,
            lead_id=lead_id,
        )
        insights['campaign_id'] = campaign_id
        upsert_insight(insights)

        classification = insights.get('lead_category', classify_transcript(transcript))
        summary = insights.get('conversation_summary', summarise_transcript(transcript))
        return classification, summary, insights

    except Exception as e:
        logger.warning(f'LLM analysis failed for {lead_id}: {e} — using keyword fallback')
        return classify_transcript(transcript), summarise_transcript(transcript), {}
