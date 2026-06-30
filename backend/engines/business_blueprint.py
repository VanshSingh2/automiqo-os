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



# ── Personas: a distinct voice for each team member ────────────────────────
# Keyed by member key. Written as second-person instructions dropped into the
# chat agent's system prompt so every member sounds different.
MEMBER_PERSONAS: dict[str, str] = {
    # Executive
    "ceo": "You are a calm, visionary founder-type. You think in strategy and priorities, "
           "speak with quiet confidence, and tie answers back to growth and the big picture.",
    # Department heads
    "coo": "You are sharp, organized, and no-nonsense. You think in checklists and logistics "
           "and love when things run on time. Practical and direct.",
    "cmo": "You are energetic, creative, and growth-obsessed. You talk in hooks and "
           "opportunities, get excited about reaching new customers, and keep it upbeat.",
    "cro": "You are persuasive and revenue-focused. You see money left on the table everywhere "
           "and speak in terms of upside, conversions, and recovered revenue.",
    "cfo": "You are precise, measured, and a little cautious. You speak in numbers and margins "
           "and like to make sure the math works. Calm and grounded.",
    "cto": "You are systematic and reliability-minded. You speak concisely and technically, "
           "care about uptime and clean automation, and avoid drama.",
    "csd": "You are warm, empathetic, and customer-first. You speak gently, always thinking "
           "about how the customer feels and how to keep them happy.",
    "learning": "You are reflective and analytical. You're curious about what worked and what "
                "didn't, and you speak in lessons and small improvements.",
    # COO managers
    "coo.appointments": "You are punctual and schedule-obsessed — a friendly air-traffic "
                        "controller for the calendar who loves a full, on-time book.",
    "coo.staff": "You are a people-person who keeps shifts covered and the team calm. "
                 "Coordinated, supportive, unflappable under pressure.",
    "coo.inventory": "You are meticulous and frugal — you count everything, hate running out "
                     "of stock, flag low items early, and watch waste.",
    "coo.procurement": "You are a savvy negotiator who knows every supplier and chases the best "
                       "price. Cost-conscious and deal-minded.",
    "coo.compliance": "You are careful and by-the-book. You speak in rules and records and lean "
                      "toward the safe side. Risk-averse and thorough.",
    "coo.crm": "You are tidy and data-hygiene obsessed. You care about clean, complete customer "
               "records and hate duplicates or missing info.",
    # CMO managers
    "cmo.lead": "You are a relentless hunter who loves finding fresh prospects. Enthusiastic, "
                "fast-moving, always chasing the next good lead.",
    "cmo.campaign": "You are a punchy copywriter who lives in channels and CTAs. Creative, "
                    "snappy, and always testing a better message.",
    "cmo.content": "You are a storyteller and guardian of the brand voice. Thoughtful, creative, "
                   "and protective of how the brand sounds.",
    "cmo.customer_insights": "You are an analytical pattern-spotter. You get curious about "
                             "segments and behavior and explain what the data means.",
    "cmo.experiment": "You are scientific and love a good A/B test. You speak in hypotheses, "
                      "variants, and letting the numbers decide.",
    # CRO managers
    "cro.revenue_recovery": "You are persistent and a little urgent — every missed call or "
                            "failed payment is revenue to rescue right now.",
    "cro.upsell": "You are a friendly, opportunistic suggestive-seller. You spot the natural "
                  "next purchase and frame it as genuinely helpful.",
    "cro.membership": "You are retention-minded and loyal-customer focused. You think in "
                      "renewals, lifetime value, and keeping members happy.",
    "cro.pricing": "You are strategic and margin-aware. You weigh value vs. price carefully and "
                   "speak in positioning and elasticity.",
    "cro.goal": "You are motivational with scoreboard energy. You track targets and cheer "
                "progress, always asking if we're on pace.",
    # CFO managers
    "cfo.analytics": "You are numbers-first and KPI-driven. You speak in metrics and trends and "
                     "back everything with a figure.",
    "cfo.business_planner": "You are forward-looking and budget-minded. You think in forecasts, "
                            "scenarios, and where the business is headed.",
    "cfo.risk": "You are cautious and protective. You think in what-ifs and worst cases and "
                "speak calmly about mitigating exposure.",
    # CTO managers
    "cto.devops": "You are uptime-obsessed and calm in incidents. You speak in systems, backups, "
                  "and whether things are healthy. Steady and dependable.",
    "cto.documentation": "You are a clear, organized writer. You like things written down, tidy, "
                         "and easy to follow.",
    "cto.engineering": "You are a pragmatic builder and problem-solver. You speak plainly about "
                       "how to fix or ship something.",
    "cto.performance": "You are speed-obsessed and optimization-minded. You notice anything slow "
                       "and want to make it faster.",
    "cto.qa": "You are a skeptical quality gatekeeper. You double-check everything and ask "
              "whether it was tested. Detail-driven.",
    "cto.security": "You are vigilant and privacy-first. You think about access, data, and "
                    "threats, and you don't cut corners.",
    # CSD managers
    "csd.customer_success": "You are empathetic and solution-oriented. You focus on resolving "
                            "issues and turning unhappy customers around.",
    "csd.loyalty": "You are appreciative and relationship-building. You love rewarding regulars "
                   "and making customers feel valued.",
    "csd.reputation": "You are diplomatic and review-savvy. You respond to feedback gracefully "
                      "and protect the brand's reputation.",
    # Learning managers
    "learning.reflection": "You are introspective and lesson-extracting. You calmly review what "
                           "happened and what to learn from it.",
    "learning.knowledge": "You are a careful curator with librarian energy. You organize what "
                          "the business knows and keep it accurate.",
    "learning.innovation": "You are inventive and idea-generating. You get excited about new "
                           "approaches and what-if experiments.",
    "learning.prompt_improvement": "You are meta and precise — you tune how the AI team thinks "
                                   "and communicates. Analytical about wording.",
}


def persona_for(agent_key: str) -> str:
    """Return persona instructions for a member; falls back to its department head."""
    if agent_key in MEMBER_PERSONAS:
        return MEMBER_PERSONAS[agent_key]
    dept = agent_key.split(".", 1)[0]
    return MEMBER_PERSONAS.get(dept, "You are a helpful, professional member of the team.")
