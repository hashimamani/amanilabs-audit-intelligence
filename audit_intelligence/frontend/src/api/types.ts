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
  id: number;
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
  id: number;
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

export interface UploadResult {
  dataset_id: string;
  files_received: string[];
}

export interface RunSummary {
  id: number;
  dataset_id: string;
  created_at: string;
  flag_count: number;
  case_count: number;
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
