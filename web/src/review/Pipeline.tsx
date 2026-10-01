import { duration } from "../lib/format";
import type { Stage } from "../lib/types";

const LABELS: Record<string, string> = {
  parse_diff: "Parse diff",
  filter_files: "Filter files and redact secrets",
  build_graph: "Build code graph",
  extract_context: "Extract context",
  static_analysis: "Run static analysis",
  ai_review: "AI review",
  verification: "Verify findings",
  finalize: "Deduplicate, prioritize, summarize",
};
const ORDER = Object.keys(LABELS);

export function Pipeline({ stages, live = false }: { stages: Stage[]; live?: boolean }) {
  const byName = new Map(stages.map((s) => [s.name, s]));
  const total = stages.reduce((sum, s) => sum + (s.duration_ms ?? 0), 0) || 1;
  return (
    <ol className={`pipeline ${live ? "pipeline-live" : ""}`}>
      {ORDER.map((name) => {
        const s = byName.get(name);
        const status = s?.status ?? "pending";
        const share = s?.duration_ms ? Math.max(2, (s.duration_ms / total) * 100) : 0;
        return (
          <li key={name} className={`stage stage-${status}`}>
            <span className="stage-glyph" aria-hidden="true" />
            <span className="stage-name">{LABELS[name]}</span>
            <span className="stage-detail">{s?.detail ?? ""}</span>
            <span className="stage-time">
              {status === "done" || status === "failed"
                ? duration(s?.duration_ms)
                : status === "running"
                  ? "running"
                  : status === "skipped"
                    ? "skipped"
                    : ""}
            </span>
            {!live && share ? (
              <span className="stage-bar" aria-hidden="true">
                <span style={{ width: `${share}%` }} />
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
