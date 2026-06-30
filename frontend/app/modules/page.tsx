"use client";
import { useEffect, useState } from "react";
import { getModules, setModule, type ModuleSummary } from "@/lib/api";

const BUSINESS_ID = process.env.NEXT_PUBLIC_BUSINESS_ID || "00000000-0000-0000-0000-000000000001";

function Toggle({ on, onClick, disabled }: { on: boolean; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${on ? "bg-indigo-500" : "bg-slate-200"}`}
      aria-pressed={on}
    >
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? "left-[22px]" : "left-0.5"}`} />
    </button>
  );
}

export default function ModulesPage() {
  const [data, setData] = useState<ModuleSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    getModules(BUSINESS_ID).then((d) => { setData(d); setLoading(false); });
  }, []);

  async function toggle(department: string, manager: string | null, next: boolean) {
    const key = manager ? `${department}.${manager}` : department;
    setSaving(key);
    const updated = await setModule(BUSINESS_ID, department, manager, next);
    if (updated) setData(updated);
    setSaving(null);
  }

  return (
    <div className="mx-auto max-w-4xl p-6 lg:p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-800">Modules</h1>
        <p className="mt-1 text-sm text-slate-500">
          Turn on only what this business needs. Disabled departments and managers won't run or spend resources.
        </p>
        {data && (
          <span className="pill mt-3 bg-indigo-50 text-indigo-600">Profile: {data.profile}</span>
        )}
      </div>

      {loading && <p className="py-12 text-center text-sm text-slate-400">Loading modules…</p>}
      {!loading && !data && (
        <div className="soft-card p-6 text-sm text-slate-500">
          Couldn't load modules. Make sure the backend is running and the business exists.
        </div>
      )}

      <div className="space-y-4">
        {data?.departments.map((d) => (
          <div key={d.key} className={`soft-card p-5 transition ${d.enabled ? "" : "opacity-70"}`}>
            <div className="flex items-center justify-between">
              <div>
                <p className="font-semibold text-slate-800">{d.label}</p>
                <p className="mt-0.5 text-xs text-slate-400">
                  {d.enabled ? `${d.managers.filter((m) => m.enabled).length} of ${d.managers.length} managers active` : "Department off"}
                </p>
              </div>
              <Toggle on={d.enabled} disabled={saving === d.key} onClick={() => toggle(d.key, null, !d.enabled)} />
            </div>

            {d.enabled && d.managers.length > 0 && (
              <div className="mt-4 grid gap-2 border-t border-slate-100 pt-4 sm:grid-cols-2">
                {d.managers.map((m) => (
                  <div key={m.key} className="flex items-center justify-between rounded-xl bg-slate-50/70 px-3 py-2.5">
                    <span className={`text-sm ${m.enabled ? "text-slate-700" : "text-slate-400"}`}>{m.label}</span>
                    <Toggle on={m.enabled} disabled={saving === `${d.key}.${m.key}`} onClick={() => toggle(d.key, m.key, !m.enabled)} />
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
