// Types mirroring the Sentinel HTTP API (src/sentinel/apps/api/app.py).

export type Severity = "high" | "medium" | "low";
export type Risk = "high" | "medium" | "low" | "none";
export type Category =
  | "bug"
  | "security"
  | "performance"
  | "tests"
  | "architecture"
  | "documentation"
  | "style";
export type VerificationStatus = "supported" | "likely" | "uncertain" | "rejected";
export type FindingStatus = "open" | "accepted" | "dismissed" | "fixed";
export type ReviewStatus = "queued" | "running" | "completed" | "partial" | "failed";
export type StageStatus = "pending" | "running" | "done" | "skipped" | "failed";
export type CheckOutcome = "supports" | "contradicts" | "neutral" | "skipped";

export interface Stage {
  name: string;
  status: StageStatus;
  started_at: string | null;
  duration_ms: number | null;
  detail: string;
  metrics: Record<string, number | string>;
}

export interface ReviewSummary {
  risk: Risk;
  headline: string;
  stats: {
    files_changed: number;
    files_reviewed: number;
    files_skipped: number;
    lines_added: number;
    lines_removed: number;
    by_severity: Record<string, number>;
    by_category: Record<string, number>;
    by_verification: Record<string, number>;
    suppressed: number;
  };
  what_changed: string[];
  attention: string[];
  verified: string[];
  uncertain: string[];
}

export interface PullRequestRef {
  number: number;
  url: string | null;
  title: string;
  author: string | null;
}

export interface ReviewItem {
  id: string;
  title: string | null;
  status: ReviewStatus;
  risk: Risk | null;
  source: string;
  repository: string;
  repository_kind: "local" | "github";
  pull_request: PullRequestRef | null;
  counts: Partial<Record<Severity, number>>;
  headline: string | null;
  provider: string | null;
  model: string | null;
  created_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface AnalysisRun {
  tool: string;
  status: string;
  duration_ms: number;
  findings: number;
  detail: string;
}

export interface ReviewDetail extends ReviewItem {
  summary: ReviewSummary | null;
  stages: Stage[];
  errors: string[];
  base_ref: string | null;
  head_ref: string | null;
  usage: { input_tokens: number; output_tokens: number };
  published_at: string | null;
  mode: string | null;
  analysis_runs: AnalysisRun[];
  can_apply_fixes: boolean;
}

export interface Evidence {
  source: string;
  text: string;
  file: string | null;
  line: number | null;
}

export interface VerificationCheck {
  name: string;
  outcome: CheckOutcome;
  detail: string;
  weight: number;
  decisive: boolean;
}

export interface Verification {
  status: VerificationStatus;
  score: number;
  checks: VerificationCheck[];
  summary: string;
  reachability: "entrypoint" | "test-only" | "unreachable" | "unknown";
  call_path: string[];
}

export interface Priority {
  score: number;
  severity_weight: number;
  confidence: number;
  reachability: number;
  change_relevance: number;
  explanation: string;
}

export interface Finding {
  id: string;
  category: Category;
  severity: Severity;
  confidence: number;
  title: string;
  explanation: string;
  file: string;
  line_start: number;
  line_end: number;
  evidence: Evidence[];
  suggested_fix: string | null;
  source: "ai" | "static_analyzer" | "verified" | "combined";
  origins: string[];
  rule_id: string | null;
  tags: string[];
  status: FindingStatus;
  fingerprint: string;
  verification: Verification | null;
  priority: Priority | null;
  in_changed_lines: boolean;
  merged_ids: string[];
  suppressed: boolean;
  suppressed_reason: string | null;
  symbol: string | null;
  review_id: string;
}

export type LineKind = "added" | "removed" | "context";

export interface DiffLine {
  kind: LineKind;
  content: string;
  old_lineno: number | null;
  new_lineno: number | null;
}

export interface Hunk {
  old_start: number;
  old_count: number;
  new_start: number;
  new_count: number;
  header: string;
  lines: DiffLine[];
}

export interface FileChange {
  path: string;
  old_path: string | null;
  change_type: "added" | "modified" | "deleted" | "renamed";
  language: string;
  is_binary: boolean;
  hunks: Hunk[];
}

export interface ChangeSetJson {
  source: string;
  title: string | null;
  files: FileChange[];
  skipped: { path: string; reason: string }[];
}

export type NodeKind =
  | "file"
  | "module"
  | "class"
  | "function"
  | "method"
  | "variable"
  | "test"
  | "endpoint"
  | "database";

export interface GraphNode {
  id: string;
  kind: NodeKind;
  name: string;
  file: string | null;
  line_start: number | null;
  line_end: number | null;
  meta: Record<string, string>;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
  line: number | null;
}

export interface CodeGraphJson {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface FixCheck {
  name: string;
  status: "passed" | "failed" | "skipped" | "error";
  detail: string;
  duration_ms: number;
}

export interface FixAttempt {
  id: string;
  finding_id: string;
  status:
    | "queued"
    | "running"
    | "validated"
    | "unverified"
    | "failed"
    | "error"
    | "applied"
    | "rejected";
  summary: string | null;
  patch: string | null;
  checks: FixCheck[];
  isolation: string | null;
  provider: string | null;
  model: string | null;
  attempts: number;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
  can_apply: boolean;
}

export interface FindingDetail {
  finding: Finding;
  events: {
    event: string;
    from: string | null;
    to: string | null;
    note: string | null;
    at: string | null;
  }[];
  fixes: FixAttempt[];
}

export interface Health {
  status: string;
  version: string;
  database: string;
  queue: number;
  provider: string;
  auth: string;
}
