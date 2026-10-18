// The building blocks of the finding detail view: one small component per section.

import { useState } from "react";

import { api } from "../lib/api";
import type { Finding, FindingDetail, FindingStatus, Verification } from "../lib/types";
import { Inline, VerificationRibbon } from "../components/ui";

const OUTCOME_GLYPH: Record<string, string> = {
  supports: "✓",
  contradicts: "✗",
  neutral: "–",
  skipped: "·",
};

/** Entry point → … → the function the finding is in. */
export function CallPath({ path }: { path: string[] }) {
  if (path.length < 2) return null;
  return (
    <section className="fd-section">
      <h3>Reachable from</h3>
      <ol className="callpath">
        {path.map((step, i) => (
          <li key={i} className={i === 0 ? "entry" : i === path.length - 1 ? "target" : ""}>
            <code>{step}</code>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Every deterministic check the verifier ran, with its outcome. */
export function VerifierChecks({ verification }: { verification: Verification }) {
  return (
    <section className="fd-section">
      <h3>What the verifier checked</h3>
      <VerificationRibbon verification={verification} />
      <ul className="checks">
        {verification.checks.map((check) => (
          <li key={check.name} className={`check check-${check.outcome}`}>
            <span className="check-glyph" aria-hidden="true">
              {OUTCOME_GLYPH[check.outcome]}
            </span>
            <span className="check-text">
              <Inline text={check.detail} />
            </span>
            {check.decisive ? <span className="decisive">decisive</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function EvidenceList({ finding }: { finding: Finding }) {
  if (!finding.evidence.length) return null;
  return (
    <section className="fd-section">
      <h3>Evidence</h3>
      <ul className="evidence">
        {finding.evidence.map((item, i) => (
          <li key={i}>
            <span className="ev-source">{item.source}</span>
            <span>
              <Inline text={item.text} />
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Status changes and fixes, oldest first. */
export function History({ events }: { events: FindingDetail["events"] }) {
  if (!events.length) return null;
  return (
    <section className="fd-section">
      <h3>History</h3>
      <ul className="history">
        {events.map((event, i) => (
          <li key={i}>
            <span>
              {event.event === "status_changed"
                ? `${event.from} → ${event.to}`
                : event.event.replace("_", " ")}
            </span>
            {event.note ? <span className="muted"> {event.note}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Accept / dismiss an open finding, or reopen a triaged one. */
export function StatusActions({ finding, onChanged }: { finding: Finding; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const setStatus = async (status: FindingStatus) => {
    setBusy(true);
    setError(null);
    try {
      await api.setStatus(finding.id, status);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setBusy(false);
    }
  };
  if (finding.status !== "open") {
    return (
      <>
        <button className="btn" disabled={busy} onClick={() => setStatus("open")}>
          Reopen ({finding.status})
        </button>
        {error ? <div role="alert">{error.message}</div> : null}
      </>
    );
  }
  return (
    <>
      {error ? <div role="alert">{error.message}</div> : null}
      <button className="btn" disabled={busy} onClick={() => setStatus("accepted")}>
        Accept
      </button>
      <button className="btn" disabled={busy} onClick={() => setStatus("dismissed")}>
        Dismiss
      </button>
    </>
  );
}
