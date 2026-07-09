"use client";
import { useEffect, useState } from "react";
import {
  Activity as ActivityIcon, CheckCircle2, DollarSign, Users,
} from "@/components/icons";
import {
  getAccountabilitySummary, getAccountabilityAgents, getAccountabilityRecent,
  type AccountabilitySummary, type AgentRollup, type AgentMetricRow,
} from "@/lib/api";

const BUSINESS_ID = process.env.NEXT_PUBLIC_BUSINESS_ID || "00000000-0000-0000-0000-000000000001";
const WINDOW_DAYS = 14;

const pct = (v: number) => `${Math.round((v || 0) * 100)}%`;
const usd = (v: number) => `$${(v || 0).toFixed(2)}`;
const ms = (v: number) => `${Math.round(v || 0)} ms`;

const fmt = (s?: string) => {
  if (!s) return "";
  const d = new Date(s);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

// green >=0.9, amber >=0.7, red below
const rateClass = (r: number) =>
  r >= 0.9 ? "text-emerald-600" : r >= 0.7 ? "text-amber-600" : "text-rose-600";

export default function AccountabilityPage() {
  const [summary, setSummary] = useState<AccountabilitySummary | null>(null);
  const [agents, setAgents] = useState<AgentRollup[]>([]);
  const [recent, setRecent] = useState<AgentMetricRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () => {
      getAccountabilitySummary(BUSINESS_ID, WINDOW_DAYS).then((s) => { setSummary(s); setLoading(false); });
      getAccountabilityAgents(BUSINESS_ID, WINDOW_DAYS).then((a) => setAgents(a));
      getAccountabilityRecent(BUSINESS_ID, 50).then((r) => setRecent(r));
    };
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const sortedAgents = [...agents].sort((a, b) => b.runs - a.runs);

  const cards = [
    { title: "Total runs", value: loading ? "—" : String(summary?.total_runs ?? 0), icon: ActivityIcon, tint: "from-indigo-400 to-violet-400" },
    { title: "Overall success", value: loading ? "—" : pct(summary?.overall_success_rate ?? 0), icon: CheckCircle2, tint: "from-emerald-400 to-teal-400" },
    { title: "Total cost", value: loading ? "—" : usd(summary?.total_cost_usd ?? 0), icon: DollarSign, tint: "from-amber-400 to-yellow-400" },
    { title: "Avg latency", value: loading ? "—" : ms(summary?.avg_latency_ms ?? 0), icon: ActivityIcon, tint: "from-sky-400 to-cyan-400" },
    { title: "Active agents", value: loading ? "—" : String(summary?.agent_count ?? 0), icon: Users, tint: "from-rose-400 to-orange-400" },
  ];

  return (
    <div className="mx-auto max-w-7xl p-6 lg:p-8">
      <div className="mb-7">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-800">Accountability</h1>
        <p className="mt-1 text-sm text-slate-500">
          How your AI team is performing over the last {WINDOW_DAYS} days · refreshes every 30s
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {cards.map((c, i) => (
          <div key={c.title} className="soft-card animate-fadein p-5" style={{ animationDelay: `${i * 50}ms` }}>
            <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br ${c.tint} text-white shadow-sm`}>
              <c.icon className="h-5 w-5" />
            </div>
            <p className="text-2xl font-semibold text-slate-800">{c.value}</p>
            <p className="mt-0.5 text-xs font-medium text-slate-400">{c.title}</p>
          </div>
        ))}
      </div>

      {/* Per-agent rollups */}
      <div className="mt-6 soft-card overflow-hidden">
        <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-4">
          <Users className="h-4 w-4 text-indigo-500" />
          <h2 className="text-sm font-semibold text-slate-700">Per-agent performance</h2>
        </div>
        {loading && <p className="py-12 text-center text-sm text-slate-400">Loading metrics…</p>}
        {!loading && sortedAgents.length === 0 && (
          <p className="py-12 text-center text-sm text-slate-400">No metrics yet — your agents just start recording.</p>
        )}
        {sortedAgents.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-wide text-slate-400">
                  <th className="px-5 py-3 font-medium">Agent</th>
                  <th className="px-5 py-3 font-medium">Runs</th>
                  <th className="px-5 py-3 font-medium">Success rate</th>
                  <th className="px-5 py-3 font-medium">Avg latency</th>
                  <th className="px-5 py-3 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {sortedAgents.map((a) => (
                  <tr key={a.agent_name} className="hover:bg-slate-50/60">
                    <td className="px-5 py-3 font-medium text-slate-800">{a.agent_name}</td>
                    <td className="px-5 py-3 text-slate-600">{a.runs}</td>
                    <td className={`px-5 py-3 font-semibold ${rateClass(a.success_rate)}`}>{pct(a.success_rate)}</td>
                    <td className="px-5 py-3 text-slate-600">{ms(a.avg_latency_ms)}</td>
                    <td className="px-5 py-3 text-slate-600">{usd(a.total_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent activity */}
      <div className="mt-6 soft-card overflow-hidden">
        <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-4">
          <ActivityIcon className="h-4 w-4 text-indigo-500" />
          <h2 className="text-sm font-semibold text-slate-700">Recent activity</h2>
        </div>
        {!loading && recent.length === 0 && (
          <p className="py-12 text-center text-sm text-slate-400">No recent runs recorded yet.</p>
        )}
        {recent.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-wide text-slate-400">
                  <th className="px-5 py-3 font-medium">Agent</th>
                  <th className="px-5 py-3 font-medium">Event</th>
                  <th className="px-5 py-3 font-medium">Workflow</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Latency</th>
                  <th className="px-5 py-3 font-medium">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {recent.map((r, i) => (
                  <tr key={r.trace_id || i} className="hover:bg-slate-50/60">
                    <td className="px-5 py-3 font-medium text-slate-800">{r.agent_name}</td>
                    <td className="px-5 py-3 text-slate-600">{r.event}</td>
                    <td className="px-5 py-3 text-slate-500">{r.workflow}</td>
                    <td className={`px-5 py-3 font-semibold ${r.success ? "text-emerald-600" : "text-rose-600"}`}>
                      {r.success ? "✓" : "✗"}
                    </td>
                    <td className="px-5 py-3 text-slate-600">{ms(r.latency_ms)}</td>
                    <td className="px-5 py-3 text-[11px] text-slate-400">{fmt(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
