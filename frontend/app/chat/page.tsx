"use client";
import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { streamChat } from "@/lib/api";

type Msg = { role: "user" | "assistant"; content: string; error?: boolean };

const DEMO_BUSINESS_ID = "00000000-0000-0000-0000-000000000001";

const QUICK_ACTIONS = [
  "How is my business today?",
  "Who are my at-risk customers?",
  "What's my revenue this week?",
  "Any missed calls to recover?",
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Msg[]>([
    { role: "assistant", content: "Hi! I'm your CEO AI. I can analyze your business, identify opportunities, and create action plans. What would you like to know?" },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
        setMessages((m) => [...m.slice(0, -1), { role: "assistant", content: `Error: ${error}. Make sure ANTHROPIC_API_KEY is set.`, error: true }]);
        setStreaming(false);
      }
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-49px)]">
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
              m.role === "user"
                ? "bg-blue-600 text-white"
                : m.error
                ? "bg-red-900/30 border border-red-500/30 text-red-300"
                : "bg-[#1A1A2E] border border-[#2A2A4E] text-gray-100"
            }`}>
              {m.content}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="px-4 pb-2">
        <div className="flex gap-2 flex-wrap mb-3">
          {QUICK_ACTIONS.map((q) => (
            <button
              key={q}
              onClick={() => send(q)}
              disabled={streaming}
              className="text-xs px-3 py-1.5 rounded-full bg-[#1A1A2E] border border-[#2A2A4E] text-gray-400 hover:text-white hover:border-blue-500 transition-colors disabled:opacity-50"
            >
              {q}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
            placeholder="Ask your CEO AI anything about your business..."
            className="bg-[#1A1A2E] border-[#2A2A4E] text-white placeholder:text-gray-600 focus:border-blue-500"
            disabled={streaming}
          />
          <Button
            onClick={() => send()}
            disabled={streaming || !input.trim()}
            className="bg-blue-600 hover:bg-blue-700 text-white"
          >
            {streaming ? "..." : "Send"}
          </Button>
        </div>
      </div>
    </div>
  );
}
