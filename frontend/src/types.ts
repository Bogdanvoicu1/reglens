export interface Source {
  id: number;
  ref: string;
  title: string;
  corpus: string;
  text: string;
}

export interface DoneMeta {
  status: string;
  cached: boolean;
  cited_sources: number[];
  conversation_id: string;
  latency_ms: number;
}

export type SSEEvent =
  | { event: "sources"; data: { sources: Source[] } }
  | { event: "token"; data: { token: string } }
  | { event: "done"; data: DoneMeta }
  | { event: "refusal"; data: { reason: string } }
  | { event: "error"; data: { message: string } };

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
}

export interface MessageOut {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: { cited: number[] } | null;
  latency_ms: number | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: MessageOut[];
}

export interface CorpusOut {
  slug: string;
  title: string;
  version: string;
}

// ── Assessments (v2 agent) ────────────────────────────────────────────────

export interface AssessmentSummary {
  id: string;
  title: string;
  status: "draft" | "clarifying" | "running" | "complete" | "failed";
  created_at: string;
  completed_at: string | null;
}

export interface ReportBlocker {
  rule_id: string;
  title: string;
  reasoning: string;
  citations: string[];
}

export type GapStatus = "met" | "partial" | "missing" | "unknown";

export interface ReportObligation {
  id: string;
  title: string;
  summary: string;
  audience: string;
  audience_established: boolean;
  severity: string;
  triggered_by: string[];
  citations: string[];
  gap_status: GapStatus;
  gap_reasoning: string;
}

export interface ReportRemediation {
  title: string;
  description: string;
  priority: "blocker" | "high" | "medium" | "low";
  effort: "S" | "M" | "L";
  addresses: string[];
  tradeoffs: string;
}

export interface AssessmentReport {
  assessment_id: string;
  title: string;
  generated_at: string;
  rulebook_version: string | null;
  corpus_fingerprint: string | null;
  executive_summary: string;
  verdict_counts: Record<string, number>;
  gap_counts: Record<string, number>;
  profile: Record<string, unknown>;
  blockers: ReportBlocker[];
  obligations: ReportObligation[];
  remediation: ReportRemediation[];
  disclaimer: string;
}
