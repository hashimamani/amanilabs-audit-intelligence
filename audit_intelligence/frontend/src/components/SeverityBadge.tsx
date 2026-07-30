import type { Severity } from "../api/types";

const STYLES: Record<Severity, string> = {
  Critical: "bg-red-100 text-red-800 ring-red-600/20",
  High: "bg-orange-100 text-orange-800 ring-orange-600/20",
  Medium: "bg-amber-100 text-amber-800 ring-amber-600/20",
  Low: "bg-slate-100 text-slate-700 ring-slate-600/20",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[severity]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {severity}
    </span>
  );
}
