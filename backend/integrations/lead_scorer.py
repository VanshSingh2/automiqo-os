"""
Lead Scorer v2 — 0-100 fit score with social signals.
Higher score = business needs Automiqo most.
Backwards-compatible: score_and_prioritize() still works for existing code.
"""
from typing import Optional

BASIC_BOOKING_PLATFORMS = ["calendly", "squarespace", "wix", "square"]
ADVANCED_BOOKING_PLATFORMS = ["mindbody", "vagaro", "fresha", "jane_app", "boulevard", "zenoti"]

INDUSTRY_KEYWORDS = {
    "med spa": ["med spa", "medspa", "botox", "filler", "laser", "aesthetic", "skin care", "iv therapy"],
    "medspa": ["med spa", "medspa", "botox", "filler", "laser", "aesthetic"],
    "salon": ["salon", "hair", "nail", "beauty", "barber", "blowout", "color"],
    "gym": ["gym", "fitness", "crossfit", "yoga", "pilates", "training", "spin"],
    "dental": ["dental", "dentist", "orthodont", "smile"],
    "wellness": ["spa", "massage", "facial", "wellness", "retreat", "chiropractic"],
}


def score_lead_v2(lead: dict) -> dict:
    """
    Score a lead 0-100 with social signals. Returns updated lead dict.
    Replaces score_lead() + score_and_prioritize() for new pipeline.
    """
    score = 0
    reasons = []

    # ── Opportunity signals ────────────────────────────────────
    if not lead.get("has_website") and not lead.get("website"):
        score += 20; reasons.append("no website")

    if not lead.get("has_online_booking") and not lead.get("has_booking_system"):
        score += 25; reasons.append("no online booking")

    if not lead.get("has_chatbot"):
        score += 15; reasons.append("no AI/chatbot")

    review_count = lead.get("review_count", 0) or 0
    if review_count < 50:
        score += 15; reasons.append(f"only {review_count} reviews")

    rating = lead.get("google_rating", 0) or 0
    if 0 < rating < 4.0:
        score += 10; reasons.append(f"{rating}★ rating")

    # ── Reachability ───────────────────────────────────────────
    if lead.get("email") or lead.get("instagram_email"):
        score += 10; reasons.append("has email")

    if lead.get("phone") or lead.get("phone_from_site"):
        score += 5; reasons.append("has phone")

    # ── Booking platform signals ───────────────────────────────
    bp = lead.get("booking_platform", "")
    if bp in BASIC_BOOKING_PLATFORMS:
        score += 15; reasons.append(f"uses {bp} (easy upgrade)")
    elif bp in ADVANCED_BOOKING_PLATFORMS:
        score -= 10; reasons.append(f"uses {bp} (harder sell)")

    # ── Social signals ─────────────────────────────────────────
    if not lead.get("instagram_username") and not lead.get("instagram"):
        score += 10; reasons.append("no Instagram found")
    else:
        insta_followers = lead.get("instagram_followers", 0) or 0
        if insta_followers < 500:
            score += 8; reasons.append(f"only {insta_followers} Instagram followers")
        if lead.get("instagram_email"):
            score += 8; reasons.append("email in Instagram bio")
            if not lead.get("email"):
                lead["email"] = lead["instagram_email"]

    if not lead.get("facebook_page_name"):
        score += 5; reasons.append("no Facebook page")

    if not lead.get("linkedin_company_url"):
        score += 5; reasons.append("no LinkedIn")

    score = min(score, 100)

    return {
        **lead,
        "score": score,
        "score_reason": ", ".join(reasons),
        "score_reasons": ", ".join(reasons),  # backwards-compat
        "tier": "A" if score >= 75 else "B" if score >= 50 else "C",
    }


def score_lead(lead: dict, target_industry: str = "med spa") -> tuple[int, list[str]]:
    """Backwards-compatible scorer. Returns (score, reasons) tuple."""
    result = score_lead_v2({**lead})
    score = result["score"]
    reasons = result["score_reason"].split(", ") if result["score_reason"] else []
    return score, reasons


def score_and_prioritize(leads: list[dict], target_industry: str = "med spa") -> list[dict]:
    """Backwards-compatible: score all leads and sort by score desc."""
    for lead in leads:
        s, reasons = score_lead(lead, target_industry)
        lead["score"] = s
        lead["score_reasons"] = ", ".join(reasons)
    leads.sort(key=lambda x: x.get("score", 0), reverse=True)
    return leads


def segment_leads(leads: list[dict]) -> dict:
    """Segment leads into tiers and groups for targeted outreach."""
    tier_a = [l for l in leads if l.get("tier") == "A"]
    tier_b = [l for l in leads if l.get("tier") == "B"]
    tier_c = [l for l in leads if l.get("tier") == "C"]
    no_booking = [l for l in leads if not l.get("has_online_booking") and not l.get("has_booking_system")]
    no_website = [l for l in leads if not l.get("has_website") and not l.get("website")]
    has_calendly = [l for l in leads if l.get("booking_platform") == "calendly"]
    has_mindbody = [l for l in leads if l.get("booking_platform") == "mindbody"]
    return {
        "total": len(leads),
        "tier_a": {"count": len(tier_a), "leads": tier_a},
        "tier_b": {"count": len(tier_b), "leads": tier_b},
        "tier_c": {"count": len(tier_c), "leads": tier_c},
        "segments": {
            "no_booking_system": {"count": len(no_booking), "leads": no_booking},
            "no_website": {"count": len(no_website), "leads": no_website},
            "using_calendly": {"count": len(has_calendly), "leads": has_calendly},
            "using_mindbody": {"count": len(has_mindbody), "leads": has_mindbody},
        },
        "outreach_priority": sorted(tier_a, key=lambda x: x.get("score", 0), reverse=True)[:20],
    }
