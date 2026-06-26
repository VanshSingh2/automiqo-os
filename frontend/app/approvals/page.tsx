"use client";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const DEMO_APPROVALS = [
  { id: "1", title: "Launch Reactivation Campaign", category: "campaign", priority: "high",
    description: "Send personalized SMS to 12 dormant customers (30+ days inactive). Estimated 3-4 rebookings worth ~$1,200.", generated_by: "CRO" },
  { id: "2", title: "Update Botox FAQ", category: "faq_addition", priority: "normal",
    description: "Customers asked about bruising recovery 5 times this week. Add answer to knowledge base.", generated_by: "Learning Director" },
  { id: "3", title: "Increase Filler Pricing", category: "strategy", priority: "normal",
    description: "Competitor analysis shows our filler prices are 15% below market. Recommend +$50 per syringe.", generated_by: "CFO" },
];

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState(DEMO_APPROVALS);

  function handle(id: string) {
    setApprovals((prev) => prev.filter((a) => a.id !== id));
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-2">Pending Approvals</h1>
      <p className="text-gray-400 mb-6 text-sm">{approvals.length} recommendations from your AI team</p>
      <div className="space-y-4">
        {approvals.map((a) => (
          <Card key={a.id} className="bg-[#1A1A2E] border-[#2A2A4E]">
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between">
                <CardTitle className="text-white text-base">{a.title}</CardTitle>
                <div className="flex gap-2">
                  <Badge className={a.priority === "high" ? "bg-orange-500/20 text-orange-400" : "bg-blue-500/20 text-blue-400"}>
                    {a.priority}
                  </Badge>
                  <Badge className="bg-gray-500/20 text-gray-400">{a.category}</Badge>
                </div>
              </div>
              <p className="text-xs text-gray-500">From: {a.generated_by}</p>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-gray-300 mb-4">{a.description}</p>
              <div className="flex gap-2">
                <Button onClick={() => handle(a.id)} className="bg-green-600 hover:bg-green-700 text-white text-sm">
                  Approve
                </Button>
                <Button onClick={() => handle(a.id)} variant="outline" className="border-[#2A2A4E] text-gray-400 hover:text-white text-sm">
                  Reject
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
        {approvals.length === 0 && (
          <div className="text-center py-12 text-gray-500">
            <p>All caught up! No pending approvals.</p>
          </div>
        )}
      </div>
    </div>
  );
}
