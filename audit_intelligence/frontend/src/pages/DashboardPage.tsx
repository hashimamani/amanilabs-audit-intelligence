import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CircleDot, Flag as FlagIcon, FolderOpen, PlayCircle } from "lucide-react";
import { ApiError, listCases, listRuns } from "../api/client";
import type { CaseSummary, RunSummary, Severity } from "../api/types";
import { SeverityBadge } from "../components/SeverityBadge";

const SEVERITIES: Severity[] = ["Critical", "High", "Medium", "Low"];
const STATUSES = ["Open", "In Progress", "Closed"];

const SEVERITY_BAR: Record<Severity, string> = {
  Critical: "bg-red-500",
  High: "bg-orange-500",
  Medium: "bg-amber-500",
  Low: "bg-slate-400",
};

function formatTimestamp(ts: string): string {
  return new Date(ts).toLocaleString();
}

export function DashboardPage() {
  const [run, setRun] = useState<RunSummary | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listRuns()
      .then(async (runs) => {
        const latest = runs[0] ?? null;
        if (cancelled) return;
        setRun(latest);
        if (!latest) {
          setCases([]);
          return;
        }
        // Dashboard-scale aggregation only: pulls the API's max page size
        // (200) and aggregates client-side rather than adding a dedicated
        // backend stats endpoint - fine at this project's case volumes
        // (dozens, not thousands), revisit if that changes.
        const runCases = await listCases({ runId: latest.id, limit: 200 });
        if (!cancelled) setCases(runCases);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load dashboard.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <p className="text-sm text-slate-500">Loading...</p>;
  if (error) return <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</div>;

  if (!run) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
        <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
          No analysis runs yet.{" "}
          <Link to="/upload" className="font-medium text-slate-900 underline">
            Run an analysis
          </Link>{" "}
          to get started.
        </div>
      </div>
    );
  }

  const severityCounts = SEVERITIES.map((s) => ({
    severity: s,
    count: cases.filter((c) => c.severity === s).length,
  }));
  const statusCounts = STATUSES.map((s) => ({
    status: s,
    count: cases.filter((c) => c.status === s).length,
  }));
  const ruleCounts = new Map<string, number>();
  for (const c of cases) {
    for (const rule of c.triggered_rules) {
      ruleCounts.set(rule, (ruleCounts.get(rule) ?? 0) + 1);
    }
  }
  const topRules = [...ruleCounts.entries()].sort((a, b) => b[1] - a[1]);
  const topCases = [...cases].sort((a, b) => b.risk_score - a.risk_score).slice(0, 5);
  const maxSeverityCount = Math.max(1, ...severityCounts.map((s) => s.count));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
          <p className="mt-1 text-sm text-slate-500">
            Latest run: {run.dataset_id} &middot; {formatTimestamp(run.created_at)}
          </p>
        </div>
        <Link to="/upload" className="btn-primary flex items-center gap-2">
          <PlayCircle className="h-4 w-4" />
          Run new analysis
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="card flex items-start justify-between p-4">
          <div>
            <div className="text-xs font-medium text-slate-500">Flags raised</div>
            <div className="mt-1 text-2xl font-semibold text-slate-900">{run.flag_count}</div>
          </div>
          <FlagIcon className="h-5 w-5 text-indigo-500" />
        </div>
        <div className="card flex items-start justify-between p-4">
          <div>
            <div className="text-xs font-medium text-slate-500">Cases opened</div>
            <div className="mt-1 text-2xl font-semibold text-slate-900">{run.case_count}</div>
          </div>
          <FolderOpen className="h-5 w-5 text-indigo-500" />
        </div>
        <div className="card flex items-start justify-between p-4">
          <div>
            <div className="text-xs font-medium text-slate-500">Critical + High</div>
            <div className="mt-1 text-2xl font-semibold text-slate-900">
              {severityCounts[0].count + severityCounts[1].count}
            </div>
          </div>
          <AlertTriangle className="h-5 w-5 text-indigo-500" />
        </div>
        <div className="card flex items-start justify-between p-4">
          <div>
            <div className="text-xs font-medium text-slate-500">Still open</div>
            <div className="mt-1 text-2xl font-semibold text-slate-900">
              {statusCounts[0].count}
            </div>
          </div>
          <CircleDot className="h-5 w-5 text-indigo-500" />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="card p-6">
          <h2 className="text-base font-semibold text-slate-900">Cases by severity</h2>
          <ul className="mt-4 space-y-3">
            {severityCounts.map(({ severity, count }) => (
              <li key={severity}>
                <Link
                  to={`/cases?severity=${severity}`}
                  className="flex items-center gap-3 text-sm hover:opacity-80"
                >
                  <span className="w-16 shrink-0">
                    <SeverityBadge severity={severity} />
                  </span>
                  <span className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <span
                      className={`block h-full rounded-full ${SEVERITY_BAR[severity]}`}
                      style={{ width: `${(count / maxSeverityCount) * 100}%` }}
                    />
                  </span>
                  <span className="w-6 shrink-0 text-right font-medium text-slate-900">
                    {count}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section className="card p-6">
          <h2 className="text-base font-semibold text-slate-900">Cases by status</h2>
          <ul className="mt-4 space-y-3">
            {statusCounts.map(({ status, count }) => (
              <li key={status}>
                <Link
                  to={`/cases?status=${status}`}
                  className="flex items-center justify-between text-sm hover:underline"
                >
                  <span className="text-slate-700">{status}</span>
                  <span className="font-medium text-slate-900">{count}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="card p-6">
          <h2 className="text-base font-semibold text-slate-900">Most-triggered rules</h2>
          {topRules.length === 0 ? (
            <p className="mt-4 text-sm text-slate-400">No rules triggered.</p>
          ) : (
            <ul className="mt-4 divide-y divide-slate-100">
              {topRules.map(([rule, count]) => (
                <li key={rule} className="flex items-center justify-between py-2 text-sm">
                  <span className="text-slate-700">{rule}</span>
                  <span className="font-medium text-slate-900">{count} case{count === 1 ? "" : "s"}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card p-6">
          <h2 className="text-base font-semibold text-slate-900">Highest-risk cases</h2>
          {topCases.length === 0 ? (
            <p className="mt-4 text-sm text-slate-400">No cases yet.</p>
          ) : (
            <ul className="mt-4 divide-y divide-slate-100">
              {topCases.map((c) => (
                <li key={c.id} className="flex items-center justify-between py-2 text-sm">
                  <Link to={`/cases/${c.id}`} className="text-slate-700 hover:underline">
                    {c.case_ref} &middot; {c.subject_name}
                  </Link>
                  <span className="flex items-center gap-2">
                    <SeverityBadge severity={c.severity} />
                    <span className="font-medium text-slate-900">{c.risk_score.toFixed(1)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
