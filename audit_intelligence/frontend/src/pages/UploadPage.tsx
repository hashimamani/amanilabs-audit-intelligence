import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, PlayCircle, UploadCloud } from "lucide-react";
import { ApiError, listDatasets, runAnalysis, uploadDataset } from "../api/client";
import { REQUIRED_UPLOAD_FILES, type RunSummary, type UploadResult } from "../api/types";
import { useRun } from "../contexts/RunContext";
import { formatDateTime } from "../lib/format";
import { JobProgress } from "../ui/JobProgress";
import { useToast } from "../ui/Toast";

const RUN_HINTS = ["Loading the export…", "Running the nine rules…", "Grouping flags into cases…", "Saving the cases…"];

export function UploadPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { refreshRuns, selectRun } = useRun();
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [datasets, setDatasets] = useState<UploadResult[]>([]);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const missingFiles = REQUIRED_UPLOAD_FILES.filter((name) => !selectedFiles.some((f) => f.name === name));

  function loadDatasets() {
    listDatasets().then(setDatasets).catch(() => setDatasets([]));
  }
  useEffect(loadDatasets, []);

  async function handleUpload() {
    setUploading(true);
    setError(null);
    try {
      const result = await uploadDataset(selectedFiles);
      setUploadResult(result);
      loadDatasets();
      if (result.status === "ready") toast.success("Dataset uploaded and validated.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function handleRunAnalysis(datasetId?: string) {
    setAnalyzing(datasetId ?? "default");
    setError(null);
    setRunResult(null);
    try {
      const result = await runAnalysis(datasetId);
      setRunResult(result);
      await refreshRuns();
      selectRun(result.id);
      toast.success(`Run #${result.id} finished: ${result.case_count} cases.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Analysis failed.");
    } finally {
      setAnalyzing(null);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Upload & Analyze</h1>
        <p className="mt-1 text-sm text-slate-500">Upload a SACCO's exported data and run the fraud detection engine, or try it against the bundled demo dataset.</p>
      </div>

      {analyzing && <JobProgress label={analyzing === "default" ? "Analysing the demo dataset" : `Analysing dataset ${analyzing}`} hints={RUN_HINTS} />}
      {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</div>}

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">Try the demo dataset</h2>
        <p className="mt-1 text-sm text-slate-500">A synthetic SACCO — 1,500 members, a year of transactions — with known injected fraud scenarios. No upload needed.</p>
        <button onClick={() => void handleRunAnalysis(undefined)} disabled={analyzing !== null} className="btn-primary mt-4 flex items-center gap-2">
          <PlayCircle className="h-4 w-4" />
          Run analysis on demo dataset
        </button>
      </section>

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">Upload your own data</h2>
        <p className="mt-1 text-sm text-slate-500">
          Select all 8 CSV exports at once. File names must match exactly; the columns each file needs are checked before anything runs, and you'll be told exactly what's missing.
        </p>
        <ul className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
          {REQUIRED_UPLOAD_FILES.map((name) => {
            const selected = selectedFiles.some((f) => f.name === name);
            return (
              <li key={name} className={`flex items-center gap-1 rounded px-2 py-1 ${selected ? "bg-emerald-50 text-emerald-700" : "bg-slate-100"}`}>
                {selected && <CheckCircle2 className="h-3 w-3" />}
                {name}
              </li>
            );
          })}
        </ul>
        <input
          type="file"
          accept=".csv"
          multiple
          aria-label="CSV files"
          onChange={(e) => {
            setSelectedFiles(Array.from(e.target.files ?? []));
            setUploadResult(null);
            setRunResult(null);
            setError(null);
          }}
          className="mt-4 block text-sm text-slate-600 file:mr-4 file:rounded-md file:border-0 file:bg-slate-100 file:px-4 file:py-2 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200"
        />
        {selectedFiles.length > 0 && missingFiles.length > 0 && <p className="mt-2 text-sm text-amber-700">Missing: {missingFiles.join(", ")}</p>}
        <button onClick={() => void handleUpload()} disabled={uploading || selectedFiles.length === 0 || missingFiles.length > 0} className="btn-primary mt-4 flex items-center gap-2">
          <UploadCloud className="h-4 w-4" />
          {uploading ? "Uploading…" : "Upload dataset"}
        </button>

        {uploadResult && uploadResult.status !== "ready" && (
          <div className="mt-4 rounded-md bg-amber-50 p-3 text-sm text-amber-800">
            <p className="font-medium">The upload can't be analysed yet:</p>
            <ul className="mt-1 list-disc pl-5">
              {uploadResult.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </div>
        )}
        {uploadResult && uploadResult.status === "ready" && (
          <div className="mt-4 flex items-center gap-3 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
            Uploaded (dataset {uploadResult.dataset_id}).
            <button
              onClick={() => void handleRunAnalysis(uploadResult.dataset_id)}
              disabled={analyzing !== null}
              className="rounded-md bg-emerald-700 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
            >
              Run analysis on this dataset
            </button>
          </div>
        )}
      </section>

      {datasets.length > 0 && (
        <section className="card p-6">
          <h2 className="text-base font-semibold text-slate-900">Uploaded datasets</h2>
          <table className="mt-3 min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-medium text-slate-500">
                <th className="py-1 pr-4">Dataset</th>
                <th className="py-1 pr-4">Uploaded</th>
                <th className="py-1 pr-4">Status</th>
                <th className="py-1"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {datasets.map((d) => (
                <tr key={d.dataset_id}>
                  <td className="py-2 pr-4 font-mono text-xs text-slate-700">{d.dataset_id}</td>
                  <td className="py-2 pr-4 text-slate-500">{formatDateTime(d.created_at)}</td>
                  <td className="py-2 pr-4">
                    <span className={d.status === "ready" ? "text-emerald-700" : d.status === "invalid" ? "text-red-700" : "text-slate-500"}>{d.status}</span>
                    {d.errors.length > 0 && <span className="ml-2 text-xs text-slate-400">({d.errors.length} problem{d.errors.length === 1 ? "" : "s"})</span>}
                  </td>
                  <td className="py-2 text-right">
                    {d.status === "ready" && (
                      <button onClick={() => void handleRunAnalysis(d.dataset_id)} disabled={analyzing !== null} className="text-xs font-medium text-indigo-700 hover:underline disabled:opacity-50">
                        Run analysis
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {runResult && (
        <section className="card p-6">
          <h2 className="text-base font-semibold text-slate-900">Analysis complete</h2>
          <dl className="mt-3 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-slate-500">Run</dt>
              <dd className="font-medium text-slate-900">#{runResult.id}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Flags raised</dt>
              <dd className="font-medium text-slate-900">{runResult.flag_count}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Cases created</dt>
              <dd className="font-medium text-slate-900">{runResult.case_count}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Critical + High</dt>
              <dd className="font-medium text-slate-900">{(runResult.severity_counts.Critical ?? 0) + (runResult.severity_counts.High ?? 0)}</dd>
            </div>
          </dl>
          <button onClick={() => navigate("/cases")} className="btn-primary mt-4">
            View cases
          </button>
        </section>
      )}
    </div>
  );
}
