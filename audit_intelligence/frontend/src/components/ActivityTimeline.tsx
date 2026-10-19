import type { ActivityEntry } from "../api/types";
import { formatDateTime } from "../lib/format";

function describe(entry: ActivityEntry): string {
  const d = entry.detail as Record<string, string | boolean | null | undefined>;
  switch (entry.action) {
    case "status_changed":
      return `changed status from ${d.from} to ${d.to}${d.bulk ? " (bulk update)" : ""}`;
    case "assigned":
      return d.to ? `assigned the case to ${d.to}` : "cleared the assignee";
    case "outcome_set":
      return d.to ? `recorded the outcome "${d.to}"` : "cleared the outcome";
    case "note_added":
      return `added a note: "${d.note}"`;
    default:
      return entry.action;
  }
}

export function ActivityTimeline({ entries }: { entries: ActivityEntry[] }) {
  if (entries.length === 0) return <p className="text-sm text-slate-400">No activity yet — the case has not been touched since it was opened.</p>;
  return (
    <ol className="space-y-3">
      {entries.map((entry, i) => (
        <li key={`${entry.at}-${i}`} className="relative border-l-2 border-slate-200 pl-4 text-sm">
          <span className="absolute top-1.5 -left-[5px] h-2 w-2 rounded-full bg-slate-400" />
          <span className="font-medium text-slate-900">{entry.actor_name}</span>{" "}
          <span className="text-slate-700">{describe(entry)}</span>
          <div className="text-xs text-slate-400">{formatDateTime(entry.at)}</div>
        </li>
      ))}
    </ol>
  );
}
