"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const DEMO_METRICS = [
  { title: "Revenue Today", value: "$2,840", delta: "+12% vs yesterday", color: "text-green-400" },
  { title: "Appointments", value: "14", delta: "3 completed • 2 pending", color: "text-blue-400" },
  { title: "Missed Calls", value: "2", delta: "Auto-recovering now", color: "text-yellow-400" },
  { title: "Pending Approvals", value: "3", delta: "Review needed", color: "text-orange-400" },
];

const DEMO_ALERTS = [
  { type: "warning", message: "James Park hasn't visited in 45 days — send reactivation?" },
  { type: "info", message: "Lisa Torres flagged as churn risk — 2 visits, no rebook" },
  { type: "success", message: "Emma Wilson completed Botox — review request sent" },
];

export default function DashboardPage() {
  return (
    <div className="p-6 min-h-screen">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold text-white mb-2">Good morning 👋</h1>
        <p className="text-gray-400 mb-6 text-sm">Here&apos;s what&apos;s happening at Glow Med Spa today</p>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {DEMO_METRICS.map((m) => (
            <Card key={m.title} className="bg-[#1A1A2E] border-[#2A2A4E]">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm text-gray-400 font-normal">{m.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-bold text-white">{m.value}</p>
                <p className={`text-xs mt-1 ${m.color}`}>{m.delta}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="bg-[#1A1A2E] border border-[#2A2A4E] rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-400 mb-3">AI Alerts</h2>
          <div className="space-y-2">
            {DEMO_ALERTS.map((a, i) => (
              <div key={i} className={`flex items-start gap-3 p-3 rounded-lg ${
                a.type === "warning" ? "bg-yellow-500/10 border border-yellow-500/20" :
                a.type === "success" ? "bg-green-500/10 border border-green-500/20" :
                "bg-blue-500/10 border border-blue-500/20"
              }`}>
                <span className="text-sm text-gray-300">{a.message}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-600 mt-3">Connect Supabase credentials to see live data</p>
        </div>
      </div>
    </div>
  );
}
