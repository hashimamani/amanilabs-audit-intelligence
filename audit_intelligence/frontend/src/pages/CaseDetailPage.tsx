import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Download, MessageCircle, Send } from "lucide-react";
import { ApiError, askCaseQuestion, getCase, updateCase } from "../api/client";
import type { CaseDetail } from "../api/types";
import { SeverityBadge } from "../components/SeverityBadge";
import { downloadCsv } from "../lib/csv";

const STATUSES = ["Open", "In Progress", "Closed"];

function formatTimestamp(ts: string | null): string {
  if (!ts) return "Undated";
  return new Date(ts).toLocaleString();
}

export function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const caseId = Number(id);

  const [caseData, setCaseData] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [auditorDraft, setAuditorDraft] = useState("");
  const [outcomeDraft, setOutcomeDraft] = useState("");
  const [qaHistory, setQaHistory] = useState<{ question: string; answer: string }[]>([]);
  const [questionDraft, setQuestionDraft] = useState("");
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    getCase(caseId)
      .then((c) => {
        setCaseData(c);
        setAuditorDraft(c.assigned_auditor ?? "");
        setOutcomeDraft(c.outcome ?? "");
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load case."))
      .finally(() => setLoading(false));
  }

  useEffect(load, [caseId]);

  async function handleStatusChange(status: string) {
    setSaving(true);
    try {
      const updated = await updateCase(caseId, { status });
      setCaseData(updated);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveDetails() {
    setSaving(true);
    try {
      const updated = await updateCase(caseId, {
        assigned_auditor: auditorDraft,
        outcome: outcomeDraft,
      });
      setCaseData(updated);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddNote() {
    if (!noteDraft.trim()) return;
    setSaving(true);
    try {
      const updated = await updateCase(caseId, { add_note: noteDraft.trim() });
      setCaseData(updated);
      setNoteDraft("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to add note.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAsk() {
    if (!questionDraft.trim()) return;
    setAsking(true);
    setAskError(null);
    try {
      const result = await askCaseQuestion(caseId, questionDraft.trim());
      setQaHistory((h) => [...h, { question: questionDraft.trim(), answer: result.answer }]);
      setQuestionDraft("");
    } catch (e) {
      setAskError(e instanceof ApiError ? e.message : "Failed to get an answer.");
    } finally {
      setAsking(false);
    }
  }

  function handleExportEvidence() {
    if (!caseData) return;
    const header = [
      "Case",
      "Subject",
      "Subject ID",
      "Rule",
      "Rule ID",
      "Flag Severity",
      "Explanation",
      "Evidence Label",
      "Evidence Value",
      "Triggered At",
    ];
    const rows: string[][] = [];
    for (const flag of caseData.flags) {
      const base = [
        caseData.case_ref,
        caseData.subject_name,
        caseData.subject_id,
        flag.rule_name,
        flag.rule_id,
        flag.severity,
        flag.explanation,
      ];
      if (flag.evidence.length === 0) {
        rows.push([...base, "", "", flag.triggered_at ?? ""]);
      } else {
        for (const e of flag.evidence) {
          rows.push([...base, e.label, e.value, flag.triggered_at ?? ""]);
        }
      }
    }
    downloadCsv(`${caseData.case_ref}-evidence.csv`, [header, ...rows]);
  }

  if (loading) return <p className="text-sm text-slate-500">Loading...</p>;
  if (error && !caseData)
    return <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</div>;
  if (!caseData) return null;

  return (
    <div className="space-y-6">
      <Link
        to="/cases"
        className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to cases
      </Link>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{caseData.case_ref}</h1>
          <p className="mt-1 text-sm text-slate-500">
            {caseData.subject_type === "member" ? "Member" : "Employee"}:{" "}
            <span className="font-medium text-slate-700">{caseData.subject_name}</span>{" "}
            ({caseData.subject_id})
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={handleExportEvidence} className="btn-secondary flex items-center gap-2">
            <Download className="h-4 w-4" />
            Download evidence (CSV)
          </button>
          <SeverityBadge severity={caseData.severity} />
          <span className="text-2xl font-semibold text-indigo-600">
            {caseData.risk_score.toFixed(1)}
          </span>
        </div>
      </div>

      {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</div>}

      <section className="card grid grid-cols-1 gap-4 p-6 sm:grid-cols-3">
        <div>
          <label className="text-xs font-medium text-slate-500">Status</label>
          <select
            value={caseData.status}
            disabled={saving}
            onChange={(e) => handleStatusChange(e.target.value)}
            className="input-field mt-1 block w-full"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs font-medium text-slate-500">Assigned auditor</label>
          <input
            value={auditorDraft}
            onChange={(e) => setAuditorDraft(e.target.value)}
            onBlur={handleSaveDetails}
            className="input-field mt-1 block w-full"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-slate-500">Outcome</label>
          <input
            value={outcomeDraft}
            onChange={(e) => setOutcomeDraft(e.target.value)}
            onBlur={handleSaveDetails}
            className="input-field mt-1 block w-full"
          />
        </div>
      </section>

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">Timeline</h2>
        <ol className="mt-4 space-y-4">
          {caseData.timeline.map((event, i) => (
            <li key={i} className="relative border-l-2 border-slate-200 pl-4">
              <span className="absolute top-1 -left-[5px] h-2 w-2 rounded-full bg-indigo-500" />
              <div className="text-xs text-slate-400">{formatTimestamp(event.timestamp)}</div>
              <div className="text-sm font-medium text-slate-900">{event.rule_name}</div>
              <div className="text-sm text-slate-600">{event.explanation}</div>
            </li>
          ))}
        </ol>
      </section>

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">Evidence</h2>
        <dl className="mt-4 divide-y divide-slate-100">
          {caseData.evidence.map((e, i) => (
            <div key={i} className="flex justify-between py-2 text-sm">
              <dt className="text-slate-500">{e.label}</dt>
              <dd className="font-medium text-slate-900">{e.value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">Recommended actions</h2>
        <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-slate-700">
          {caseData.recommended_actions.map((action, i) => (
            <li key={i}>{action}</li>
          ))}
        </ul>
      </section>

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">Notes</h2>
        <ul className="mt-3 space-y-2">
          {caseData.notes.length === 0 && (
            <li className="text-sm text-slate-400">No notes yet.</li>
          )}
          {caseData.notes.map((note, i) => (
            <li key={i} className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700">
              {note}
            </li>
          ))}
        </ul>
        <div className="mt-3 flex gap-2">
          <input
            value={noteDraft}
            onChange={(e) => setNoteDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAddNote()}
            placeholder="Add a note..."
            className="input-field flex-1"
          />
          <button
            onClick={handleAddNote}
            disabled={saving || !noteDraft.trim()}
            className="btn-primary py-1.5"
          >
            Add
          </button>
        </div>
      </section>

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">
          Constituent flags ({caseData.flags.length})
        </h2>
        <div className="mt-4 space-y-4">
          {caseData.flags.map((flag, i) => (
            <div key={i} className="rounded-md border border-slate-200 p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-900">
                  {flag.rule_name} ({flag.rule_id})
                </span>
                <SeverityBadge severity={flag.severity} />
              </div>
              <p className="mt-1 text-sm text-slate-600">{flag.explanation}</p>
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
                {flag.evidence.map((e, j) => (
                  <div key={j}>
                    <dt className="text-slate-400">{e.label}</dt>
                    <dd className="font-medium text-slate-700">{e.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      </section>

      <section className="card p-6">
        <h2 className="flex items-center gap-2 text-base font-semibold text-slate-900">
          <MessageCircle className="h-4 w-4 text-indigo-600" />
          Ask about this case
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          Answers are grounded strictly in this case's evidence, flags, timeline, and notes above —
          the AI won't speculate beyond what's recorded here.
        </p>

        {qaHistory.length > 0 && (
          <div className="mt-4 space-y-4">
            {qaHistory.map((qa, i) => (
              <div key={i} className="space-y-1">
                <p className="text-sm font-medium text-slate-900">{qa.question}</p>
                <p className="whitespace-pre-wrap rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700">
                  {qa.answer}
                </p>
              </div>
            ))}
          </div>
        )}

        {askError && (
          <div className="mt-3 rounded-md bg-red-50 p-3 text-sm text-red-800">{askError}</div>
        )}

        <div className="mt-4 flex gap-2">
          <input
            value={questionDraft}
            onChange={(e) => setQuestionDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAsk()}
            placeholder="e.g. Why was this flagged as Critical?"
            className="input-field flex-1"
          />
          <button
            onClick={handleAsk}
            disabled={asking || !questionDraft.trim()}
            className="btn-primary flex items-center gap-2 py-1.5"
          >
            <Send className="h-4 w-4" />
            {asking ? "Asking..." : "Ask"}
          </button>
        </div>
      </section>
    </div>
  );
}
