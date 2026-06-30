"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, MessagesSquare, Activity, Bot,
  CheckSquare, FileText, SlidersHorizontal, Users,
} from "@/components/icons";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/team-members", label: "Team Members", icon: Users },
  { href: "/team", label: "Team Chat", icon: MessagesSquare },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/chat", label: "CEO AI", icon: Bot },
  { href: "/approvals", label: "Approvals", icon: CheckSquare },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/modules", label: "Modules", icon: SlidersHorizontal },
];

export default function Sidebar() {
  const pathname = usePathname() || "";
  return (
    <aside className="hidden md:flex w-64 shrink-0 flex-col gap-1 border-r border-slate-200 bg-white/70 backdrop-blur-sm px-4 py-6">
      <Link href="/" className="mb-6 flex items-center gap-2.5 px-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-teal-400 text-white font-bold shadow-md">A</span>
        <div className="leading-tight">
          <p className="font-semibold text-slate-800">Automiqo</p>
          <p className="text-[11px] text-slate-400">AI Business OS</p>
        </div>
      </Link>

      <nav className="flex flex-col gap-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || (href !== "/" && pathname.startsWith(href + "/"));
          return (
            <Link key={href} href={href} className={`nav-link ${active ? "nav-link-active" : ""}`}>
              <Icon className="h-[18px] w-[18px]" strokeWidth={2} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto rounded-2xl bg-gradient-to-br from-indigo-50 to-teal-50 p-4 text-xs text-slate-500">
        <p className="font-medium text-slate-700">Your AI team is on</p>
        <p className="mt-1 leading-relaxed">Working 24/7 — planning, deciding, and flagging what needs you.</p>
      </div>
    </aside>
  );
}
