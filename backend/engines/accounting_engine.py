"""
Accounting Engine — expense tracking, P&L, tax categorization, reconciliation.
Lightweight bookkeeping the CFO uses. Stores to `expenses` table; revenue is
read from completed appointments.
"""
from datetime import datetime, timezone, timedelta
from backend.memory.supabase_client import get_supabase

TAX_CATEGORIES = {
    "supplies": "Cost of Goods Sold",
    "inventory": "Cost of Goods Sold",
    "rent": "Operating Expense",
    "utilities": "Operating Expense",
    "payroll": "Payroll",
    "marketing": "Advertising",
    "software": "Operating Expense",
    "ai_costs": "Operating Expense",
    "equipment": "Capital Expense",
    "insurance": "Operating Expense",
    "professional": "Professional Services",
    "other": "Other",
}


def _categorize(description: str, category: str) -> str:
    return TAX_CATEGORIES.get((category or "other").lower(), "Other")


class AccountingEngine:
    async def log_expense(self, business_id: str, amount: float, category: str,
                          description: str = "", vendor: str = "", date: str = None) -> dict:
        """Record a business expense with automatic tax categorization."""
        sb = get_supabase()
        row = {
            "business_id": business_id,
            "amount": float(amount),
            "category": category,
            "tax_category": _categorize(description, category),
            "description": description,
            "vendor": vendor,
            "expense_date": date or datetime.now(timezone.utc).date().isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            sb.table("expenses").insert(row).execute()
            return {"logged": True, "tax_category": row["tax_category"]}
        except Exception as e:
            return {"logged": False, "error": str(e)}

    async def profit_and_loss(self, business_id: str, period_days: int = 30) -> dict:
        """Compute a P&L statement: revenue - expenses by category."""
        sb = get_supabase()
        since = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()

        # Revenue from completed appointments
        appts = sb.table("appointments").select("revenue").eq("business_id", business_id)\
            .eq("status", "completed").gte("scheduled_at", since).execute().data or []
        revenue = sum(float(a.get("revenue") or 0) for a in appts)

        # Expenses
        expenses = sb.table("expenses").select("amount,category,tax_category")\
            .eq("business_id", business_id).gte("expense_date",
            (datetime.now(timezone.utc) - timedelta(days=period_days)).date().isoformat()).execute().data or []
        total_expenses = sum(float(e.get("amount") or 0) for e in expenses)

        by_category = {}
        for e in expenses:
            c = e.get("tax_category", "Other")
            by_category[c] = by_category.get(c, 0) + float(e.get("amount") or 0)

        # AI costs are an operating expense too
        ai = sb.table("ai_costs").select("cost_usd").eq("business_id", business_id)\
            .gte("created_at", since).execute().data or []
        ai_cost = sum(float(c.get("cost_usd") or 0) for c in ai)
        if ai_cost:
            by_category["AI/Software"] = by_category.get("AI/Software", 0) + ai_cost
            total_expenses += ai_cost

        net = revenue - total_expenses
        return {
            "period_days": period_days,
            "revenue": round(revenue, 2),
            "total_expenses": round(total_expenses, 2),
            "net_profit": round(net, 2),
            "profit_margin_pct": round(net / revenue * 100, 1) if revenue else 0,
            "expenses_by_category": {k: round(v, 2) for k, v in by_category.items()},
            "appointment_count": len(appts),
        }

    async def tax_summary(self, business_id: str, year: int = None) -> dict:
        """Year-to-date expense totals grouped by tax category (for filing)."""
        sb = get_supabase()
        yr = year or datetime.now(timezone.utc).year
        start = f"{yr}-01-01"
        expenses = sb.table("expenses").select("amount,tax_category")\
            .eq("business_id", business_id).gte("expense_date", start).execute().data or []
        by_tax = {}
        for e in expenses:
            c = e.get("tax_category", "Other")
            by_tax[c] = by_tax.get(c, 0) + float(e.get("amount") or 0)
        return {
            "year": yr,
            "deductible_by_category": {k: round(v, 2) for k, v in by_tax.items()},
            "total_deductible": round(sum(by_tax.values()), 2),
        }


accounting_engine = AccountingEngine()
