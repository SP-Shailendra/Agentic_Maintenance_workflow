export type Asset = {
  asset_id: string;
  name: string;
  asset_class: string;
  criticality_tier: number;
  safety_critical: boolean | null;
  site_id: string;
  location: string;
  health_index: number;
};

export type Citation = { document: string; section: string; passage: string };
export type Candidate = {
  failure_mode: string;
  confidence: number;
  rationale: string;
  citations: Citation[];
  verified: boolean;
};
export type ApprovalPackage = {
  correlation_id: string;
  asset_id: string;
  anomaly_summary: string;
  diagnosis: { candidates: Candidate[]; selected_index: number; safety_flag: boolean };
  work_order: {
    summary: string;
    tasks: string[];
    priority: number;
    estimated_cost_usd: number;
    parts: { part_number: string; description: string; quantity: number; unit_cost: number }[];
  } | null;
  parts: { all_available: boolean; long_lead: string[]; parts_tbc: boolean };
  technician: { name: string; technician_id: string; skill_match: string[] } | null;
  required_approver_tier: number;
  reasons_for_hitl: string[];
  sla_deadline: string;
  partial: boolean;
  degraded_reasons: string[];
};

export type Workflow = {
  correlation_id: string;
  status: string;
  asset: { asset_id: string };
  anomaly: { anomaly_type: string; severity: number; detected_at: string };
  trace: { node: string; duration_ms: number; model: string | null; outcome: string }[];
};

export type AuditEvent = {
  seq: number;
  correlation_id: string;
  timestamp_utc: string;
  actor: string;
  event_type: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  hash: string;
};

export type Technician = {
  technician_id: string;
  name: string;
  skills: string[];
  available: boolean;
};

export type ActiveScenario = {
  asset_id: string;
  scenario: string;
  scenario_id: string;
  severity: number;
  duration_ticks: number | null;
  elapsed_ticks: number;
  remaining_ticks: number | null;
  seed: number | null;
  measurement_type: string | null;
  recovery_after_ticks: number | null;
};

export type ScenarioRun = {
  scenario_id: string;
  asset_id: string;
  scenario: string;
  severity: number;
  duration_ticks: number | null;
  tick_seconds: number;
  status: string;
  start_time_utc: string;
  end_time_utc: string | null;
  detected: boolean;
  detected_count: number;
  missed: boolean;
  detection_latency_ticks: number | null;
  detection_latency_seconds: number | null;
  false_positive_count: number;
};

const apiBase = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function decide(
  correlationId: string,
  decision: 'approve' | 'modify_approve' | 'reject' | 'escalate',
  reason?: string,
): Promise<void> {
  await api(`/approvals/${encodeURIComponent(correlationId)}/decision`, {
    method: 'POST',
    headers: { 'X-Approver-Id': 'ops-console-user' },
    body: JSON.stringify({ correlation_id: correlationId, decision, approver: 'ops-console-user', reason }),
  });
}
