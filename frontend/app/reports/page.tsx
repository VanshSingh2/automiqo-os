"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const DEMO_REPORTS = [
  { date: "2026-06-27", type: "daily", summary: "Strong day: $2,840 revenue (14 appointments). 1 no-show. 2 missed calls auto-recovered. Emma Wilson rebooked for next month." },
  { date: "2026-06-26", type: "daily", summary: "$2,100 revenue (11 appointments). Revenue down 15% — 3 same-day cancellations. Recommend: tighter cancellation policy." },
  { date: "2026-06-20", type: "weekly", summary: "Week of June 16-20: $12,400 total. Top service: Botox (38%). 2 new VIP customers. Reactivation campaign sent to 8 dormant members." },
];

export default function ReportsPage() {
  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-6">Reports</h1>
      <div className="space-y-4">
        {DEMO_REPORTS.map((r, i) => (
          <Card key={i} className="bg-[#1A1A2E] border-[#2A2A4E]">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-white text-sm font-medium">{r.date}</CardTitle>
                <span className="text-xs text-blue-400 uppercase">{r.type}</span>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-gray-300">{r.summary}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
