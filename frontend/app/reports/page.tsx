"use client";
import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-6">Reports</h1>
      {loading && <p className="text-gray-400">Loading reports...</p>}
      <div className="space-y-4">
        {reports.map((r) => (
          <Card key={r.id} className="bg-[#1A1A2E] border-[#2A2A4E]">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-white text-sm font-medium">{r.report_date}</CardTitle>
                <span className="text-xs text-blue-400 uppercase">{r.report_type}</span>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-gray-300">{r.summary || "No summary available"}</p>
              <p className="text-xs text-gray-600 mt-2">{new Date(r.generated_at).toLocaleString()}</p>
            </CardContent>
          </Card>
        ))}
        {!loading && reports.length === 0 && (
          <p className="text-gray-500 text-center py-8">No reports yet. Run morning briefing to generate the first one.</p>
        )}
      </div>
    </div>
  );
}
