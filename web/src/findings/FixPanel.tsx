import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { duration } from "../lib/format";
import { invalidate, useQuery } from "../lib/hooks";
import type { FixAttempt } from "../lib/types";
import { ErrorNote, Spinner } from "../components/ui";

const PENDING = new Set(["queued", "running"]);
const CHECK_NAME: Record<string, string> = {
  apply: "Patch applies",
  syntax: "Syntax",
  "finding-resolved": "Original issue gone",
  "no-new-issues": "No new issues",
  tests: "Tests",
  analysis: "Static analysis",
  "regression-tests": "New regression tests",
};
const VERDICT: Record<string, string> = {
  validated: "Validated: all required checks passed.",
  unverified: "Some required checks did not complete. Complete validation before applying.",
  failed: "Failed validation. Don't apply this patch.",
  error: "Fix generation failed.",
  applied: "Applied to the working tree.",
  rejected: "Rejected.",
};

export function DiffView({ patch }: { patch: string }) {
  return (
    <pre className="diff" aria-label="Proposed patch">
      {patch.split("\n").map((line, i) => {
        const cls =
          line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ")
            ? "d-meta"
            : line.startsWith("@@")
              ? "d-hunk"
              : line.startsWith("+")
                ? "d-add"
                : line.startsWith("-")
                  ? "d-del"
                  : "";
        return (
          <span key={i} className={cls}>
            {line}
            {"\n"}
          </span>
        );
      })}
    </pre>
  );
}

export function FixPanel({
  fixId,
  canApply,
  onApplied,
}: {
  fixId: string;
  canApply: boolean;
  onApplied: () => void;
}) {
  const [finishedId, setFinishedId] = useState<string | null>(null);
  const fix = useQuery<FixAttempt>(
    `fix:${fixId}`,
    () => api.fix(fixId),
    finishedId !== fixId ? 1500 : undefined,
  );
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const data = fix.data;
  useEffect(() => {
    if (data?.id === fixId && !PENDING.has(data.status)) setFinishedId(fixId);
  }, [data?.id, data?.status, fixId]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      invalidate(`fix:${fixId}`);
      fix.reload();
      onApplied();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="fix-panel" aria-live="polite">
      <h3>Proposed fix</h3>
      {fix.error ? <ErrorNote error={fix.error} retry={fix.reload} /> : null}
      {!data || PENDING.has(data.status) ? (
        <Spinner label="Generating a patch and validating it in a sandbox" />
      ) : (
        <>
          <p className={`verdict verdict-${data.status}`}>{VERDICT[data.status] ?? data.status}</p>
          {data.summary ? <p className="prose">{data.summary}</p> : null}
          {data.error ? <ErrorNote error={new Error(data.error)} /> : null}
          {data.checks.length ? (
            <table className="fix-checks">
              <tbody>
                {data.checks.map((c) => (
                  <tr key={c.name} className={`fc fc-${c.status}`}>
                    <th scope="row">{CHECK_NAME[c.name] ?? c.name}</th>
                    <td className="fc-status">{c.status}</td>
                    <td className="fc-detail">{c.detail}</td>
                    <td className="num muted">{c.duration_ms ? duration(c.duration_ms) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {data.isolation ? (
            <p className="fine">
              Isolation: <strong>{data.isolation}</strong>
              {data.isolation === "none" ? " (tests were not executed)" : ""}. Attempts:{" "}
              {data.attempts}.
            </p>
          ) : null}
          {data.patch ? <DiffView patch={data.patch} /> : null}
          <div className="fd-actions">
            {data.status === "validated" && data.can_apply && canApply ? (
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={() => act(() => api.applyFix(fixId))}
              >
                Apply to working tree
              </button>
            ) : null}
            {data.patch ? (
              <button
                className="btn"
                onClick={() => downloadText(`${fixId}.patch`, data.patch ?? "")}
              >
                Download patch
              </button>
            ) : null}
            {data.status !== "applied" && data.status !== "rejected" ? (
              <button
                className="btn"
                disabled={busy}
                onClick={() => act(() => api.rejectFix(fixId))}
              >
                Reject
              </button>
            ) : null}
          </div>
        </>
      )}
      {error ? <ErrorNote error={error} /> : null}
    </section>
  );
}

/** Save text as a file in the browser (the patch is already loaded; no extra request). */
function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/x-diff" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
