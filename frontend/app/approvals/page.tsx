"use client";
import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-2">Pending Approvals</h1>
      <p className="text-gray-400 mb-6 text-sm">{loading ? "Loading..." : `${approvals.length} recommendations from your AI team`}</p>
      <div className="space-y-4">
        {approvals.map((a) => (
          <Card key={a.id} className="bg-[#1A1A2E] border-[#2A2A4E]">
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between">
                <CardTitle className="text-white text-base">{a.title}</CardTitle>
                <div className="flex gap-2">
                  <Badge className={a.priority === "high" ? "bg-orange-500/20 text-orange-400" : "bg-blue-500/20 text-blue-400"}>{a.priority}</Badge>
                  <Badge className="bg-gray-500/20 text-gray-400">{a.category}</Badge>
                </div>
              </div>
              <p className="text-xs text-gray-500">From: {a.generated_by}</p>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-gray-300 mb-4">{a.description}</p>
              <div className="flex gap-2">
                <Button onClick={() => handle(a.id, "approve")} className="bg-green-600 hover:bg-green-700 text-white text-sm">Approve</Button>
                <Button onClick={() => handle(a.id, "reject")} variant="outline" className="border-[#2A2A4E] text-gray-400 hover:text-white text-sm">Reject</Button>
              </div>
            </CardContent>
          </Card>
        ))}
        {!loading && approvals.length === 0 && (
          <div className="text-center py-12 text-gray-500">All caught up! No pending approvals.</div>
        )}
      </div>
    </div>
  );
}
