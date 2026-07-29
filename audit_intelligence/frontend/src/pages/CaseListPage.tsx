import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, bulkUpdateCaseStatus, listCases } from "../api/client";
import type { CaseSummary, Severity } from "../api/types";
import { SeverityBadge } from "../components/SeverityBadge";
import { downloadCsv } from "../lib/csv";

const SEVERITIES: Severity[] = ["Critical", "High", "Medium", "Low"];
const STATUSES = ["Open", "In Progress", "Closed"];

export function CaseListPage() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const severity = searchParams.get("severity") ?? "";
  const status = searchParams.get("status") ?? "";
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkStatus, setBulkStatus] = useState<string>(STATUSES[0]);
  const [applyingBulk, setApplyingBulk] = useState(false);

  function setFilter(key: "severity" | "status", value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next);
  }

  function loadCases() {
    let cancelled = false;
    setLoading(true);
    listCases({
      severity: severity || undefined,
      status: status || undefined,
      limit: 200,
    })
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

  useEffect(loadCases, [severity, status]);

  function toggleSelected(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected((prev) => (prev.size === cases.length ? new Set() : new Set(cases.map((c) => c.id))));
  }

  async function handleApplyBulkStatus() {
    setApplyingBulk(true);
    try {
      await bulkUpdateCaseStatus(Array.from(selected), bulkStatus);
      loadCases();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Bulk update failed.");
    } finally {
      setApplyingBulk(false);
    }
  }

  function handleExport() {
    const header = [
      "Case",
      "Subject",
      "Subject ID",
      "Rules",
      "Flags",
      "Severity",
      "Risk",
      "Status",
      "Created",
      "Updated",
    ];
    const rows = cases.map((c) => [
      c.case_ref,
      c.subject_name,
      c.subject_id,
      c.triggered_rules.join("; "),
      String(c.flag_count),
      c.severity,
      c.risk_score.toFixed(1),
      c.status,
      c.created_at,
      c.updated_at,
    ]);
    downloadCsv(`cases-${new Date().toISOString().slice(0, 10)}.csv`, [header, ...rows]);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Cases</h1>
          <p className="mt-1 text-sm text-slate-500">
            Ranked by risk score, from the most recent analysis run.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleExport}
            disabled={cases.length === 0}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Export CSV
          </button>
          <Link
            to="/upload"
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            Run new analysis
          </Link>
        </div>
      </div>

      <div className="flex gap-3">
        <select
          value={severity}
          onChange={(e) => setFilter("severity", e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        >
          <option value="">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          value={status}
          onChange={(e) => setFilter("status", e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {selected.size > 0 && (
        <div className="flex items-center gap-3 rounded-md border border-slate-200 bg-slate-50 px-4 py-2 text-sm">
          <span className="font-medium text-slate-700">{selected.size} selected</span>
          <select
            value={bulkStatus}
            onChange={(e) => setBulkStatus(e.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            onClick={handleApplyBulkStatus}
            disabled={applyingBulk}
            className="rounded-md bg-slate-900 px-3 py-1 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            Apply
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="text-slate-500 hover:text-slate-700"
          >
            Clear
          </button>
        </div>
      )}

      {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</div>}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : cases.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
          No cases yet.{" "}
          <Link to="/upload" className="font-medium text-slate-900 underline">
            Run an analysis
          </Link>{" "}
          to get started.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="w-8 px-4 py-2">
                  <input
                    type="checkbox"
                    checked={selected.size === cases.length && cases.length > 0}
                    onChange={toggleSelectAll}
                    aria-label="Select all cases"
                  />
                </th>
                <th className="px-4 py-2 text-left font-medium text-slate-500">Case</th>
                <th className="px-4 py-2 text-left font-medium text-slate-500">Subject</th>
                <th className="px-4 py-2 text-left font-medium text-slate-500">Rules</th>
                <th className="px-4 py-2 text-left font-medium text-slate-500">Flags</th>
                <th className="px-4 py-2 text-left font-medium text-slate-500">Severity</th>
                <th className="px-4 py-2 text-left font-medium text-slate-500">Risk</th>
                <th className="px-4 py-2 text-left font-medium text-slate-500">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {cases.map((c) => (
                <tr key={c.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selected.has(c.id)}
                      onChange={() => toggleSelected(c.id)}
                      aria-label={`Select ${c.case_ref}`}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <Link to={`/cases/${c.id}`} className="font-medium text-slate-900 hover:underline">
                      {c.case_ref}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-slate-700">
                    {c.subject_name}{" "}
                    <span className="text-slate-400">({c.subject_id})</span>
                  </td>
                  <td className="px-4 py-3 text-slate-500">{c.triggered_rules.join(", ")}</td>
                  <td className="px-4 py-3 text-slate-500">{c.flag_count}</td>
                  <td className="px-4 py-3">
                    <SeverityBadge severity={c.severity} />
                  </td>
                  <td className="px-4 py-3 font-medium text-slate-900">{c.risk_score.toFixed(1)}</td>
                  <td className="px-4 py-3 text-slate-500">{c.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
