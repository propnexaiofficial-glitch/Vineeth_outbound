"""
Lead scoring module.

Provides score_lead() and category_from_score() used by the classifier
to rank and categorise call outcomes.
"""


def score_lead(insights: dict, duration: float, status: str) -> int:
    """
    Compute a 0–100 lead score from call insights, duration, and status.

    Scoring breakdown:
      +20  call completed
      +0–15  duration (1 pt per 20 s, capped at 15)
      +20/+10  sentiment positive/neutral
      +25/+15  buying intent high/medium
      +0–10  interest_level * 2 (capped at 10)
      +10  decision_maker present
      +10  budget present
      +15  follow_up_required
      +0–10  engagement_score (capped at 10)
    """
    score = 0
    if status == "Completed":
        score += 20
    score += min(15, int(duration / 20))          # up to 15 pts for 5-min call
    sentiment = insights.get("sentiment", {}).get("overall", "")
    if sentiment == "positive":
        score += 20
    elif sentiment == "neutral":
        score += 10
    intent = insights.get("buying_intent", {}).get("level", "")
    if intent == "high":
        score += 25
    elif intent == "medium":
        score += 15
    score += min(10, insights.get("interest_level", 0) * 2)
    if insights.get("extracted", {}).get("decision_maker"):
        score += 10
    if insights.get("extracted", {}).get("budget"):
        score += 10
    if insights.get("follow_up_required"):
        score += 15
    score += min(10, insights.get("engagement_score", 0))
    return min(100, score)


def category_from_score(score: int) -> str:
    """
    Map a numeric lead score to a category label.

    80–100 → Hot
    60–79  → Warm
    30–59  → Cold
    0–29   → Not_Interested
    """
    if score >= 80:
        return "Hot"
    if score >= 60:
        return "Warm"
    if score >= 30:
        return "Cold"
    return "Not_Interested"
