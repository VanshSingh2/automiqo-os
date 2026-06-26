import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <h1 className="text-4xl font-bold text-white mb-4">Automiqo OS</h1>
      <p className="text-gray-400 mb-8 text-center max-w-md">
        AI-powered operating system for local service businesses.
        CEO AI + 19 department agents + 42 automation workflows.
      </p>
      <div className="flex gap-4">
        <Link href="/dashboard" className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg transition-colors">
          Dashboard
        </Link>
        <Link href="/chat" className="bg-[#1A1A2E] border border-[#2A2A4E] hover:border-blue-500 text-white px-6 py-3 rounded-lg transition-colors">
          Talk to CEO AI
        </Link>
      </div>
    </main>
  );
}
