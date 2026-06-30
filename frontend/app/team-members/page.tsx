"use client";
import { useEffect, useRef, useState } from "react";
import { Send, X, MessagesSquare } from "@/components/icons";
import {
  getTeamMembers, getMemberDM, askMember, setModule,
  type Roster, type TeamMember, type TeamMessage,
} from "@/lib/api";

const BUSINESS_ID = process.env.NEXT_PUBLIC_BUSINESS_ID || "00000000-0000-0000-0000-000000000001";

const PALETTE = [
  "from-indigo-500 to-violet-500", "from-teal-500 to-emerald-500",
  "from-rose-500 to-orange-500", "from-sky-500 to-cyan-500",
  "from-amber-500 to-yellow-500", "from-fuchsia-500 to-pink-500",
];
function colorFor(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % PALETTE.length;
  return PALETTE[h];
}
function initials(name: string) {
  const p = name.trim().split(/\s+/);
  return ((p[0]?.[0] || "") + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase();
}

function Toggle({ on, onClick, disabled }: { on: boolean; onClick: () => void; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${on ? "bg-indigo-500" : "bg-slate-200"}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? "left-[22px]" : "left-0.5"}`} />
    </button>
  );
}

export default function TeamMembersPage() {
  const [roster, setRoster] = useState<Roster | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [chatMember, setChatMember] = useState<TeamMember | null>(null);

  const load = () => getTeamMembers(BUSINESS_ID).then((r) => { setRoster(r); setLoading(false); });
  useEffect(() => { load(); }, []);

  async function toggle(m: TeamMember) {
    setSaving(m.key);
    const [dept, manager] = m.key.includes(".") ? m.key.split(".") : [m.key, null];
    await setModule(BUSINESS_ID, dept, manager, !m.enabled);
    await load();
    setSaving(null);
  }

  // Group members by department (roster is ordered head-then-managers).
  const groups: { dept: string; label: string; members: TeamMember[] }[] = [];
  roster?.members.forEach((m) => {
    const g = groups.find((x) => x.dept === m.dept);
    if (g) g.members.push(m);
    else groups.push({ dept: m.dept, label: m.role === "executive" ? "Executive" : m.dept_label, members: [m] });
  });

  return (
    <div className="mx-auto max-w-6xl p-6 lg:p-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-800">Your Team</h1>
          <p className="mt-1 text-sm text-slate-500">Everyone working on your business. Chat with anyone, or switch them on/off.</p>
        </div>
        {roster && (
          <div className="flex gap-2">
            <span className="pill bg-indigo-50 text-indigo-600">{roster.active} active</span>
            <span className="pill bg-slate-100 text-slate-400">{roster.total} total</span>
          </div>
        )}
      </div>

      {loading && <p className="py-12 text-center text-sm text-slate-400">Loading your team…</p>}

      <div className="space-y-7">
        {groups.map((g) => (
          <div key={g.dept}>
            <h2 className="mb-3 px-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{g.label}</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {g.members.map((m) => (
                <div key={m.key} className={`soft-card p-4 transition ${m.enabled ? "" : "opacity-60"}`}>
                  <div className="flex items-start gap-3">
                    <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${colorFor(m.name)} text-xs font-bold text-white shadow-sm`}>
                      {initials(m.name)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="truncate font-semibold text-slate-800">{m.name}</p>
                        {m.role === "executive" && <span className="pill bg-amber-50 text-amber-500">lead</span>}
                        {m.role === "department" && <span className="pill bg-indigo-50 text-indigo-500">head</span>}
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-slate-500">{m.description}</p>
                    </div>
                  </div>
                  <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
                    <button onClick={() => setChatMember(m)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-indigo-50 hover:text-indigo-600">
                      <MessagesSquare className="h-3.5 w-3.5" /> Chat
                    </button>
                    {m.can_toggle ? (
                      <Toggle on={m.enabled} disabled={saving === m.key} onClick={() => toggle(m)} />
                    ) : (
                      <span className="text-[11px] font-medium text-emerald-500">always on</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {chatMember && <ChatPanel member={chatMember} onClose={() => setChatMember(null)} />}
    </div>
  );
}

function ChatPanel({ member, onClose }: { member: TeamMember; onClose: () => void }) {
  const [messages, setMessages] = useState<TeamMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getMemberDM(BUSINESS_ID, member.key).then((m) => { setMessages(m); setLoaded(true); });
  }, [member.key]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setMessages((m) => [...m, { from_agent: "Owner", from_role: "owner", message: text }]);
    setSending(true);
    const reply = await askMember(BUSINESS_ID, member.key, text);
    setMessages((m) => [...m, { from_agent: member.name, message: reply }]);
    setSending(false);
  }

  return (
    <div className="fixed inset-0 z-30 flex justify-end bg-slate-900/20 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-md flex-col bg-white shadow-2xl animate-fadein" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-3">
            <span className={`flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br ${colorFor(member.name)} text-xs font-bold text-white`}>
              {initials(member.name)}
            </span>
            <div>
              <p className="font-semibold text-slate-800">{member.name}</p>
              <p className="text-xs text-slate-400">{member.dept_label}</p>
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
          {loaded && messages.length === 0 && (
            <p className="py-8 text-center text-sm text-slate-400">Say hi to {member.name} — ask them anything about their area.</p>
          )}
          {messages.map((m, i) => {
            const isOwner = m.from_agent === "Owner" || m.from_role === "owner";
            return (
              <div key={i} className={`flex ${isOwner ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[82%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
                  isOwner ? "bg-gradient-to-br from-indigo-500 to-violet-500 text-white" : "bg-slate-50 text-slate-700"
                }`}>
                  {m.message}
                </div>
              </div>
            );
          })}
          {sending && <p className="text-xs text-slate-400">{member.name} is thinking…</p>}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-slate-100 p-3">
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-1.5 focus-within:border-indigo-300">
            <input value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder={`Message ${member.name}…`}
              className="flex-1 bg-transparent py-2 text-sm text-slate-700 outline-none placeholder:text-slate-400" />
            <button onClick={send} disabled={sending || !input.trim()}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500 text-white transition hover:bg-indigo-600 disabled:opacity-40">
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
