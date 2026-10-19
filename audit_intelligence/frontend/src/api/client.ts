import type {
  ActivityEntry,
  AnalyticsQueryResult,
  AskCaseResult,
  CaseDetail,
  CaseSummary,
  CaseUpdate,
  DatasetCreateResult,
  Job,
  ReportResult,
  Role,
  RunSummary,
  UploadResult,
  UserInfo,
} from "./types";

const BASE_URL = "/api";

let authToken: string | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  if (!(init?.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${BASE_URL}${path}`, {
    headers,
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response body wasn't JSON, fall back to statusText
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

const POLL_INTERVAL_MS = 1500;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Files go straight to the URL the API hands out (a presigned S3 PUT when
// deployed, the API's own file route locally) - never through a JSON body.
export async function uploadDataset(files: File[]): Promise<UploadResult> {
  const created = await request<DatasetCreateResult>("/datasets", { method: "POST" });
  for (const target of created.uploads) {
    const file = files.find((f) => f.name === target.file);
    if (!file) throw new ApiError(400, `Missing ${target.file}`);
    const url = target.url.startsWith("/") ? `${BASE_URL}${target.url}` : target.url;
    const res = await fetch(url, { method: target.method, body: file, headers: { "Content-Type": "text/csv" } });
    if (!res.ok) throw new ApiError(res.status, `Upload of ${target.file} failed (${res.status})`);
  }
  return request(`/datasets/${created.dataset_id}/finalize`, { method: "POST" });
}

export function getRun(id: number): Promise<RunSummary> {
  return request(`/analysis/runs/${id}`);
}

// Resolves once the run has finished; the engine runs in the background.
export async function runAnalysis(datasetId?: string): Promise<RunSummary> {
  let run = await request<RunSummary>("/analysis/run", {
    method: "POST",
    body: JSON.stringify({ dataset_id: datasetId ?? null }),
  });
  while (run.status === "queued" || run.status === "running") {
    await sleep(POLL_INTERVAL_MS);
    run = await getRun(run.id);
  }
  if (run.status === "failed") throw new ApiError(500, run.error ?? "Analysis failed.");
  return run;
}

export function listRuns(): Promise<RunSummary[]> {
  return request("/analysis/runs");
}

export function getJob<T>(id: string): Promise<Job<T>> {
  return request(`/jobs/${id}`);
}

async function awaitJob<T>(initial: Job<T>): Promise<T> {
  let job = initial;
  while (job.status === "queued" || job.status === "running") {
    await sleep(POLL_INTERVAL_MS);
    job = await getJob<T>(job.id);
  }
  if (job.status === "failed" || job.result === null) {
    throw new ApiError(502, job.error ?? "The job failed.");
  }
  return job.result;
}

export interface ListCasesParams {
  runId?: number;
  status?: string;
  severity?: string;
  minRisk?: number;
  limit?: number;
  offset?: number;
}

export function listCases(params: ListCasesParams = {}): Promise<CaseSummary[]> {
  const query = new URLSearchParams();
  if (params.runId !== undefined) query.set("run_id", String(params.runId));
  if (params.status) query.set("status", params.status);
  if (params.severity) query.set("severity", params.severity);
  if (params.minRisk !== undefined) query.set("min_risk", String(params.minRisk));
  query.set("limit", String(params.limit ?? 50));
  query.set("offset", String(params.offset ?? 0));
  return request(`/cases?${query.toString()}`);
}

export function getCase(id: string): Promise<CaseDetail> {
  return request(`/cases/${id}`);
}

export function updateCase(id: string, payload: CaseUpdate): Promise<CaseDetail> {
  return request(`/cases/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export interface BulkStatusResult {
  updated_count: number;
}

export function getCaseActivity(id: string): Promise<ActivityEntry[]> {
  return request(`/cases/${id}/activity`);
}

export function bulkUpdateCaseStatus(
  caseIds: string[],
  status: string,
): Promise<BulkStatusResult> {
  return request("/cases/bulk-status", {
    method: "PATCH",
    body: JSON.stringify({ case_ids: caseIds, status }),
  });
}

export function askCaseQuestion(caseId: string, question: string): Promise<AskCaseResult> {
  return request(`/cases/${caseId}/ask`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export async function queryAnalytics(question: string): Promise<AnalyticsQueryResult> {
  const job = await request<Job<AnalyticsQueryResult>>("/analytics/query", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
  return awaitJob(job);
}

export async function generateReport(caseIds?: string[]): Promise<ReportResult> {
  const job = await request<Job<ReportResult>>("/reports/generate", {
    method: "POST",
    body: JSON.stringify({ case_ids: caseIds ?? null }),
  });
  return awaitJob(job);
}

export interface LoginResult {
  access_token: string;
  user: UserInfo;
}

export function login(email: string, password: string): Promise<LoginResult> {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function getMe(): Promise<UserInfo> {
  return request("/auth/me");
}

export function listUsers(): Promise<UserInfo[]> {
  return request("/users");
}

export interface UserCreate {
  email: string;
  name: string;
  password?: string;
  role: Role;
}

export function createUser(payload: UserCreate): Promise<UserInfo> {
  return request("/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface UserUpdate {
  role?: Role;
  is_active?: boolean;
}

export function updateUser(id: string, payload: UserUpdate): Promise<UserInfo> {
  return request(`/users/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export { ApiError };
