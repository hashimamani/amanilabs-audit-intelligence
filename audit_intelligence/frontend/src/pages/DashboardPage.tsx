import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CircleDot, Flag as FlagIcon, FolderOpen, Send, Sparkles } from "lucide-react";
import { ApiError, listCases, queryAnalytics } from "../api/client";
import { SEVERITIES, type AnalyticsQueryResult, type CaseSummary, type Severity } from "../api/types";
import { BarChart } from "../components/BarChart";
import { LineChart } from "../components/LineChart";
import { RuleLabel } from "../components/RuleLabel";
import { SeverityBadge } from "../components/SeverityBadge";
import { useRun } from "../contexts/RunContext";
import { delta, formatDateTime } from "../lib/format";
import { CardSkeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { JobProgress } from "../ui/JobProgress";

const SEVERITY_BAR: Record<Severity, string> = {
  Critical: "bg-red-500",
  High: "bg-orange-500",
  Medium: "bg-amber-500",
  Low: "bg-slate-400",
};

function Delta({ current, previous }: { current: number; previous: number | undefined }) {
  const d = delta(current, previous);
  if (!d) return <span className="text-xs text-slate-400">first run</span>;
  const tone = d.tone === "flat" ? "text-slate-400" : d.tone === "up" ? "text-red-600" : "text-emerald-600";
  return <span className={`text-xs ${tone}`}>{d.text}</span>;
}

function Tile({ label, value, previous, icon: Icon }: { label: string; value: number; previous?: number; icon: typeof FlagIcon }) {
  return (
    <div className="card flex items-start justify-between p-4">
      <div>
        <div className="text-xs font-medium text-slate-500">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
        <Delta current={value} previous={previous} />
      </div>
      <Icon className="h-5 w-5 text-indigo-500" />
    </div>
  );
}

export function DashboardPage() {
  const { selectedRun: run, previousRun, loading: runsLoading } = useRun();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [chart, setChart] = useState<AnalyticsQueryResult | null>(null);
  const [loadingChart, setLoadingChart] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);

  useEffect(() => {
    if (!run) {
      setCases([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    listCases({ runId: run.id, limit: 500 })
      .then((rows) => {
        if (!cancelled) setCases(rows);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load the dashboard.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [run]);

  async function askForChart() {
    if (!question.trim()) return;
    setLoadingChart(true);
    setChartError(null);
    try {
      setChart(await queryAnalytics(question.trim()));
    } catch (e) {
      setChartError(e instanceof ApiError ? e.message : "Failed to generate a chart.");
    } finally {
      setLoadingChart(false);
    }
  }

  if (runsLoading || (loading && run)) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} lines={1} />)}
        </div>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      </div>
    );
  }
  if (error) return <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</div>;
  if (!run) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
        <EmptyState
          title="No analysis has been run yet"
          description="Run the engine on the bundled demo data or upload a SACCO's export to see cases here."
          action={<Link to="/upload" className="btn-primary">Run an analysis</Link>}
        />
      </div>
    );
  }

  const severityCount = (s: Severity, r = run) => r.severity_counts[s] ?? 0;
  const criticalHigh = severityCount("Critical") + severityCount("High");
  const prevCriticalHigh = previousRun ? severityCount("Critical", previousRun) + severityCount("High", previousRun) : undefined;
  const openCount = cases.filter((c) => c.status === "Open").length;
  const statusCounts = ["Open", "In Progress", "Closed"].map((s) => ({ status: s, count: cases.filter((c) => c.status === s).length }));
  const maxSeverity = Math.max(1, ...SEVERITIES.map((s) => severityCount(s)));
  const topRules = Object.entries(run.rule_counts).sort((a, b) => b[1] - a[1]);
  const topCases = cases.slice(0, 5);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          Run #{run.id} · {run.dataset_id === "default" ? "demo dataset" : `dataset ${run.dataset_id}`} · {formatDateTime(run.completed_at ?? run.created_at)}
          {previousRun && ` · compared with run #${previousRun.id}`}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Tile label="Flags raised" value={run.flag_count} previous={previousRun?.flag_count} icon={FlagIcon} />
        <Tile label="Cases opened" value={run.case_count} previous={previousRun?.case_count} icon={FolderOpen} />
        <Tile label="Critical + High" value={criticalHigh} previous={prevCriticalHigh} icon={AlertTriangle} />
        <Tile label="Still open" value={openCount} icon={CircleDot} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="card p-6">
          <h2 className="text-base font-semibold text-slate-900">Cases by severity</h2>
          <ul className="mt-4 space-y-3">
            {SEVERITIES.map((severity) => {
              const count = severityCount(severity);
              return (
                <li key={severity}>
                  <Link to={`/cases?severity=${severity}`} className="flex items-center gap-3 text-sm hover:opacity-80">
                    <span className="w-20 shrink-0">
                      <SeverityBadge severity={severity} />
                    </span>
                    <span className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                      <span className={`block h-full rounded-full ${SEVERITY_BAR[severity]}`} style={{ width: `${(count / maxSeverity) * 100}%` }} />
                    </span>
                    <span className="w-8 shrink-0 text-right font-medium text-slate-900">{count}</span>
                    <span className="w-24 shrink-0 text-right">
                      <Delta current={count} previous={previousRun ? severityCount(severity, previousRun) : undefined} />
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="card p-6">
          <h2 className="text-base font-semibold text-slate-900">Cases by status</h2>
          <ul className="mt-4 space-y-3">
            {statusCounts.map(({ status, count }) => (
              <li key={status}>
                <Link to={`/cases?status=${status}`} className="flex items-center justify-between text-sm hover:underline">
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
                <li key={rule} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <Link to="/rules" className="min-w-0 truncate hover:underline">
                    <RuleLabel id={rule} />
                  </Link>
                  <span className="flex shrink-0 items-center gap-3">
                    <Delta current={count} previous={previousRun?.rule_counts[rule]} />
                    <span className="font-medium text-slate-900">{count} case{count === 1 ? "" : "s"}</span>
                  </span>
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
                    {c.case_ref} · {c.subject_name}
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

      <section className="card p-6">
        <h2 className="flex items-center gap-2 text-base font-semibold text-slate-900">
          <Sparkles className="h-4 w-4 text-indigo-600" />
          Ask for a chart
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          e.g. "average risk score for R001 cases" or "trend of Critical cases" — the AI writes and runs real code against your case data; it never states a number it hasn't computed.
        </p>
        <div className="mt-4 flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void askForChart()}
            placeholder="Ask a question..."
            aria-label="Chart question"
            className="input-field flex-1"
          />
          <button onClick={() => void askForChart()} disabled={loadingChart || !question.trim()} className="btn-primary flex items-center gap-2 py-1.5">
            <Send className="h-4 w-4" />
            Ask
          </button>
        </div>
        {loadingChart && (
          <div className="mt-3">
            <JobProgress label="Analysing your cases" hints={["Handing the case data to the sandbox…", "Writing and running pandas code…", "Checking the result…", "Almost there — this can take up to a minute."]} />
          </div>
        )}
        {chartError && <div className="mt-3 rounded-md bg-red-50 p-3 text-sm text-red-800">{chartError}</div>}
        {chart && !loadingChart && (
          <div className="mt-4">
            <h3 className="text-sm font-medium text-slate-900">{chart.title}</h3>
            <div className="mt-3">{chart.chart_type === "line" ? <LineChart data={chart.data} /> : <BarChart data={chart.data} />}</div>
          </div>
        )}
      </section>
    </div>
  );
}
