import type {
  CaseDetail,
  CaseSummary,
  CaseUpdate,
  RunSummary,
  TenantInfo,
  UploadResult,
} from "./types";

const BASE_URL = "/api";
const TENANT_KEY = import.meta.env.VITE_TENANT_KEY ?? "";

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "X-Tenant-Key": TENANT_KEY };
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

export function uploadDataset(files: File[]): Promise<UploadResult> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file, file.name);
  }
  return request("/upload", { method: "POST", body: form });
}

export function runAnalysis(datasetId?: string): Promise<RunSummary> {
  return request("/analysis/run", {
    method: "POST",
    body: JSON.stringify({ dataset_id: datasetId ?? null }),
  });
}

export function listRuns(): Promise<RunSummary[]> {
  return request("/analysis/runs");
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

export function getCase(id: number): Promise<CaseDetail> {
  return request(`/cases/${id}`);
}

export function updateCase(id: number, payload: CaseUpdate): Promise<CaseDetail> {
  return request(`/cases/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export interface BulkStatusResult {
  updated_count: number;
}

export function bulkUpdateCaseStatus(
  caseIds: number[],
  status: string,
): Promise<BulkStatusResult> {
  return request("/cases/bulk-status", {
    method: "PATCH",
    body: JSON.stringify({ case_ids: caseIds, status }),
  });
}

export function getCurrentTenant(): Promise<TenantInfo> {
  return request("/tenant/me");
}

export { ApiError };
