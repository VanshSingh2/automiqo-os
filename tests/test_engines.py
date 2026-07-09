"""Tests for accounting + HR engine logic (deterministic, fake Supabase)."""
from unittest.mock import patch

from backend.engines.accounting_engine import accounting_engine, _categorize
from backend.engines.hr_manager import hr_manager


# ── accounting: tax categorization ──────────────────────────────────────────
def test_categorize_maps_known_categories():
    assert _categorize("", "supplies") == "Cost of Goods Sold"
    assert _categorize("", "rent") == "Operating Expense"
    assert _categorize("", "marketing") == "Advertising"


def test_categorize_unknown_is_other():
    assert _categorize("", "banana") == "Other"


async def test_log_expense_sets_tax_category(make_sb):
    sb = make_sb()
    with patch("backend.engines.accounting_engine.get_supabase", return_value=sb):
        out = await accounting_engine.log_expense("biz-1", 100.0, "supplies", "gloves")
    assert out["logged"] is True
    assert out["tax_category"] == "Cost of Goods Sold"
    assert sb.queries["expenses"].inserted[0]["amount"] == 100.0


async def test_profit_and_loss_computes_net(make_sb):
    sb = make_sb({
        "appointments": [{"revenue": 500}, {"revenue": 300}],
        "expenses": [{"amount": 200, "category": "rent", "tax_category": "Operating Expense"}],
        "ai_costs": [{"cost_usd": 10}],
    })
    with patch("backend.engines.accounting_engine.get_supabase", return_value=sb):
        pnl = await accounting_engine.profit_and_loss("biz-1", period_days=30)
    assert pnl["revenue"] == 800.0
    # 200 expenses + 10 ai costs
    assert pnl["total_expenses"] == 210.0
    assert pnl["net_profit"] == 590.0
    assert pnl["expenses_by_category"]["Operating Expense"] == 200.0



# ── HR: pipeline + coverage ─────────────────────────────────────────────────
async def test_add_applicant(make_sb):
    sb = make_sb(insert_id="app-1")
    with patch("backend.engines.hr_manager.get_supabase", return_value=sb):
        out = await hr_manager.add_applicant("biz-1", "Jane", "esthetician", email="j@x.com")
    assert out["added"] is True
    assert out["applicant_id"] == "app-1"
    assert sb.queries["applicants"].inserted[0]["stage"] == "applied"


async def test_hiring_pipeline_groups_by_stage(make_sb):
    sb = make_sb({"applicants": [
        {"stage": "applied"}, {"stage": "applied"}, {"stage": "screened_advance"},
    ]})
    with patch("backend.engines.hr_manager.get_supabase", return_value=sb):
        out = await hr_manager.hiring_pipeline("biz-1")
    assert out["total_applicants"] == 3
    assert out["by_stage"]["applied"] == 2
    assert out["by_stage"]["screened_advance"] == 1


async def test_coverage_check_flags_gap(make_sb):
    # appointments exist but no shifts and no active staff -> coverage gap
    sb = make_sb({
        "appointments": [{"id": "a1"}, {"id": "a2"}],
        "shifts": [],
        "staff": [],
    })
    with patch("backend.engines.hr_manager.get_supabase", return_value=sb):
        out = await hr_manager.coverage_check("biz-1")
    assert out["appointments_today"] == 2
    assert out["coverage_gap"] is True


async def test_coverage_check_no_gap_when_staffed(make_sb):
    sb = make_sb({
        "appointments": [{"id": "a1"}],
        "shifts": [{"id": "s1", "staff_id": "st1"}],
        "staff": [{"id": "st1"}],
    })
    with patch("backend.engines.hr_manager.get_supabase", return_value=sb):
        out = await hr_manager.coverage_check("biz-1")
    assert out["coverage_gap"] is False
