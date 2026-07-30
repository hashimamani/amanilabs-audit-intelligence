import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, PlayCircle, UploadCloud } from "lucide-react";
import { ApiError, runAnalysis, uploadDataset } from "../api/client";
import { REQUIRED_UPLOAD_FILES } from "../api/types";
import type { RunSummary, UploadResult } from "../api/types";

export function UploadPage() {
  const navigate = useNavigate();
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [runResult, setRunResult] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const missingFiles = REQUIRED_UPLOAD_FILES.filter(
    (name) => !selectedFiles.some((f) => f.name === name),
  );

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    setSelectedFiles(Array.from(e.target.files ?? []));
    setUploadResult(null);
    setRunResult(null);
    setError(null);
  }

  async function handleUpload() {
    setUploading(true);
    setError(null);
    try {
      const result = await uploadDataset(selectedFiles);
      setUploadResult(result);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function handleRunAnalysis(datasetId?: string) {
    setAnalyzing(true);
    setError(null);
    try {
      const result = await runAnalysis(datasetId);
      setRunResult(result);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Analysis failed.");
    } finally {
      setAnalyzing(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Upload & Analyze</h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload a SACCO's exported data and run the fraud detection engine, or try it
          against the bundled demo dataset.
        </p>
      </div>

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">Try the demo dataset</h2>
        <p className="mt-1 text-sm text-slate-500">
          Runs the engine against a synthetic dataset with known injected fraud
          scenarios, no upload needed.
        </p>
        <button
          onClick={() => handleRunAnalysis(undefined)}
          disabled={analyzing}
          className="btn-primary mt-4 flex items-center gap-2"
        >
          <PlayCircle className="h-4 w-4" />
          {analyzing ? "Running analysis..." : "Run analysis on demo dataset"}
        </button>
      </section>

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">Upload your own data</h2>
        <p className="mt-1 text-sm text-slate-500">
          Select all 8 required CSV exports at once (file names must match exactly):
        </p>
        <ul className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
          {REQUIRED_UPLOAD_FILES.map((name) => {
            const selected = selectedFiles.some((f) => f.name === name);
            return (
              <li
                key={name}
                className={`flex items-center gap-1 rounded px-2 py-1 ${
                  selected ? "bg-emerald-50 text-emerald-700" : "bg-slate-100"
                }`}
              >
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
          onChange={handleFileChange}
          className="mt-4 block text-sm text-slate-600 file:mr-4 file:rounded-md file:border-0 file:bg-slate-100 file:px-4 file:py-2 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200"
        />

        {selectedFiles.length > 0 && missingFiles.length > 0 && (
          <p className="mt-2 text-sm text-amber-700">
            Missing: {missingFiles.join(", ")}
          </p>
        )}

        <button
          onClick={handleUpload}
          disabled={uploading || selectedFiles.length === 0 || missingFiles.length > 0}
          className="btn-primary mt-4 flex items-center gap-2"
        >
          <UploadCloud className="h-4 w-4" />
          {uploading ? "Uploading..." : "Upload dataset"}
        </button>

        {uploadResult && (
          <div className="mt-4 flex items-center gap-3 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
            Uploaded (dataset {uploadResult.dataset_id}).
            <button
              onClick={() => handleRunAnalysis(uploadResult.dataset_id)}
              disabled={analyzing}
              className="rounded-md bg-emerald-700 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
            >
              {analyzing ? "Running..." : "Run analysis on this dataset"}
            </button>
          </div>
        )}
      </section>

      {error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</div>
      )}

      {runResult && (
        <section className="card p-6">
          <h2 className="text-base font-semibold text-slate-900">Analysis complete</h2>
          <dl className="mt-3 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-slate-500">Run ID</dt>
              <dd className="font-medium text-slate-900">{runResult.id}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Flags raised</dt>
              <dd className="font-medium text-slate-900">{runResult.flag_count}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Cases created</dt>
              <dd className="font-medium text-slate-900">{runResult.case_count}</dd>
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
