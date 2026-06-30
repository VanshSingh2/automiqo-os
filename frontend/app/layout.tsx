import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Sidebar from "@/components/Sidebar";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Automiqo OS",
  description: "AI Operating System for Local Service Businesses",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white/70 px-6 py-3 backdrop-blur-md">
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <span className="flex h-2 w-2 rounded-full bg-emerald-400 animate-pulse-soft" />
                AI team active
              </div>
              <div className="flex items-center gap-3">
                <span className="hidden sm:block text-sm text-slate-400">Owner</span>
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-teal-400 text-sm font-semibold text-white">O</span>
              </div>
            </header>
            <main className="flex-1">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
