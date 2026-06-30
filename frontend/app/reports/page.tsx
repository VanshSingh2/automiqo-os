"use client";
import { useEffect, useState } from "react";
import { fetchReports } from "@/lib/api";

const BUSINESS_ID = process.env.NEXT_PUBLIC_BUSINESS_ID || "00000000-0000-0000-0000-000000000001";

type Report = {
  id: string;
  report_date: string;
  report_type: string;
  summary: string;
  generated_at: string;
};

export default function ReportsPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchReports(BUSINESS_ID).then((data) => {
      setReports(data as Report[]);
      setLoading(false);
    });
  }, []);

  return (
    <div className="mx-auto max-w-4xl p-6 lg:p-8">
      <h1 className="text-2xl font-semibold tracking-tight text-slate-800">Reports</h1>
      <p className="mb-6 mt-1 text-sm text-slate-500">Daily and weekly summaries from your AI team.</p>

      {loading && <p className="text-sm text-slate-400">Loading reports…</p>}
      <div className="space-y-4">
        {reports.map((r) => (
          <div key={r.id} className="soft-card animate-fadein p-5">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-slate-800">{r.report_date}</p>
              <span className="pill bg-indigo-50 uppercase text-indigo-500">{r.report_type}</span>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-slate-600">{r.summary || "No summary available"}</p>
            <p className="mt-2 text-[11px] text-slate-300">{new Date(r.generated_at).toLocaleString()}</p>
          </div>
        ))}
        {!loading && reports.length === 0 && (
          <div className="soft-card py-12 text-center text-sm text-slate-400">No reports yet. Run the morning briefing to generate the first one.</div>
        )}
      </div>
    </div>
  );
}
