"use client";
import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchMetrics } from "@/lib/api";

const BUSINESS_ID = process.env.NEXT_PUBLIC_BUSINESS_ID || "00000000-0000-0000-0000-000000000001";

type Metrics = {
  appointments_today?: number;
  completed_today?: number;
  no_shows_today?: number;
  revenue_today?: number;
  active_staff?: number;
};

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<Metrics>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchMetrics(BUSINESS_ID).then((m) => {
      setMetrics(m as Metrics);
      setLoading(false);
    });
    const interval = setInterval(() => {
      fetchMetrics(BUSINESS_ID).then((m) => setMetrics(m as Metrics));
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  const cards = [
    { title: "Revenue Today", value: loading ? "..." : `$${(metrics.revenue_today || 0).toLocaleString()}`, color: "text-green-400" },
    { title: "Appointments", value: loading ? "..." : String(metrics.appointments_today || 0), color: "text-blue-400" },
    { title: "Completed", value: loading ? "..." : String(metrics.completed_today || 0), color: "text-green-400" },
    { title: "No-Shows", value: loading ? "..." : String(metrics.no_shows_today || 0), color: "text-red-400" },
    { title: "Active Staff", value: loading ? "..." : String(metrics.active_staff || 0), color: "text-purple-400" },
  ];

  return (
    <div className="p-6 min-h-screen">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <p className="text-gray-400 text-sm mt-1">Live data &bull; refreshes every 30s</p>
          </div>
          <div className={`w-2 h-2 rounded-full ${loading ? "bg-yellow-400" : "bg-green-400"}`} />
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
          {cards.map((c) => (
            <Card key={c.title} className="bg-[#1A1A2E] border-[#2A2A4E]">
              <CardHeader className="pb-2">
                <CardTitle className="text-xs text-gray-400 font-normal">{c.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className={`text-2xl font-bold ${c.color}`}>{c.value}</p>
              </CardContent>
            </Card>
          ))}
        </div>
        <div className="bg-[#1A1A2E] border border-[#2A2A4E] rounded-xl p-4">
          <p className="text-sm text-gray-500">
            {loading ? "Loading live data..." : "Live data from Supabase. Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env to connect."}
          </p>
        </div>
      </div>
    </div>
  );
}
