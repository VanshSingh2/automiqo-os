import Link from "next/link";
import { LayoutDashboard, MessagesSquare } from "@/components/icons";

export default function Home() {
  return (
    <main className="flex min-h-[calc(100vh-57px)] flex-col items-center justify-center p-10 text-center">
      <span className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-teal-400 text-2xl font-bold text-white shadow-lg">A</span>
      <h1 className="text-4xl font-semibold tracking-tight text-slate-800">Automiqo OS</h1>
      <p className="mb-8 mt-3 max-w-md text-slate-500">
        Your AI operating system for local service businesses — a full virtual team
        that plans, decides, and runs the day-to-day, 24/7.
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Link href="/dashboard" className="inline-flex items-center gap-2 rounded-xl bg-indigo-500 px-6 py-3 font-medium text-white shadow-md transition hover:bg-indigo-600">
          <LayoutDashboard className="h-4 w-4" /> Open Dashboard
        </Link>
        <Link href="/team" className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-6 py-3 font-medium text-slate-700 shadow-sm transition hover:border-indigo-300">
          <MessagesSquare className="h-4 w-4" /> See Team Chat
        </Link>
      </div>
    </main>
  );
}
