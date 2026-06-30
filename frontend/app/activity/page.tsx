"use client";
import { useEffect, useState } from "react";
import { getBackstage, type ActivityItem } from "@/lib/api";

const BUSINESS_ID = process.env.NEXT_PUBLIC_BUSINESS_ID || "00000000-0000-0000-0000-000000000001";

const fmt = (s?: string) => {
  if (!s) return "";
  const d = new Date(s);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

export default function ActivityPage() {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () => getBackstage(BUSINESS_ID).then((a) => { setItems(a); setLoading(false); });
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="mx-auto max-w-4xl p-6 lg:p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-800">Behind the Scenes</h1>
        <p className="mt-1 text-sm text-slate-500">
          Everything your AI team is doing under the hood — in plain English. Live, refreshes every 10s.
        </p>
      </div>

      <div className="soft-card overflow-hidden">
        {loading && <p className="py-12 text-center text-sm text-slate-400">Loading activity…</p>}
        {!loading && items.length === 0 && (
          <p className="py-12 text-center text-sm text-slate-400">No backend activity recorded yet.</p>
        )}
        <div className="relative">
          {items.map((a, i) => (
            <div key={i} className="flex animate-fadein items-start gap-4 px-5 py-3.5 hover:bg-slate-50/60">
              <div className="flex flex-col items-center">
                <span className={`mt-1 h-2.5 w-2.5 rounded-full ${a.urgency === "high" ? "bg-rose-400" : "bg-indigo-300"}`} />
                {i < items.length - 1 && <span className="mt-1 w-px flex-1 bg-slate-100" style={{ minHeight: 18 }} />}
              </div>
              <div className="min-w-0 flex-1 pb-1">
                <p className="text-sm text-slate-700">
                  <span className="font-medium text-slate-800">{a.who}</span> · {a.action}
                </p>
                <div className="mt-1 flex items-center gap-2">
                  {a.event_type && <span className="pill bg-slate-100 text-slate-400">{a.event_type}</span>}
                  {a.urgency === "high" && <span className="pill bg-rose-50 text-rose-500">urgent</span>}
                  <span className="text-[11px] text-slate-300">{fmt(a.at)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
