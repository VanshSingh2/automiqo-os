"""Tests for business_blueprint: profiles, module resolution, overrides, roster."""
from backend.engines import business_blueprint as bp


# ── profile selection ───────────────────────────────────────────────────────
def test_profile_exact_match():
    assert bp.profile_for_industry("med spa") == "appointment_service"
    assert bp.profile_for_industry("ecommerce") == "ecommerce"


def test_profile_substring_match():
    assert bp.profile_for_industry("Luxury Med Spa & Wellness") == "appointment_service"
    assert bp.profile_for_industry("B2B SaaS startup") == "digital_service"


def test_profile_defaults_when_unknown():
    assert bp.profile_for_industry("underwater basket weaving") == bp.DEFAULT_PROFILE
    assert bp.profile_for_industry(None) == bp.DEFAULT_PROFILE


# ── module resolution ───────────────────────────────────────────────────────
def test_appointment_service_enables_inventory():
    assert bp.is_manager_enabled({"industry": "med spa"}, "coo", "inventory") is True


def test_digital_service_disables_inventory():
    # digital_service profile only enables appointments/crm/staff under COO
    cfg = {"industry": "ai agency"}
    assert bp.is_manager_enabled(cfg, "coo", "inventory") is False
    assert bp.is_manager_enabled(cfg, "coo", "appointments") is True


def test_ceo_always_enabled():
    assert bp.is_dept_enabled({"industry": "anything"}, "ceo") is True


def test_dept_override_turns_whole_dept_off():
    cfg = {"industry": "med spa", "module_overrides": {"coo": False}}
    assert bp.is_dept_enabled(cfg, "coo") is False
    # if dept off, managers are off too
    assert bp.is_manager_enabled(cfg, "coo", "inventory") is False


def test_manager_override_turns_single_manager_off():
    cfg = {"industry": "med spa", "module_overrides": {"coo.inventory": False}}
    assert bp.is_dept_enabled(cfg, "coo") is True
    assert bp.is_manager_enabled(cfg, "coo", "inventory") is False
    assert bp.is_manager_enabled(cfg, "coo", "appointments") is True


def test_manager_override_can_force_on():
    cfg = {"industry": "ai agency", "module_overrides": {"coo.inventory": True}}
    assert bp.is_manager_enabled(cfg, "coo", "inventory") is True


def test_enabled_depts_excludes_ceo_and_off_depts():
    cfg = {"industry": "med spa", "module_overrides": {"cto": False}}
    depts = bp.enabled_depts(cfg)
    assert "ceo" not in depts
    assert "cto" not in depts
    assert "coo" in depts



# ── summary / roster / personas ─────────────────────────────────────────────
def test_summary_shape():
    s = bp.summary({"industry": "med spa"})
    assert "profile" in s and "departments" in s
    keys = {d["key"] for d in s["departments"]}
    assert "ceo" not in keys  # CEO excluded from toggleable departments
    for d in s["departments"]:
        assert "enabled" in d and isinstance(d["managers"], list)


def test_team_roster_counts():
    roster = bp.team_roster({"industry": "med spa"})
    assert roster["total"] == len(roster["members"])
    assert roster["active"] <= roster["total"]
    ceo = [m for m in roster["members"] if m["key"] == "ceo"][0]
    assert ceo["can_toggle"] is False and ceo["enabled"] is True


def test_member_display_resolves_names():
    assert bp.member_display("ceo") == bp.HEAD_NAMES["ceo"]
    assert bp.member_display("coo") == bp.HEAD_NAMES["coo"]
    assert bp.member_display("coo.inventory") == "Inventory Manager"


def test_persona_falls_back_to_dept_head():
    # a manager without an explicit persona falls back to its dept head persona
    assert bp.persona_for("coo") == bp.MEMBER_PERSONAS["coo"]
    assert bp.persona_for("nonexistent.manager") == bp.MEMBER_PERSONAS.get(
        "nonexistent", "You are a helpful, professional member of the team.")


def test_resolve_modules_does_not_mutate_template():
    cfg = {"industry": "med spa", "module_overrides": {"coo.inventory": False}}
    bp.resolve_modules(cfg)
    # a fresh resolve for another business must still have inventory on
    assert bp.is_manager_enabled({"industry": "med spa"}, "coo", "inventory") is True


def test_every_dept_has_a_head_name_and_description():
    for dept in bp.DEPARTMENTS:
        assert dept in bp.HEAD_NAMES
        assert dept in bp.DEPT_DESCRIPTIONS
