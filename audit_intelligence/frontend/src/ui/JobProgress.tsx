import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

/**
 * A long operation is a job the backend runs in the background. This shows
 * that something is happening, how long it has been, and what is going on,
 * so a 40-second wait reads as work rather than a hang.
 */
export function JobProgress({ label, hints }: { label: string; hints: string[] }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const hint = hints[Math.min(hints.length - 1, Math.floor(elapsed / 8))];
  return (
    <div role="status" className="flex items-center gap-3 rounded-md border border-indigo-100 bg-indigo-50 px-4 py-3 text-sm text-indigo-900">
      <Loader2 className="h-4 w-4 animate-spin text-indigo-600" />
      <div className="flex-1">
        <div className="font-medium">{label}</div>
        {hint && <div className="text-xs text-indigo-700">{hint}</div>}
      </div>
      <span className="tabular-nums text-xs text-indigo-700">{elapsed}s</span>
    </div>
  );
}
