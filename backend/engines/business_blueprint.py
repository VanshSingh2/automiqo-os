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


# Short display name of each department's "head" (the team member you chat with)
HEAD_NAMES: dict[str, str] = {
    "ceo": "CEO",
    "coo": "COO",
    "cmo": "CMO",
    "cro": "CRO",
    "cfo": "CFO",
    "cto": "CTO",
    "csd": "Customer Success Lead",
    "learning": "Learning Lead",
}

# One-line "what they do" for each department head.
DEPT_DESCRIPTIONS: dict[str, str] = {
    "ceo": "Sets strategy, delegates to the team, and makes the big calls.",
    "coo": "Runs day-to-day operations — appointments, staff, and inventory.",
    "cmo": "Brings in customers — leads, campaigns, content, and social.",
    "cro": "Grows revenue — recovers lost sales, upsells, and memberships.",
    "cfo": "Watches the money — reporting, costs, invoicing, and planning.",
    "cto": "Keeps the tech running — automations, deployments, and monitoring.",
    "csd": "Keeps customers happy — reviews, loyalty, complaints, and retention.",
    "learning": "Makes the whole team smarter over time by learning from results.",
}

# One-line "what they do" for each manager, keyed by "dept.manager".
MANAGER_DESCRIPTIONS: dict[str, str] = {
    # COO
    "coo.appointments": "Books, confirms, and sends reminders for appointments.",
    "coo.staff": "Manages staff schedules and coverage.",
    "coo.inventory": "Tracks stock levels and flags reorders for your approval.",
    "coo.procurement": "Handles supplier orders and purchasing.",
    "coo.compliance": "Keeps operations within regulations.",
    "coo.crm": "Keeps customer records clean and up to date.",
    # CMO
    "cmo.lead": "Finds and scores new leads.",
    "cmo.campaign": "Runs SMS, email, and WhatsApp campaigns.",
    "cmo.content": "Creates social posts and marketing content.",
    "cmo.customer_insights": "Analyzes customer behavior and segments.",
    "cmo.experiment": "Runs A/B tests to improve results.",
    # CRO
    "cro.revenue_recovery": "Recovers missed calls and failed payments.",
    "cro.upsell": "Spots and sends upsell offers.",
    "cro.membership": "Manages memberships and renewals.",
    "cro.pricing": "Optimizes pricing and offers.",
    "cro.goal": "Tracks revenue goals and progress.",
    # CFO
    "cfo.analytics": "Reports on revenue, costs, and KPIs.",
    "cfo.business_planner": "Plans budgets and forecasts.",
    "cfo.risk": "Watches for financial risk.",
    # CTO
    "cto.devops": "Deploys, backs up, and monitors infrastructure.",
    "cto.documentation": "Maintains docs and SOPs.",
    "cto.engineering": "Builds and fixes platform features.",
    "cto.performance": "Keeps the system fast and healthy.",
    "cto.qa": "Tests workflows and reliability.",
    "cto.security": "Guards data and access.",
    # CSD
    "csd.customer_success": "Handles complaints and keeps customers happy.",
    "csd.loyalty": "Runs loyalty and rewards programs.",
    "csd.reputation": "Monitors and responds to reviews.",
    # Learning
    "learning.reflection": "Reviews what worked and what didn't.",
    "learning.knowledge": "Curates the business knowledge base.",
    "learning.innovation": "Suggests new ideas and improvements.",
    "learning.prompt_improvement": "Tunes how the AI team thinks and responds.",
}


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


def member_display(agent_key: str) -> str:
    """Resolve a roster key ('ceo', 'coo', 'coo.inventory') to a display name."""
    if agent_key == "ceo":
        return HEAD_NAMES["ceo"]
    parts = agent_key.split(".", 1)
    dept = parts[0]
    if len(parts) == 1:
        return HEAD_NAMES.get(dept, dept.upper())
    manager = parts[1]
    return DEPARTMENTS.get(dept, {}).get("managers", {}).get(manager, manager.replace("_", " ").title())


def team_roster(config: Optional[dict]) -> dict:
    """
    Full team roster for the dashboard: every member (CEO + dept heads + managers)
    with a name, role, short description, enabled state, and chat/toggle ability.
    """
    r = resolve_modules(config)
    members: list[dict] = []

    # CEO — always present, always on, can't be toggled off.
    members.append({
        "key": "ceo",
        "name": HEAD_NAMES["ceo"],
        "role": "executive",
        "dept": "ceo",
        "dept_label": "Executive",
        "description": DEPT_DESCRIPTIONS["ceo"],
        "enabled": True,
        "can_chat": True,
        "can_toggle": False,
    })

    for dept, meta in DEPARTMENTS.items():
        if dept == "ceo":
            continue
        rd = r.get(dept, {})
        dept_on = rd.get("enabled", False)
        # Department head
        members.append({
            "key": dept,
            "name": HEAD_NAMES.get(dept, dept.upper()),
            "role": "department",
            "dept": dept,
            "dept_label": meta["label"],
            "description": DEPT_DESCRIPTIONS.get(dept, ""),
            "enabled": dept_on,
            "can_chat": True,
            "can_toggle": True,
        })
        # Managers under the department
        for mk, ml in meta["managers"].items():
            members.append({
                "key": f"{dept}.{mk}",
                "name": ml,
                "role": "manager",
                "dept": dept,
                "dept_label": meta["label"],
                "description": MANAGER_DESCRIPTIONS.get(f"{dept}.{mk}", ""),
                "enabled": bool(rd.get("managers", {}).get(mk, False)),
                "can_chat": True,
                "can_toggle": True,
            })

    active = sum(1 for m in members if m["enabled"])
    return {
        "total": len(members),
        "active": active,
        "profile": profile_for_industry((config or {}).get("industry")),
        "members": members,
    }
