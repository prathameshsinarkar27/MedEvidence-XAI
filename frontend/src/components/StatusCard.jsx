const TONES = {
  ok: "bg-emerald-100 text-emerald-800 ring-emerald-600/20",
  warn: "bg-amber-100 text-amber-800 ring-amber-600/20",
  bad: "bg-rose-100 text-rose-800 ring-rose-600/20",
  idle: "bg-slate-100 text-slate-700 ring-slate-500/20",
};

export default function StatusCard({ title, badge, tone = "idle", children }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}>
          {badge}
        </span>
      </div>
      <div className="mt-3 space-y-1 text-sm text-slate-600">{children}</div>
    </section>
  );
}
