import type { ChartDatapoint } from "../api/types";

export function BarChart({ data }: { data: ChartDatapoint[] }) {
  if (data.length === 0) return <p className="text-sm text-slate-400">No data.</p>;
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <ul className="space-y-3">
      {data.map((d) => (
        <li key={d.label} className="flex items-center gap-3 text-sm">
          <span className="w-32 shrink-0 truncate text-slate-700" title={d.label}>
            {d.label}
          </span>
          <span className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
            <span
              className="block h-full rounded-full bg-indigo-500"
              style={{ width: `${(d.value / max) * 100}%` }}
            />
          </span>
          <span className="w-10 shrink-0 text-right font-medium text-slate-900">{d.value}</span>
        </li>
      ))}
    </ul>
  );
}
