// Pure formatting helpers (unit-tested in tests/format.test.ts).

import type { Finding, Severity, VerificationStatus } from "./types";

export function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "–";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s % 60)} s`;
}

export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const then = new Date(iso);
  const diff = Math.max(0, (now.getTime() - then.getTime()) / 1000);
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  if (diff < 86400 * 7) return `${Math.round(diff / 86400)} d ago`;
  return then.toLocaleDateString();
}

export function location(f: Pick<Finding, "file" | "line_start" | "line_end">): string {
  return f.line_end !== f.line_start
    ? `${f.file}:${f.line_start}–${f.line_end}`
    : `${f.file}:${f.line_start}`;
}

const SEV_RANK: Record<Severity, number> = { high: 3, medium: 2, low: 1 };

export function bySeverityThenPriority(a: Finding, b: Finding): number {
  const sev = SEV_RANK[b.severity] - SEV_RANK[a.severity];
  if (sev !== 0) return sev;
  return (b.priority?.score ?? 0) - (a.priority?.score ?? 0);
}

export const VERIFICATION_LABEL: Record<VerificationStatus, string> = {
  supported: "Supported",
  likely: "Likely",
  uncertain: "Uncertain",
  rejected: "Rejected",
};

export const SOURCE_LABEL: Record<Finding["source"], string> = {
  ai: "AI only",
  static_analyzer: "Static analysis",
  verified: "AI, verified",
  combined: "AI + static analysis",
};

export const CHECK_LABEL: Record<string, string> = {
  location: "Location exists",
  "change-relevance": "Touches the change",
  "symbols-exist": "Symbols exist",
  "call-path": "Call path",
  reachability: "Reachable",
  "static-corroboration": "Static analysis agrees",
  "test-coverage": "Test coverage",
  "not-style": "Not a style remark",
  "deterministic-rule": "Deterministic rule",
  "probe:sql-injection": "SQL probe",
  "probe:n+1": "Loop/query probe",
  "probe:async": "Async probe",
  "probe:quadratic": "Nested-loop probe",
  "probe:secret": "Secret probe",
  "probe:auth": "Auth-order probe",
  "probe:error-handling": "Error-handling probe",
};

export function checkLabel(name: string): string {
  return CHECK_LABEL[name] ?? name.replace(/^probe:/, "").replace(/-/g, " ");
}

/** Group findings by file path, preserving order. */
export function groupByFile(findings: Finding[]): Map<string, Finding[]> {
  const out = new Map<string, Finding[]>();
  for (const f of findings) {
    const list = out.get(f.file) ?? [];
    list.push(f);
    out.set(f.file, list);
  }
  return out;
}

export function pluralize(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
