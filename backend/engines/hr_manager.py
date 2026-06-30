"""
HR Manager Engine — hiring pipeline, staff scheduling, certification tracking,
onboarding. Used by COO. Stores applicants in `applicants`, shifts in `shifts`.
"""
from datetime import datetime, timezone, timedelta
from backend.memory.supabase_client import get_supabase


class HRManager:
    # ── Hiring pipeline ───────────────────────────────────────────────────────
    async def add_applicant(self, business_id: str, name: str, role: str,
                            email: str = "", phone: str = "", resume_text: str = "") -> dict:
        sb = get_supabase()
        try:
            r = sb.table("applicants").insert({
                "business_id": business_id, "name": name, "role": role,
                "email": email, "phone": phone, "resume_text": resume_text[:4000],
                "stage": "applied", "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            return {"added": True, "applicant_id": r.data[0]["id"] if r.data else None}
        except Exception as e:
            return {"added": False, "error": str(e)}

    async def screen_applicant(self, business_id: str, applicant_id: str) -> dict:
        """LLM screens a resume against the role; advances or rejects."""
        import os, json, re
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage
        sb = get_supabase()
        app = sb.table("applicants").select("*").eq("id", applicant_id)\
            .eq("business_id", business_id).limit(1).execute().data
        if not app:
            return {"error": "applicant not found"}
        a = app[0]
        try:
            llm = ChatOpenAI(model=os.getenv("DEPT_MODEL", "gpt-4o-mini").split("/")[-1],
                             api_key=os.getenv("OPENAI_API_KEY", ""))
            resp = await llm.ainvoke([
                SystemMessage(content="You are an HR screener. Score this applicant 0-100 for the role and recommend advance/reject. Respond JSON: {score, recommendation, reasons}."),
                HumanMessage(content=f"Role: {a.get('role')}\nResume: {a.get('resume_text','')[:2000]}"),
            ])
            raw = resp.content.strip()
            m = re.search(r"```[\w]*\s*([\s\S]*?)```", raw)
            data = json.loads(m.group(1).strip() if m else raw)
        except Exception:
            data = {"score": 50, "recommendation": "review", "reasons": "auto-screen unavailable"}
        new_stage = "screened_advance" if data.get("score", 0) >= 65 else "screened_reject"
        sb.table("applicants").update({
            "stage": new_stage, "screen_score": data.get("score"),
            "screen_notes": str(data.get("reasons", "")),
        }).eq("id", applicant_id).execute()
        return {"applicant_id": applicant_id, "stage": new_stage, **data}

    # ── Scheduling ────────────────────────────────────────────────────────────
    async def schedule_shift(self, business_id: str, staff_id: str,
                            starts_at: str, ends_at: str, role: str = "") -> dict:
        sb = get_supabase()
        try:
            sb.table("shifts").insert({
                "business_id": business_id, "staff_id": staff_id,
                "starts_at": starts_at, "ends_at": ends_at, "role": role,
                "status": "scheduled", "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            return {"scheduled": True}
        except Exception as e:
            return {"scheduled": False, "error": str(e)}

    async def coverage_check(self, business_id: str) -> dict:
        """Check if today's appointments have enough staff scheduled."""
        sb = get_supabase()
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0).isoformat()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0).isoformat()
        appts = sb.table("appointments").select("id").eq("business_id", business_id)\
            .gte("scheduled_at", today).lt("scheduled_at", tomorrow).execute().data or []
        shifts = sb.table("shifts").select("id,staff_id").eq("business_id", business_id)\
            .gte("starts_at", today).lt("starts_at", tomorrow).execute().data or []
        active_staff = sb.table("staff").select("id").eq("business_id", business_id)\
            .eq("active", True).execute().data or []
        gap = len(appts) > 0 and len(shifts) == 0 and len(active_staff) == 0
        return {
            "appointments_today": len(appts),
            "shifts_scheduled": len(shifts),
            "active_staff": len(active_staff),
            "coverage_gap": gap,
        }

    # ── Certifications ────────────────────────────────────────────────────────
    async def expiring_certifications(self, business_id: str, within_days: int = 30) -> list[dict]:
        """Staff certifications expiring soon (read from staff.certifications JSON)."""
        sb = get_supabase()
        staff = sb.table("staff").select("id,name,certifications").eq("business_id", business_id)\
            .eq("active", True).execute().data or []
        soon = (datetime.now(timezone.utc) + timedelta(days=within_days)).date().isoformat()
        expiring = []
        for s in staff:
            for cert in (s.get("certifications") or []):
                exp = cert.get("expires") if isinstance(cert, dict) else None
                if exp and exp <= soon:
                    expiring.append({"staff": s["name"], "cert": cert.get("name"), "expires": exp})
        return expiring

    async def hiring_pipeline(self, business_id: str) -> dict:
        """Pipeline summary by stage."""
        sb = get_supabase()
        apps = sb.table("applicants").select("stage").eq("business_id", business_id).execute().data or []
        by_stage = {}
        for a in apps:
            by_stage[a.get("stage", "applied")] = by_stage.get(a.get("stage", "applied"), 0) + 1
        return {"total_applicants": len(apps), "by_stage": by_stage}


hr_manager = HRManager()
