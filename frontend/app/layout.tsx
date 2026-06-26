import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Link from "next/link";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Automiqo OS",
  description: "AI Operating System for Local Service Businesses",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-[#0A0A0F] text-white`}>
        <nav className="bg-[#1A1A2E] border-b border-[#2A2A4E] px-6 py-3 flex items-center gap-6">
          <span className="font-bold text-blue-400 mr-4">Automiqo OS</span>
          <Link href="/dashboard" className="text-sm text-gray-300 hover:text-white transition-colors">Dashboard</Link>
          <Link href="/chat" className="text-sm text-gray-300 hover:text-white transition-colors">CEO Chat</Link>
          <Link href="/approvals" className="text-sm text-gray-300 hover:text-white transition-colors">Approvals</Link>
          <Link href="/reports" className="text-sm text-gray-300 hover:text-white transition-colors">Reports</Link>
        </nav>
        {children}
      </body>
    </html>
  );
}
