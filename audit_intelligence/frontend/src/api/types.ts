export type Severity = "Low" | "Medium" | "High" | "Critical";

export interface Evidence {
  label: string;
  value: string;
}

export interface Flag {
  rule_id: string;
  rule_name: string;
  severity: Severity;
  entity_type: string;
  entity_id: string;
  member_id: string | null;
  explanation: string;
  evidence: Evidence[];
  suggested_steps: string[];
  triggered_at: string | null;
}

export interface TimelineEvent {
  timestamp: string | null;
  rule_id: string;
  rule_name: string;
  explanation: string;
}

export interface CaseSummary {
  id: string;
  case_ref: string;
  run_id: number;
  subject_type: string;
  subject_id: string;
  subject_name: string;
  risk_score: number;
  severity: Severity;
  status: string;
  triggered_rules: string[];
  flag_count: number;
  created_at: string;
  updated_at: string;
}

export interface CaseDetail {
  id: string;
  case_ref: string;
  run_id: number;
  subject_type: string;
  subject_id: string;
  subject_name: string;
  risk_score: number;
  severity: Severity;
  status: string;
  triggered_rules: string[];
  flags: Flag[];
  evidence: Evidence[];
  timeline: TimelineEvent[];
  related_entities: Record<string, string[]>;
  recommended_actions: string[];
  assigned_auditor: string | null;
  notes: string[];
  outcome: string | null;
  ai_summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseUpdate {
  status?: string;
  assigned_auditor?: string;
  outcome?: string;
  add_note?: string;
}

export interface AskCaseResult {
  answer: string;
}

export interface ChartDatapoint {
  label: string;
  value: number;
}

export type ChartType = "bar" | "line";

export interface AnalyticsQueryResult {
  title: string;
  chart_type: ChartType;
  data: ChartDatapoint[];
}

export interface ReportResult {
  report_text: string;
  case_count: number;
  generated_at: string;
}

export interface UploadTarget {
  file: string;
  url: string;
  method: string;
}

export interface DatasetCreateResult {
  dataset_id: string;
  uploads: UploadTarget[];
}

export type DatasetStatus = "pending" | "ready" | "invalid";

export interface UploadResult {
  dataset_id: string;
  status: DatasetStatus;
  errors: string[];
  created_at: string;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface Job<T> {
  id: string;
  kind: "analysis" | "analytics" | "report";
  status: JobStatus;
  result: T | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunSummary {
  id: number;
  dataset_id: string;
  status: JobStatus;
  job_id: string | null;
  created_at: string;
  completed_at: string | null;
  flag_count: number;
  case_count: number;
  severity_counts: Record<string, number>;
  rule_counts: Record<string, number>;
  error: string | null;
}

export interface ActivityEntry {
  at: string;
  actor_email: string;
  actor_name: string;
  action: string;
  detail: Record<string, unknown>;
}

export type Role = "auditor" | "admin";

export interface UserInfo {
  id: string;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
  tenant_slug: string;
  tenant_name: string;
}

export const REQUIRED_UPLOAD_FILES = [
  "members.csv",
  "branches.csv",
  "employees.csv",
  "accounts.csv",
  "transactions.csv",
  "loans.csv",
  "guarantors.csv",
  "loan_payments.csv",
] as const;

export interface RuleThreshold {
  key: string;
  label: string;
  value: number;
}

export interface RuleInfo {
  rule_id: string;
  rule_name: string;
  summary: string;
  detail: string;
  signal: string;
  thresholds: RuleThreshold[];
}

export const STATUSES = ["Open", "In Progress", "Closed"] as const;
export type CaseStatus = (typeof STATUSES)[number];
export const SEVERITIES: Severity[] = ["Critical", "High", "Medium", "Low"];
