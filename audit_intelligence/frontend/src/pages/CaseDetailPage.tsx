import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, Download, MessageCircle, Send } from "lucide-react";
import { ApiError, askCaseQuestion, getCase, getCaseActivity, listCases, updateCase } from "../api/client";
import { STATUSES, type ActivityEntry, type CaseDetail } from "../api/types";
import { ActivityTimeline } from "../components/ActivityTimeline";
import { RuleLabel } from "../components/RuleLabel";
import { SeverityBadge } from "../components/SeverityBadge";
import { downloadCsv } from "../lib/csv";
import { formatDateTime } from "../lib/format";
import { CardSkeleton } from "../ui/Skeleton";
import { useToast } from "../ui/Toast";

export function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const caseId = id ?? "";
  const navigate = useNavigate();
  const toast = useToast();

  const [caseData, setCaseData] = useState<CaseDetail | null>(null);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [neighbours, setNeighbours] = useState<{ prev: string | null; next: string | null; index: number; total: number } | null>(null);
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

  const loadActivity = useCallback(() => {
    getCaseActivity(caseId).then(setActivity).catch(() => setActivity([]));
  }, [caseId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setQaHistory([]);
    getCase(caseId)
      .then(async (c) => {
        if (cancelled) return;
        setCaseData(c);
        setAuditorDraft(c.assigned_auditor ?? "");
        setOutcomeDraft(c.outcome ?? "");
        loadActivity();
        const siblings = await listCases({ runId: c.run_id, limit: 500 });
        if (cancelled) return;
        const index = siblings.findIndex((s) => s.id === c.id);
        setNeighbours({
          prev: index > 0 ? siblings[index - 1].id : null,
          next: index >= 0 && index < siblings.length - 1 ? siblings[index + 1].id : null,
          index,
          total: siblings.length,
        });
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load the case.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [caseId, loadActivity]);

  async function save(patch: Parameters<typeof updateCase>[1], done: string) {
    setSaving(true);
    try {
      const updated = await updateCase(caseId, patch);
      setCaseData(updated);
      setAuditorDraft(updated.assigned_auditor ?? "");
      setOutcomeDraft(updated.outcome ?? "");
      loadActivity();
      toast.success(done);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Update failed.");
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
    const header = ["Case", "Subject", "Subject ID", "Rule", "Rule ID", "Flag Severity", "Explanation", "Evidence Label", "Evidence Value", "Triggered At"];
    const rows: string[][] = [];
    for (const flag of caseData.flags) {
      const base = [caseData.case_ref, caseData.subject_name, caseData.subject_id, flag.rule_name, flag.rule_id, flag.severity, flag.explanation];
      if (flag.evidence.length === 0) rows.push([...base, "", "", flag.triggered_at ?? ""]);
      else for (const e of flag.evidence) rows.push([...base, e.label, e.value, flag.triggered_at ?? ""]);
    }
    downloadCsv(`${caseData.case_ref}-evidence.csv`, [header, ...rows]);
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <CardSkeleton lines={1} />
        <CardSkeleton />
        <CardSkeleton />
      </div>
    );
  }
  if (error || !caseData) return <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error ?? "Case not found."}</div>;

  const detailsDirty = auditorDraft !== (caseData.assigned_auditor ?? "") || outcomeDraft !== (caseData.outcome ?? "");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Link to="/cases" className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700">
          <ArrowLeft className="h-4 w-4" />
          Back to cases
        </Link>
        {neighbours && neighbours.index >= 0 && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <button
              onClick={() => neighbours.prev && navigate(`/cases/${neighbours.prev}`)}
              disabled={!neighbours.prev}
              aria-label="Previous case"
              className="rounded p-1 hover:bg-slate-100 disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span>
              {neighbours.index + 1} of {neighbours.total}
            </span>
            <button
              onClick={() => neighbours.next && navigate(`/cases/${neighbours.next}`)}
              disabled={!neighbours.next}
              aria-label="Next case"
              className="rounded p-1 hover:bg-slate-100 disabled:opacity-40"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{caseData.case_ref}</h1>
          <p className="mt-1 text-sm text-slate-500">
            {caseData.subject_type === "member" ? "Member" : "Employee"}: <span className="font-medium text-slate-700">{caseData.subject_name}</span> ({caseData.subject_id})
            {" · "}opened {formatDateTime(caseData.created_at)}
          </p>
          <div className="mt-2 flex flex-wrap gap-1">
            {caseData.triggered_rules.map((r) => (
              <RuleLabel key={r} id={r} />
            ))}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={handleExportEvidence} className="btn-secondary flex items-center gap-2">
            <Download className="h-4 w-4" />
            Evidence (CSV)
          </button>
          <SeverityBadge severity={caseData.severity} />
          <span className="text-2xl font-semibold text-indigo-600">{caseData.risk_score.toFixed(1)}</span>
        </div>
      </div>

      <section className="card grid grid-cols-1 gap-4 p-6 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end">
        <div>
          <label className="text-xs font-medium text-slate-500">Status</label>
          <select
            value={caseData.status}
            disabled={saving}
            aria-label="Status"
            onChange={(e) => void save({ status: e.target.value }, `Status set to ${e.target.value}.`)}
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
          <input value={auditorDraft} aria-label="Assigned auditor" onChange={(e) => setAuditorDraft(e.target.value)} className="input-field mt-1 block w-full" />
        </div>
        <div>
          <label className="text-xs font-medium text-slate-500">Outcome</label>
          <input value={outcomeDraft} aria-label="Outcome" onChange={(e) => setOutcomeDraft(e.target.value)} className="input-field mt-1 block w-full" />
        </div>
        <button
          onClick={() => void save({ assigned_auditor: auditorDraft, outcome: outcomeDraft }, "Case details saved.")}
          disabled={saving || !detailsDirty}
          className="btn-primary py-1.5"
        >
          Save
        </button>
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="card p-6">
          <h2 className="text-base font-semibold text-slate-900">Timeline</h2>
          <ol className="mt-4 space-y-4">
            {caseData.timeline.map((event, i) => (
              <li key={i} className="relative border-l-2 border-slate-200 pl-4">
                <span className="absolute top-1 -left-[5px] h-2 w-2 rounded-full bg-indigo-500" />
                <div className="text-xs text-slate-400">{formatDateTime(event.timestamp)}</div>
                <div className="text-sm font-medium text-slate-900">{event.rule_name}</div>
                <div className="text-sm text-slate-600">{event.explanation}</div>
              </li>
            ))}
          </ol>
        </section>

        <section className="card p-6">
          <h2 className="text-base font-semibold text-slate-900">Activity</h2>
          <div className="mt-4">
            <ActivityTimeline entries={activity} />
          </div>
        </section>
      </div>

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">Evidence</h2>
        <dl className="mt-4 divide-y divide-slate-100">
          {caseData.evidence.map((e, i) => (
            <div key={i} className="flex justify-between gap-4 py-2 text-sm">
              <dt className="text-slate-500">{e.label}</dt>
              <dd className="text-right font-medium text-slate-900">{e.value}</dd>
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
          {caseData.notes.length === 0 && <li className="text-sm text-slate-400">No notes yet.</li>}
          {caseData.notes.map((note, i) => (
            <li key={i} className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700">
              {note}
            </li>
          ))}
        </ul>
        <div className="mt-3 flex gap-2">
          <input
            value={noteDraft}
            aria-label="New note"
            onChange={(e) => setNoteDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && noteDraft.trim()) {
                void save({ add_note: noteDraft.trim() }, "Note added.");
                setNoteDraft("");
              }
            }}
            placeholder="Add a note..."
            className="input-field flex-1"
          />
          <button
            onClick={() => {
              void save({ add_note: noteDraft.trim() }, "Note added.");
              setNoteDraft("");
            }}
            disabled={saving || !noteDraft.trim()}
            className="btn-primary py-1.5"
          >
            Add
          </button>
        </div>
      </section>

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">Constituent flags ({caseData.flags.length})</h2>
        <div className="mt-4 space-y-4">
          {caseData.flags.map((flag, i) => (
            <div key={i} className="rounded-md border border-slate-200 p-4">
              <div className="flex items-center justify-between">
                <RuleLabel id={flag.rule_id} />
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
          Answers are grounded strictly in this case's evidence, flags, timeline and notes above — the AI won't speculate beyond what's recorded here.
        </p>
        {qaHistory.length > 0 && (
          <div className="mt-4 space-y-4">
            {qaHistory.map((qa, i) => (
              <div key={i} className="space-y-1">
                <p className="text-sm font-medium text-slate-900">{qa.question}</p>
                <p className="whitespace-pre-wrap rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700">{qa.answer}</p>
              </div>
            ))}
          </div>
        )}
        {askError && <div className="mt-3 rounded-md bg-red-50 p-3 text-sm text-red-800">{askError}</div>}
        <div className="mt-4 flex gap-2">
          <input
            value={questionDraft}
            aria-label="Question about this case"
            onChange={(e) => setQuestionDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void handleAsk()}
            placeholder="e.g. Why was this flagged as Critical?"
            className="input-field flex-1"
          />
          <button onClick={() => void handleAsk()} disabled={asking || !questionDraft.trim()} className="btn-primary flex items-center gap-2 py-1.5">
            <Send className="h-4 w-4" />
            {asking ? "Asking..." : "Ask"}
          </button>
        </div>
      </section>
    </div>
  );
}
