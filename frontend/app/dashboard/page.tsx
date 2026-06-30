"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  DollarSign, CalendarCheck, CheckCircle2, UserX, Users, ArrowRight, Activity as ActivityIcon,
} from "@/components/icons";
import { fetchMetrics, getBackstage, type ActivityItem } from "@/lib/api";

const BUSINESS_ID = process.env.NEXT_PUBLIC_BUSINESS_ID || "00000000-0000-0000-0000-000000000001";

type Metrics = {
  appointments_today?: number;
  completed_today?: number;
  no_shows_today?: number;
  revenue_today?: number;
  active_staff?: number;
};

const fmtTime = (s?: string) => {
  if (!s) return "";
  const d = new Date(s);
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<Metrics>({});
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const load = () => {
      fetchMetrics(BUSINESS_ID).then((m) => {
        setOffline(Object.keys(m).length === 0);
        setMetrics(m as Metrics);
        setLoading(false);
      });
      getBackstage(BUSINESS_ID).then((a) => setActivity(a.slice(0, 8)));
    };
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const cards = [
    { title: "Revenue Today", value: loading ? "—" : `$${(metrics.revenue_today || 0).toLocaleString()}`, icon: DollarSign, tint: "from-emerald-400 to-teal-400" },
    { title: "Appointments", value: loading ? "—" : String(metrics.appointments_today || 0), icon: CalendarCheck, tint: "from-indigo-400 to-violet-400" },
    { title: "Completed", value: loading ? "—" : String(metrics.completed_today || 0), icon: CheckCircle2, tint: "from-sky-400 to-cyan-400" },
    { title: "No-Shows", value: loading ? "—" : String(metrics.no_shows_today || 0), icon: UserX, tint: "from-rose-400 to-orange-400" },
    { title: "Active Staff", value: loading ? "—" : String(metrics.active_staff || 0), icon: Users, tint: "from-amber-400 to-yellow-400" },
  ];

  return (
    <div className="mx-auto max-w-7xl p-6 lg:p-8">
      <div className="mb-7">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-800">Good day 👋</h1>
        <p className="mt-1 text-sm text-slate-500">Here's how your business is doing today · refreshes every 30s</p>
      </div>

      {offline && (
        <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          Backend unreachable — start <code className="rounded bg-amber-100 px-1.5 py-0.5">uvicorn</code> on port 8000 to see live data.
        </div>
      )}

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

      <div className="mt-6 grid gap-5 lg:grid-cols-3">
        {/* Live activity */}
        <div className="soft-card lg:col-span-2">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div className="flex items-center gap-2">
              <ActivityIcon className="h-4 w-4 text-indigo-500" />
              <h2 className="text-sm font-semibold text-slate-700">Live activity</h2>
            </div>
            <Link href="/activity" className="flex items-center gap-1 text-xs font-medium text-indigo-500 hover:text-indigo-600">
              View all <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          <div className="divide-y divide-slate-50">
            {activity.length === 0 && (
              <p className="px-5 py-8 text-center text-sm text-slate-400">No activity yet — your AI team's work will appear here.</p>
            )}
            {activity.map((a, i) => (
              <div key={i} className="flex items-start gap-3 px-5 py-3">
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${a.urgency === "high" ? "bg-rose-400" : "bg-indigo-300"}`} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-slate-700"><span className="font-medium text-slate-800">{a.who}</span> · {a.action}</p>
                </div>
                <span className="shrink-0 text-[11px] text-slate-300">{fmtTime(a.at)}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Quick links */}
        <div className="flex flex-col gap-4">
          <Link href="/team" className="soft-card group flex items-center justify-between p-5 transition hover:-translate-y-0.5">
            <div>
              <p className="font-medium text-slate-800">Team Chat</p>
              <p className="mt-0.5 text-xs text-slate-400">See your AI team talk it out</p>
            </div>
            <ArrowRight className="h-4 w-4 text-slate-300 transition group-hover:text-indigo-500" />
          </Link>
          <Link href="/chat" className="soft-card group flex items-center justify-between p-5 transition hover:-translate-y-0.5">
            <div>
              <p className="font-medium text-slate-800">Ask the CEO AI</p>
              <p className="mt-0.5 text-xs text-slate-400">Get a plan or a quick answer</p>
            </div>
            <ArrowRight className="h-4 w-4 text-slate-300 transition group-hover:text-indigo-500" />
          </Link>
          <Link href="/modules" className="soft-card group flex items-center justify-between p-5 transition hover:-translate-y-0.5">
            <div>
              <p className="font-medium text-slate-800">Configure Modules</p>
              <p className="mt-0.5 text-xs text-slate-400">Turn departments on/off</p>
            </div>
            <ArrowRight className="h-4 w-4 text-slate-300 transition group-hover:text-indigo-500" />
          </Link>
        </div>
      </div>
    </div>
  );
}
