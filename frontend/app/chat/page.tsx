"use client";
import { useState, useRef, useEffect } from "react";
import { Send, Bot } from "@/components/icons";
import { streamChat } from "@/lib/api";

type Msg = { role: "user" | "assistant"; content: string; error?: boolean };

const DEMO_BUSINESS_ID = process.env.NEXT_PUBLIC_BUSINESS_ID || "00000000-0000-0000-0000-000000000001";

const QUICK_ACTIONS = [
  "How is my business today?",
  "Who are my at-risk customers?",
  "What's my revenue this week?",
  "Any missed calls to recover?",
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Msg[]>([
    { role: "assistant", content: "Hi! I'm your CEO AI. I can analyze your business, spot opportunities, and turn them into action plans. What would you like to know?" },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  async function send(text?: string) {
    const userMsg = (text || input).trim();
    if (!userMsg || streaming) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: userMsg }]);
    setStreaming(true);

    let aiContent = "";
    setMessages((m) => [...m, { role: "assistant", content: "▋" }]);

    await streamChat(
      DEMO_BUSINESS_ID,
      userMsg,
      (chunk) => {
        aiContent += chunk;
        setMessages((m) => [...m.slice(0, -1), { role: "assistant", content: aiContent + " ▋" }]);
      },
      () => {
        setMessages((m) => [...m.slice(0, -1), { role: "assistant", content: aiContent || "Done." }]);
        setStreaming(false);
      },
      (error) => {
        setMessages((m) => [...m.slice(0, -1), { role: "assistant", content: `Error: ${error}. Make sure the backend is running and OPENAI_API_KEY is set in .env`, error: true }]);
        setStreaming(false);
      }
    );
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-57px)] max-w-3xl flex-col p-6 lg:p-8">
      <div className="mb-4 flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-teal-400 text-white shadow-sm">
          <Bot className="h-5 w-5" />
        </span>
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-800">CEO AI</h1>
          <p className="text-xs text-slate-400">Strategic analysis and action plans for your business</p>
        </div>
      </div>

      <div className="soft-card flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-6">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${
                m.role === "user" ? "bg-gradient-to-br from-indigo-500 to-violet-500 text-white"
                : m.error ? "border border-rose-200 bg-rose-50 text-rose-600"
                : "bg-slate-50 text-slate-700"
              }`}>
                {m.content}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-slate-100 p-3">
          <div className="mb-3 flex flex-wrap gap-2">
            {QUICK_ACTIONS.map((q) => (
              <button key={q} onClick={() => send(q)} disabled={streaming}
                className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-500 transition hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-50">
                {q}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-1.5 focus-within:border-indigo-300">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
              placeholder="Ask your CEO AI anything…"
              disabled={streaming}
              className="flex-1 bg-transparent py-2 text-sm text-slate-700 outline-none placeholder:text-slate-400"
            />
            <button onClick={() => send()} disabled={streaming || !input.trim()}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500 text-white transition hover:bg-indigo-600 disabled:opacity-40">
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
