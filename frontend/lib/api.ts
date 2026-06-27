const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function streamChat(
  businessId: string,
  message: string,
  onChunk: (chunk: string) => void,
  onDone: (metrics: Record<string, unknown>, recommendations: string[]) => void,
  onError?: (error: string) => void
) {
  try {
    const res = await fetch(`${BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ business_id: businessId, message }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const reader = res.body?.getReader();
    if (!reader) return;
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = decoder.decode(value);
      const lines = text.split("\n").filter((l) => l.startsWith("data: "));
      for (const line of lines) {
        try {
          const data = JSON.parse(line.replace("data: ", ""));
          if (data.error) { onError?.(data.error); return; }
          if (data.done) { onDone(data.metrics || {}, data.recommendations || []); }
          else if (data.chunk) { onChunk(data.chunk); }
        } catch {}
      }
    }
  } catch (e) { onError?.(String(e)); }
}

export async function fetchMetrics(businessId: string): Promise<Record<string, unknown>> {
  try {
    const res = await fetch(`${BASE}/metrics/${businessId}`);
    if (!res.ok) return {};
    return res.json();
  } catch { return {}; }
}

export async function fetchApprovals(businessId: string): Promise<unknown[]> {
  try {
    const res = await fetch(`${BASE}/approvals/${businessId}`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.approvals || [];
  } catch { return []; }
}

export async function fetchReports(businessId: string): Promise<unknown[]> {
  try {
    const res = await fetch(`${BASE}/reports/${businessId}`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.reports || [];
  } catch { return []; }
}

export async function approveItem(approvalId: string): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/approvals/${approvalId}/approve`, { method: "POST" });
    return res.ok;
  } catch { return false; }
}

export async function rejectItem(approvalId: string): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/approvals/${approvalId}/reject`, { method: "POST" });
    return res.ok;
  } catch { return false; }
}

export async function healthCheck(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`);
    const data = await res.json();
    return data.status === "ok";
  } catch { return false; }
}
