import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Download, FileText, X } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import { ApiError, bulkUpdateCaseStatus, generateReport, listCases } from "../api/client";
import { SEVERITIES, STATUSES, type CaseSummary, type ReportResult } from "../api/types";
import { RuleLabel } from "../components/RuleLabel";
import { SeverityBadge } from "../components/SeverityBadge";
import { StatusPill } from "../components/StatusPill";
import { useRules } from "../contexts/RulesContext";
import { useRun } from "../contexts/RunContext";
import { downloadCsv, downloadText } from "../lib/csv";
import { daysSince, formatDate } from "../lib/format";
import { DataTable } from "../ui/DataTable";
import { EmptyState } from "../ui/EmptyState";
import { JobProgress } from "../ui/JobProgress";
import { TableSkeleton } from "../ui/Skeleton";
import { useToast } from "../ui/Toast";

export function CaseListPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { ruleName } = useRules();
  const { selectedRun: run, loading: runsLoading } = useRun();
  const [searchParams, setSearchParams] = useSearchParams();
  const severity = searchParams.get("severity") ?? "";
  const status = searchParams.get("status") ?? "";
  const rule = searchParams.get("rule") ?? "";

  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkStatus, setBulkStatus] = useState<string>(STATUSES[0]);
  const [applyingBulk, setApplyingBulk] = useState(false);
  const [report, setReport] = useState<ReportResult | null>(null);
  const [generatingReport, setGeneratingReport] = useState(false);

  function setFilter(key: "severity" | "status" | "rule", value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next);
  }

  function loadCases() {
    if (!run) {
      setCases([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    listCases({ runId: run.id, limit: 500 })
      .then((result) => {
        if (cancelled) return;
        setCases(result);
        setSelected(new Set());
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load cases.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }

  useEffect(loadCases, [run]);

  const visible = useMemo(
    () =>
      cases.filter(
        (c) => (!severity || c.severity === severity) && (!status || c.status === status) && (!rule || c.triggered_rules.includes(rule)),
      ),
    [cases, severity, status, rule],
  );

  const columns = useMemo<ColumnDef<CaseSummary, unknown>[]>(
    () => [
      {
        id: "case",
        accessorKey: "case_ref",
        header: "Case",
        cell: ({ row }) => (
          <Link to={`/cases/${row.original.id}`} onClick={(e) => e.stopPropagation()} className="font-medium text-slate-900 hover:text-indigo-600 hover:underline">
            {row.original.case_ref}
          </Link>
        ),
      },
      {
        id: "subject",
        accessorFn: (c) => `${c.subject_name} ${c.subject_id}`,
        header: "Subject",
        cell: ({ row }) => (
          <span className="text-slate-700">
            {row.original.subject_name} <span className="text-slate-400">({row.original.subject_id})</span>
          </span>
        ),
      },
      {
        id: "rules",
        accessorFn: (c) => c.triggered_rules.map((r) => `${r} ${ruleName(r)}`).join(" "),
        header: "Rules",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="flex flex-wrap gap-1">
            {row.original.triggered_rules.map((r) => (
              <RuleLabel key={r} id={r} short />
            ))}
          </span>
        ),
      },
      { id: "flags", accessorKey: "flag_count", header: "Flags", cell: ({ getValue }) => <span className="text-slate-500">{getValue<number>()}</span> },
      {
        id: "severity",
        accessorFn: (c) => SEVERITIES.indexOf(c.severity),
        header: "Severity",
        cell: ({ row }) => <SeverityBadge severity={row.original.severity} />,
      },
      { id: "risk", accessorKey: "risk_score", header: "Risk", cell: ({ getValue }) => <span className="font-medium text-slate-900">{getValue<number>().toFixed(1)}</span> },
      { id: "status", accessorKey: "status", header: "Status", cell: ({ getValue }) => <StatusPill status={getValue<string>()} /> },
      {
        id: "age",
        accessorFn: (c) => daysSince(c.created_at),
        header: "Age",
        cell: ({ getValue, row }) => (
          <span className="text-slate-500" title={`Opened ${formatDate(row.original.created_at)}`}>
            {getValue<number>()}d
          </span>
        ),
      },
    ],
    [ruleName],
  );

  async function handleApplyBulkStatus() {
    setApplyingBulk(true);
    try {
      const result = await bulkUpdateCaseStatus(Array.from(selected), bulkStatus);
      toast.success(`${result.updated_count} case${result.updated_count === 1 ? "" : "s"} moved to ${bulkStatus}.`);
      loadCases();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Bulk update failed.");
    } finally {
      setApplyingBulk(false);
    }
  }

  async function handleGenerateReport() {
    setGeneratingReport(true);
    try {
      setReport(await generateReport(selected.size > 0 ? Array.from(selected) : undefined));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Failed to generate the report.");
    } finally {
      setGeneratingReport(false);
    }
  }

  function handleExport() {
    const header = ["Case", "Subject", "Subject ID", "Rules", "Flags", "Severity", "Risk", "Status", "Created", "Updated"];
    const rows = visible.map((c) => [
      c.case_ref,
      c.subject_name,
      c.subject_id,
      c.triggered_rules.map((r) => `${r} ${ruleName(r)}`).join("; "),
      String(c.flag_count),
      c.severity,
      c.risk_score.toFixed(1),
      c.status,
      c.created_at,
      c.updated_at,
    ]);
    downloadCsv(`cases-${new Date().toISOString().slice(0, 10)}.csv`, [header, ...rows]);
  }

  const filterSelect = (label: string, value: string, options: readonly string[], onChange: (v: string) => void, render = (o: string) => o) => (
    <select value={value} aria-label={label} onChange={(e) => onChange(e.target.value)} className="input-field">
      <option value="">{label}</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {render(o)}
        </option>
      ))}
    </select>
  );

  const { rules } = useRules();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Cases</h1>
          <p className="mt-1 text-sm text-slate-500">
            {run ? `Run #${run.id} · ${visible.length} of ${cases.length} cases shown, highest risk first.` : "Ranked by risk score."}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={handleExport} disabled={visible.length === 0} className="btn-secondary flex items-center gap-2">
            <Download className="h-4 w-4" />
            Export CSV
          </button>
          <button onClick={() => void handleGenerateReport()} disabled={generatingReport || cases.length === 0} className="btn-secondary flex items-center gap-2">
            <FileText className="h-4 w-4" />
            {selected.size > 0 ? `Board report (${selected.size} selected)` : "Board report (top Critical+High)"}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        {filterSelect("All severities", severity, SEVERITIES, (v) => setFilter("severity", v))}
        {filterSelect("All statuses", status, STATUSES, (v) => setFilter("status", v))}
        {filterSelect("All rules", rule, rules.map((r) => r.rule_id), (v) => setFilter("rule", v), (id) => `${id} · ${ruleName(id)}`)}
      </div>

      {selected.size > 0 && (
        <div className="flex items-center gap-3 rounded-md border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm">
          <span className="font-medium text-indigo-900">{selected.size} selected</span>
          <select value={bulkStatus} aria-label="Bulk status" onChange={(e) => setBulkStatus(e.target.value)} className="input-field py-1">
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button onClick={() => void handleApplyBulkStatus()} disabled={applyingBulk} className="btn-primary px-3 py-1">
            Apply
          </button>
          <button onClick={() => setSelected(new Set())} className="text-indigo-700 hover:text-indigo-900">
            Clear
          </button>
        </div>
      )}

      {generatingReport && (
        <JobProgress label="Drafting the board report" hints={["Collecting the cases' evidence…", "Writing the report from the evidence only…", "Almost there — up to a minute for twenty cases."]} />
      )}
      {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</div>}

      {runsLoading || loading ? (
        <TableSkeleton />
      ) : !run ? (
        <EmptyState title="No analysis has been run yet" action={<Link to="/upload" className="btn-primary">Run an analysis</Link>} />
      ) : (
        <DataTable
          columns={columns}
          data={visible}
          getRowId={(c) => c.id}
          searchPlaceholder="Search by case, member name or ID…"
          initialSort={[{ id: "risk", desc: true }]}
          selection={{ selected, onChange: setSelected }}
          onRowClick={(c) => navigate(`/cases/${c.id}`)}
          emptyState={<EmptyState title="No cases match these filters" description="Clear a filter or pick another run." />}
        />
      )}

      {report && (
        <section className="card p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-900">
              Fraud audit report ({report.case_count} case{report.case_count === 1 ? "" : "s"})
            </h2>
            <div className="flex items-center gap-3">
              <button
                onClick={() => downloadText(`fraud-audit-report-${new Date().toISOString().slice(0, 10)}.txt`, report.report_text)}
                className="btn-secondary flex items-center gap-2"
              >
                <Download className="h-4 w-4" />
                Download as text
              </button>
              <button onClick={() => setReport(null)} aria-label="Close report" className="text-slate-400 hover:text-slate-600">
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
          <div className="mt-4 max-h-[32rem] overflow-y-auto whitespace-pre-wrap rounded-md bg-slate-50 p-4 text-sm text-slate-700">{report.report_text}</div>
        </section>
      )}
    </div>
  );
}
