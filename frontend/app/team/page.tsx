"use client";
import { useEffect, useRef, useState } from "react";
import { Send } from "@/components/icons";
import { getTeamChat, postOwnerMessage, type TeamMessage } from "@/lib/api";

const BUSINESS_ID = process.env.NEXT_PUBLIC_BUSINESS_ID || "00000000-0000-0000-0000-000000000001";

// Stable color per agent name
const PALETTE = [
  "from-indigo-500 to-violet-500", "from-teal-500 to-emerald-500",
  "from-rose-500 to-orange-500", "from-sky-500 to-cyan-500",
  "from-amber-500 to-yellow-500", "from-fuchsia-500 to-pink-500",
  "from-blue-500 to-indigo-500", "from-green-500 to-lime-500",
];
function colorFor(name: string) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % PALETTE.length;
  return PALETTE[h];
}
function initials(name: string) {
  const p = name.trim().split(/\s+/);
  return (p[0]?.[0] || "") + (p.length > 1 ? p[p.length - 1][0] : "");
}
const fmtTime = (s?: string) => {
  if (!s) return "";
  const d = new Date(s);
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

export default function TeamPage() {
  const [messages, setMessages] = useState<TeamMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const load = () => getTeamChat(BUSINESS_ID).then((m) => { setMessages(m); setLoading(false); });
  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    setMessages((m) => [...m, { from_agent: "Owner", from_role: "owner", message: text }]);
    await postOwnerMessage(BUSINESS_ID, text);
    setTimeout(load, 400);
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-57px)] max-w-4xl flex-col p-6 lg:p-8">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-800">Team Chat</h1>
        <p className="mt-1 text-sm text-slate-500">Your CEO, department heads, and managers — talking it out in real time.</p>
      </div>

      <div className="soft-card flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex-1 space-y-1 overflow-y-auto px-4 py-5 sm:px-6">
          {loading && <p className="py-10 text-center text-sm text-slate-400">Loading conversation…</p>}
          {!loading && messages.length === 0 && (
            <p className="py-10 text-center text-sm text-slate-400">
              Quiet for now. Your team posts here during daily standups and whenever they coordinate.
            </p>
          )}
          {messages.map((m, i) => {
            const isOwner = (m.from_role === "owner") || m.from_agent === "Owner";
            const prev = messages[i - 1];
            const grouped = prev && prev.from_agent === m.from_agent;
            return (
              <div key={i} className={`flex animate-fadein gap-3 ${isOwner ? "flex-row-reverse" : ""} ${grouped ? "mt-0.5" : "mt-3"}`}>
                <div className={`h-9 w-9 shrink-0 ${grouped ? "opacity-0" : ""}`}>
                  {!grouped && (
                    <span className={`flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br ${isOwner ? "from-slate-600 to-slate-800" : colorFor(m.from_agent)} text-xs font-bold uppercase text-white shadow-sm`}>
                      {initials(m.from_agent)}
                    </span>
                  )}
                </div>
                <div className={`max-w-[78%] ${isOwner ? "items-end text-right" : ""}`}>
                  {!grouped && (
                    <div className={`mb-1 flex items-center gap-2 ${isOwner ? "justify-end" : ""}`}>
                      <span className="text-xs font-semibold text-slate-700">{m.from_agent}</span>
                      {m.from_role && m.from_role !== "owner" && (
                        <span className="pill bg-slate-100 text-slate-400">{m.from_role}</span>
                      )}
                      <span className="text-[11px] text-slate-300">{fmtTime(m.created_at)}</span>
                    </div>
                  )}
                  <div className={`inline-block rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
                    isOwner ? "bg-gradient-to-br from-indigo-500 to-violet-500 text-white"
                    : m.urgency === "high" ? "border border-rose-200 bg-rose-50 text-rose-700"
                    : m.category === "alert" ? "border border-amber-200 bg-amber-50 text-amber-800"
                    : "bg-slate-50 text-slate-700"
                  }`}>
                    {m.message}
                  </div>
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-slate-100 p-3">
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-1.5 focus-within:border-indigo-300">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Message your team…"
              className="flex-1 bg-transparent py-2 text-sm text-slate-700 outline-none placeholder:text-slate-400"
            />
            <button onClick={send} disabled={!input.trim()}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500 text-white transition hover:bg-indigo-600 disabled:opacity-40">
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
