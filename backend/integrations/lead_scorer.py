"""
Lead Scorer — 0-100 fit score for local service businesses.
Higher score = better prospect for AI automation pitch.
"""
from typing import Optional


def score_lead(lead: dict, target_industry: str = "med spa") -> tuple[int, list[str]]:
    """
    Score a lead 0-100. Returns (score, reasons[]).

    Logic: high score = high pain (no booking system, few reviews, no website)
           + high reachability (has phone, has email)
           + industry match
    """
    score = 0
    reasons = []

    # ── Opportunity signals (pain = your value) ──────────────
    if not lead.get("has_booking_system"):
        score += 35
        reasons.append("no booking system")

    if not lead.get("has_website") and not lead.get("website"):
        score += 20
        reasons.append("no website")

    reviews = lead.get("review_count") or 0
    if reviews == 0:
        score += 15
        reasons.append("no reviews")
    elif reviews < 20:
        score += 10
        reasons.append(f"only {reviews} reviews")
    elif reviews < 50:
        score += 5

    rating = lead.get("google_rating") or 0
    if 3.0 <= rating < 4.0:
        score += 8
        reasons.append("low rating opportunity")
    elif rating < 3.0 and rating > 0:
        score += 5

    # ── Reachability ─────────────────────────────────────────
    if lead.get("email"):
        score += 10
        reasons.append("has email")

    if lead.get("phone") or lead.get("phone_from_web"):
        score += 8
        reasons.append("has phone")

    if lead.get("instagram"):
        score += 4
        reasons.append("active on Instagram")

    # ── Industry fit ─────────────────────────────────────────
    name = (lead.get("company_name") or "").lower()
    category = (lead.get("category") or "").lower()
    services = [s.lower() for s in (lead.get("services_found") or [])]
    target = target_industry.lower()

    industry_keywords = {
        "med spa": ["med spa", "medspa", "botox", "filler", "laser", "aesthetic", "skin care", "iv therapy"],
        "salon": ["salon", "hair", "nail", "beauty", "barber", "blowout", "color"],
        "gym": ["gym", "fitness", "crossfit", "yoga", "pilates", "training", "spin"],
        "dental": ["dental", "dentist", "orthodont", "smile"],
        "spa": ["spa", "massage", "facial", "wellness", "retreat"],
    }
    keywords = industry_keywords.get(target, [target])
    if any(k in name or k in category or any(k in s for s in services) for k in keywords):
        score += 10
        reasons.append("industry match")

    # ── Penalty: already well-served ─────────────────────────
    if lead.get("booking_platform"):
        score -= 10
        reasons.append(f"uses {lead['booking_platform']} (harder to displace)")

    if reviews > 200 and rating >= 4.5:
        score -= 5
        reasons.append("established — less urgent need")

    score = max(0, min(100, score))
    return score, reasons


def score_and_prioritize(leads: list[dict], target_industry: str = "med spa") -> list[dict]:
    """Score all leads and sort by score descending."""
    for lead in leads:
        s, reasons = score_lead(lead, target_industry)
        lead["score"] = s
        lead["score_reasons"] = ", ".join(reasons)

    leads.sort(key=lambda x: x.get("score", 0), reverse=True)
    return leads
