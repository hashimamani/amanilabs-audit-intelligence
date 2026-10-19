const STYLES: Record<string, string> = {
  Open: "bg-sky-50 text-sky-700 ring-sky-600/20",
  "In Progress": "bg-amber-50 text-amber-700 ring-amber-600/20",
  Closed: "bg-slate-100 text-slate-600 ring-slate-500/20",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[status] ?? STYLES.Closed}`}>
      {status}
    </span>
  );
}
