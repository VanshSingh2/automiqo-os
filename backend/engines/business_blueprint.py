"""
Business Blueprint — per-business module configuration.

Not every business needs every department or every manager. A med spa needs
inventory + appointments; an AI agency does not. This engine decides, for a
given business, which DEPARTMENTS and which MANAGERS inside them are active.

How it works
------------
1. Each industry maps to a default PROFILE (a starting set of enabled modules).
2. The owner can override any department or manager on/off. Overrides are
   stored on ``businesses.config["module_overrides"]`` and win over the profile.
3. Loops, the scheduler, and the capability registry all consult this engine
   so agents only run the work that is relevant to THIS business.

Override format (stored on businesses.config["module_overrides"]):
    {
      "coo": false,                      # whole department off
      "coo.inventory": false,            # one manager off (dept stays on)
      "cmo.content": true                # force a manager on
    }
"""
from __future__ import annotations
from typing import Optional


# ── The full org: departments and the managers inside each ────────────────
# manager keys match the real manager modules under agents/departments/<dept>/
DEPARTMENTS: dict[str, dict] = {
    "ceo": {
        "label": "CEO",
        "managers": {},  # CEO has no toggleable managers; always on
    },
    "coo": {
        "label": "Operations (COO)",
        "managers": {
            "appointments": "Appointment Manager",
            "staff": "Staff Manager",
            "inventory": "Inventory Manager",
            "procurement": "Procurement Manager",
            "compliance": "Compliance Manager",
            "crm": "CRM Manager",
        },
    },
    "cmo": {
        "label": "Marketing (CMO)",
        "managers": {
            "lead": "Lead Manager",
            "campaign": "Campaign Manager",
            "content": "Content Manager",
            "customer_insights": "Customer Insights Manager",
            "experiment": "Experiment Manager",
        },
    },
    "cro": {
        "label": "Revenue (CRO)",
        "managers": {
            "revenue_recovery": "Revenue Recovery Manager",
            "upsell": "Upsell Manager",
            "membership": "Membership Manager",
            "pricing": "Pricing Manager",
            "goal": "Goal Manager",
        },
    },
    "cfo": {
        "label": "Finance (CFO)",
        "managers": {
            "analytics": "Analytics Manager",
            "business_planner": "Business Planner",
            "risk": "Risk Manager",
        },
    },
    "cto": {
        "label": "Technology (CTO)",
        "managers": {
            "devops": "DevOps Manager",
            "documentation": "Documentation Manager",
            "engineering": "Engineering Manager",
            "performance": "Performance Manager",
            "qa": "QA Manager",
            "security": "Security Manager",
        },
    },
    "csd": {
        "label": "Customer Success (CSD)",
        "managers": {
            "customer_success": "Customer Success Manager",
            "loyalty": "Loyalty Manager",
            "reputation": "Reputation Manager",
        },
    },
    "learning": {
        "label": "Learning & Improvement",
        "managers": {
            "reflection": "Reflection Manager",
            "knowledge": "Knowledge Manager",
            "innovation": "Innovation Manager",
            "prompt_improvement": "Prompt Improvement Manager",
        },
    },
}

# Departments that the autonomous scheduler can fire (CEO runs via standup, not a loop)
SCHEDULABLE_DEPTS = ["coo", "cmo", "cro", "cfo", "cto", "csd", "learning"]


# ── Profiles: which modules are ON by default for a kind of business ───────
# A profile lists departments, and for each, the managers that are enabled.
# "*" means every manager in that department.
def _all(dept: str) -> dict:
    return {m: True for m in DEPARTMENTS[dept]["managers"]}


def _only(dept: str, enabled: list[str]) -> dict:
    return {m: (m in enabled) for m in DEPARTMENTS[dept]["managers"]}


PROFILES: dict[str, dict] = {
    # Physical, appointment-driven local businesses (med spa, gym, salon, dental)
    "appointment_service": {
        "coo": _all("coo"),
        "cmo": _all("cmo"),
        "cro": _all("cro"),
        "cfo": _all("cfo"),
        "cto": _all("cto"),
        "csd": _all("csd"),
        "learning": _all("learning"),
    },
    # Digital / online businesses (AI agency, SaaS, consulting, marketing agency).
    # No physical inventory or procurement; appointments optional (sales calls).
    "digital_service": {
        "coo": _only("coo", ["appointments", "crm", "staff"]),  # no inventory/procurement/compliance
        "cmo": _all("cmo"),
        "cro": _all("cro"),
        "cfo": _all("cfo"),
        "cto": _all("cto"),
        "csd": _all("csd"),
        "learning": _all("learning"),
    },
    # E-commerce / retail: inventory + procurement matter, appointments do not.
    "ecommerce": {
        "coo": _only("coo", ["inventory", "procurement", "crm", "compliance"]),
        "cmo": _all("cmo"),
        "cro": _all("cro"),
        "cfo": _all("cfo"),
        "cto": _all("cto"),
        "csd": _all("csd"),
        "learning": _all("learning"),
    },
}

DEFAULT_PROFILE = "appointment_service"

# Map an industry string to a profile. Matched case-insensitively by substring.
INDUSTRY_PROFILE_MAP: dict[str, str] = {
    # appointment service
    "med spa": "appointment_service",
    "medspa": "appointment_service",
    "med_spa": "appointment_service",
    "spa": "appointment_service",
    "salon": "appointment_service",
    "gym": "appointment_service",
    "fitness": "appointment_service",
    "dental": "appointment_service",
    "dentist": "appointment_service",
    "clinic": "appointment_service",
    "wellness": "appointment_service",
    "barber": "appointment_service",
    "chiropractic": "appointment_service",
    "physio": "appointment_service",
    "aesthetic": "appointment_service",
    # digital service
    "ai": "digital_service",
    "agency": "digital_service",
    "saas": "digital_service",
    "software": "digital_service",
    "consulting": "digital_service",
    "consultant": "digital_service",
    "marketing": "digital_service",
    "digital": "digital_service",
    "automation": "digital_service",
    "tech": "digital_service",
    "startup": "digital_service",
    # ecommerce
    "ecommerce": "ecommerce",
    "e-commerce": "ecommerce",
    "retail": "ecommerce",
    "store": "ecommerce",
    "shop": "ecommerce",
    "boutique": "ecommerce",
}


def profile_for_industry(industry: Optional[str]) -> str:
    """Pick the best-fit profile name for an industry string."""
    if not industry:
        return DEFAULT_PROFILE
    text = industry.strip().lower()
    # exact key first
    if text in INDUSTRY_PROFILE_MAP:
        return INDUSTRY_PROFILE_MAP[text]
    # substring match
    for key, profile in INDUSTRY_PROFILE_MAP.items():
        if key in text:
            return profile
    return DEFAULT_PROFILE


def default_modules_for_industry(industry: Optional[str]) -> dict:
    """Return the default enabled-modules tree for an industry."""
    profile = profile_for_industry(industry)
    base = PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])
    # deep copy so callers can't mutate the template
    return {dept: dict(managers) for dept, managers in base.items()}


# ── Resolution: profile defaults + owner overrides ────────────────────────
def resolve_modules(config: Optional[dict]) -> dict:
    """
    Resolve the effective module tree for a business from its config.

    Returns:
        {
          "coo": {"enabled": True, "managers": {"inventory": True, ...}},
          ...
        }
    """
    config = config or {}
    industry = config.get("industry")
    base = default_modules_for_industry(industry)
    overrides = config.get("module_overrides") or {}

    resolved: dict[str, dict] = {}
    # CEO is always on
    resolved["ceo"] = {"enabled": True, "managers": {}}

    for dept, meta in DEPARTMENTS.items():
        if dept == "ceo":
            continue
        dept_base = base.get(dept)
        dept_enabled = dept_base is not None
        managers_base = dept_base or {}
        # all known managers for the dept, defaulting to base or False
        managers = {m: bool(managers_base.get(m, False)) for m in meta["managers"]}

        # apply dept-level override
        if dept in overrides:
            dept_enabled = bool(overrides[dept])
        # apply manager-level overrides ("dept.manager")
        for okey, oval in overrides.items():
            if "." in okey:
                od, om = okey.split(".", 1)
                if od == dept and om in managers:
                    managers[om] = bool(oval)

        # if a dept is off, none of its managers run
        if not dept_enabled:
            managers = {m: False for m in managers}

        resolved[dept] = {"enabled": dept_enabled, "managers": managers}

    return resolved


def is_dept_enabled(config: Optional[dict], dept: str) -> bool:
    if dept == "ceo":
        return True
    return resolve_modules(config).get(dept, {}).get("enabled", False)


def is_manager_enabled(config: Optional[dict], dept: str, manager: str) -> bool:
    """True only if both the department AND the manager are enabled."""
    r = resolve_modules(config).get(dept, {})
    return bool(r.get("enabled")) and bool(r.get("managers", {}).get(manager, False))


def enabled_depts(config: Optional[dict]) -> list[str]:
    r = resolve_modules(config)
    return [d for d in SCHEDULABLE_DEPTS if r.get(d, {}).get("enabled")]


def summary(config: Optional[dict]) -> dict:
    """Human-friendly summary for the API / dashboard."""
    r = resolve_modules(config)
    out = {
        "profile": profile_for_industry((config or {}).get("industry")),
        "departments": [],
    }
    for dept, meta in DEPARTMENTS.items():
        if dept == "ceo":
            continue
        rd = r.get(dept, {})
        out["departments"].append({
            "key": dept,
            "label": meta["label"],
            "enabled": rd.get("enabled", False),
            "managers": [
                {"key": mk, "label": ml, "enabled": rd.get("managers", {}).get(mk, False)}
                for mk, ml in meta["managers"].items()
            ],
        })
    return out
