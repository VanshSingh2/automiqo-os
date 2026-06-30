"use client";
import { useState, useEffect } from "react";
import { Check, X } from "@/components/icons";
import { fetchApprovals, approveItem, rejectItem } from "@/lib/api";

const BUSINESS_ID = process.env.NEXT_PUBLIC_BUSINESS_ID || "00000000-0000-0000-0000-000000000001";

type Approval = {
  id: string;
  title: string;
  category: string;
  priority: string;
  description: string;
  generated_by: string;
};

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchApprovals(BUSINESS_ID).then((data) => {
      setApprovals(data as Approval[]);
      setLoading(false);
    });
  }, []);

  async function handle(id: string, action: "approve" | "reject") {
    const ok = action === "approve" ? await approveItem(id) : await rejectItem(id);
    if (ok) setApprovals((prev) => prev.filter((a) => a.id !== id));
  }

  return (
    <div className="mx-auto max-w-4xl p-6 lg:p-8">
      <h1 className="text-2xl font-semibold tracking-tight text-slate-800">Pending Approvals</h1>
      <p className="mb-6 mt-1 text-sm text-slate-500">
        {loading ? "Loading…" : `${approvals.length} decision${approvals.length === 1 ? "" : "s"} your AI team wants your sign-off on`}
      </p>

      <div className="space-y-4">
        {approvals.map((a) => (
          <div key={a.id} className="soft-card animate-fadein p-5">
            <div className="flex items-start justify-between gap-3">
              <p className="font-semibold text-slate-800">{a.title}</p>
              <div className="flex shrink-0 gap-2">
                <span className={`pill ${a.priority === "high" ? "bg-rose-50 text-rose-500" : "bg-indigo-50 text-indigo-500"}`}>{a.priority}</span>
                <span className="pill bg-slate-100 text-slate-400">{a.category}</span>
              </div>
            </div>
            <p className="mt-0.5 text-xs text-slate-400">From: {a.generated_by}</p>
            <p className="mt-3 text-sm leading-relaxed text-slate-600">{a.description}</p>
            <div className="mt-4 flex gap-2">
              <button onClick={() => handle(a.id, "approve")}
                className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-600">
                <Check className="h-4 w-4" /> Approve
              </button>
              <button onClick={() => handle(a.id, "reject")}
                className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-500 transition hover:bg-slate-50">
                <X className="h-4 w-4" /> Reject
              </button>
            </div>
          </div>
        ))}
        {!loading && approvals.length === 0 && (
          <div className="soft-card py-12 text-center text-sm text-slate-400">All caught up — no pending approvals. 🎉</div>
        )}
      </div>
    </div>
  );
}
