"""
Company Knowledge Graph — connects customers, services, staff, appointments,
workflows, reviews, and policies into a queryable graph.
Uses Supabase as the storage layer with relationship traversal in Python.
"""
from datetime import datetime, timezone, timedelta
from backend.memory.supabase_client import get_supabase


class KnowledgeGraph:
    async def get_customer_graph(self, business_id: str, customer_id: str) -> dict:
        """
        Full customer knowledge graph:
        Customer → appointments → staff → services → reviews → conversations
        """
        sb = get_supabase()
        # Customer
        customer = sb.table("customers").select("*").eq("business_id", business_id)\
            .eq("id", customer_id).limit(1).execute().data
        if not customer:
            return {}
        c = customer[0]

        # Their appointments
        appts = sb.table("appointments").select("id,service,scheduled_at,status,staff_id,revenue")\
            .eq("business_id", business_id).eq("customer_id", customer_id)\
            .order("scheduled_at", desc=True).limit(10).execute().data or []

        # Staff they've worked with
        staff_ids = list({a["staff_id"] for a in appts if a.get("staff_id")})
        staff = []
        if staff_ids:
            staff = sb.table("staff").select("id,name,role")\
                .in_("id", staff_ids).execute().data or []

        # Conversations
        convs = sb.table("conversations").select("state,message_count,created_at")\
            .eq("business_id", business_id).eq("contact_phone", c.get("phone", ""))\
            .order("created_at", desc=True).limit(5).execute().data or []

        # Calls
        calls = sb.table("calls").select("direction,status,sentiment,called_at")\
            .eq("business_id", business_id).eq("customer_id", customer_id)\
            .order("called_at", desc=True).limit(5).execute().data or []

        return {
            "customer": c,
            "appointments": appts,
            "preferred_staff": staff,
            "services_used": list({a.get("service") for a in appts if a.get("service")}),
            "total_visits": len([a for a in appts if a["status"] == "completed"]),
            "total_revenue": sum(float(a.get("revenue") or 0) for a in appts if a["status"] == "completed"),
            "conversations": convs,
            "calls": calls,
            "relationship_strength": self._calc_relationship_strength(appts, c),
        }

    def _calc_relationship_strength(self, appts: list, customer: dict) -> str:
        visits = sum(1 for a in appts if a["status"] == "completed")
        ltv = float(customer.get("lifetime_value") or 0)
        if visits >= 10 or ltv >= 2000: return "champion"
        if visits >= 5 or ltv >= 500:   return "loyal"
        if visits >= 2:                  return "regular"
        if visits == 1:                  return "new"
        return "prospect"

    async def get_business_graph(self, business_id: str) -> dict:
        """High-level business knowledge graph — connections and health."""
        sb = get_supabase()
        bid = business_id
        now = datetime.now(timezone.utc)
        month_ago = (now - timedelta(days=30)).isoformat()

        customers = sb.table("customers").select("id,tags,lifetime_value,last_visit")\
            .eq("business_id", bid).execute().data or []
        staff = sb.table("staff").select("id,name,role").eq("business_id", bid).eq("active", True).execute().data or []
        services = sb.table("appointments").select("service").eq("business_id", bid)\
            .gte("scheduled_at", month_ago).execute().data or []
        unique_services = list({s["service"] for s in services if s.get("service")})

        segments = {
            "champions": [c for c in customers if "vip" in (c.get("tags") or []) or float(c.get("lifetime_value") or 0) >= 2000],
            "loyal":     [c for c in customers if float(c.get("lifetime_value") or 0) >= 500],
            "at_risk":   [c for c in customers if "churn_risk" in (c.get("tags") or [])],
            "dormant":   [c for c in customers if c.get("last_visit") and c["last_visit"] < month_ago],
        }

        return {
            "total_customers": len(customers),
            "active_staff": len(staff),
            "services_offered": unique_services,
            "customer_segments": {k: len(v) for k, v in segments.items()},
            "top_staff": [{"id": s["id"], "name": s["name"], "role": s["role"]} for s in staff[:5]],
        }

    async def find_cross_sell_opportunities(self, business_id: str, customer_id: str) -> list[str]:
        """Find services the customer hasn't tried but similar customers have."""
        sb = get_supabase()
        graph = await self.get_customer_graph(business_id, customer_id)
        used_services = set(graph.get("services_used", []))

        all_services_data = sb.table("appointments").select("service").eq("business_id", business_id)\
            .eq("status", "completed").execute().data or []
        all_services = list({s["service"] for s in all_services_data if s.get("service")})

        untried = [s for s in all_services if s not in used_services]
        return untried[:3]


# Singleton
knowledge_graph = KnowledgeGraph()
