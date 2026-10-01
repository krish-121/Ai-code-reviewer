import { useMemo, useState } from "react";

import { api } from "../api";
import { bySeverityThenPriority, location, SOURCE_LABEL } from "../format";
import { navigate, useQuery } from "../hooks";
import type { Category, Finding, FindingStatus, ReviewDetail, Severity } from "../types";
import { FixPanel } from "./FixPanel";
import {
  CodeView,
  ConfidenceMeter,
  Empty,
  ErrorNote,
  Inline,
  SeverityMark,
  Spinner,
  VerificationPill,
  VerificationRibbon,
} from "./ui";

const OUTCOME_GLYPH: Record<string, string> = {
  supports: "✓",
  contradicts: "✗",
  neutral: "–",
  skipped: "·",
};

function CallPath({ path }: { path: string[] }) {
  if (path.length < 2) return null;
  return (
    <section className="fd-section">
      <h3>Reachable from</h3>
      <ol className="callpath">
        {path.map((p, i) => (
          <li key={i} className={i === 0 ? "entry" : i === path.length - 1 ? "target" : ""}>
            <code>{p}</code>
          </li>
        ))}
      </ol>
    </section>
  );
}

function StatusActions({ finding, onChanged }: { finding: Finding; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const set = async (status: FindingStatus) => {
    setBusy(true);
    try {
      await api.setStatus(finding.id, status);
      onChanged();
    } finally {
      setBusy(false);
    }
  };
  if (finding.status === "open") {
    return (
      <>
        <button className="btn" disabled={busy} onClick={() => set("accepted")}>
          Accept
        </button>
        <button className="btn" disabled={busy} onClick={() => set("dismissed")}>
          Dismiss
        </button>
      </>
    );
  }
  return (
    <button className="btn" disabled={busy} onClick={() => set("open")}>
      Reopen ({finding.status})
    </button>
  );
}

function FindingDetailView({
  review,
  finding,
  onChanged,
}: {
  review: ReviewDetail;
  finding: Finding;
  onChanged: () => void;
}) {
  const detail = useQuery(`finding:${finding.id}`, () => api.finding(finding.id));
  const source = useQuery(`source:${review.id}:${finding.file}`, () =>
    api.source(review.id, finding.file),
  );
  const [fixId, setFixId] = useState<string | null>(null);
  const [fixError, setFixError] = useState<string | null>(null);
  const ver = finding.verification;
  const latestFix = fixId ?? detail.data?.fixes[0]?.id ?? null;

  const requestFix = async () => {
    setFixError(null);
    try {
      const { id } = await api.requestFix(finding.id);
      setFixId(id);
    } catch (err) {
      setFixError(err instanceof Error ? err.message : String(err));
    }
  };

  const changed = () => {
    detail.reload();
    onChanged();
  };

  return (
    <article className="finding-detail" aria-labelledby="fd-title">
      <header className="fd-head">
        <div className="fd-kicker">
          <SeverityMark severity={finding.severity} withLabel />
          <span className="fd-category">{finding.category}</span>
          {finding.status !== "open" ? (
            <span className={`fstatus fstatus-${finding.status}`}>{finding.status}</span>
          ) : null}
        </div>
        <h2 id="fd-title">
          <Inline text={finding.title} />
        </h2>
        <button
          className="linkish fd-loc"
          onClick={() =>
            navigate(
              `/reviews/${review.id}?tab=files&file=${encodeURIComponent(finding.file)}&line=${finding.line_start}`,
            )
          }
        >
          {location(finding)}
          {finding.symbol ? <span className="muted"> in {finding.symbol}</span> : null}
        </button>
      </header>

      <div className="fd-meta">
        <div>
          <span className="fd-meta-label">Confidence</span>
          <ConfidenceMeter value={finding.confidence} />
        </div>
        <div>
          <span className="fd-meta-label">Verification</span>
          <VerificationPill status={ver?.status} />
        </div>
        <div>
          <span className="fd-meta-label">Found by</span>
          <span>{SOURCE_LABEL[finding.source]}</span>
        </div>
      </div>

      {finding.suppressed ? (
        <p className="suppressed-note">
          <strong>Not shown as an issue:</strong> {finding.suppressed_reason}
        </p>
      ) : null}

      <section className="fd-section">
        <h3>Explanation</h3>
        <p className="prose">
          <Inline text={finding.explanation} />
        </p>
        {finding.priority ? <p className="fine">Priority: {finding.priority.explanation}</p> : null}
      </section>

      {ver ? <CallPath path={ver.call_path} /> : null}

      {source.data ? (
        <section className="fd-section">
          <h3>Code</h3>
          <CodeView
            path={finding.file}
            content={source.data.content}
            start={finding.line_start - 3}
            end={finding.line_end + 3}
            highlight={[finding.line_start, finding.line_end]}
          />
        </section>
      ) : null}

      {ver ? (
        <section className="fd-section">
          <h3>What the verifier checked</h3>
          <VerificationRibbon verification={ver} />
          <ul className="checks">
            {ver.checks.map((c) => (
              <li key={c.name} className={`check check-${c.outcome}`}>
                <span className="check-glyph" aria-hidden="true">
                  {OUTCOME_GLYPH[c.outcome]}
                </span>
                <span className="check-text">
                  <Inline text={c.detail} />
                </span>
                {c.decisive ? <span className="decisive">decisive</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {finding.evidence.length ? (
        <section className="fd-section">
          <h3>Evidence</h3>
          <ul className="evidence">
            {finding.evidence.map((e, i) => (
              <li key={i}>
                <span className="ev-source">{e.source}</span>
                <span>
                  <Inline text={e.text} />
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {finding.suggested_fix ? (
        <section className="fd-section">
          <h3>Suggested fix</h3>
          <p className="prose">
            <Inline text={finding.suggested_fix} />
          </p>
        </section>
      ) : null}

      <div className="fd-actions">
        <button className="btn btn-primary" onClick={requestFix}>
          Generate fix
        </button>
        <StatusActions finding={finding} onChanged={changed} />
        <button
          className="btn"
          onClick={() =>
            navigate(
              `/reviews/${review.id}?tab=architecture&focus=${encodeURIComponent(finding.symbol ?? "")}`,
            )
          }
        >
          View context
        </button>
      </div>
      {fixError ? <ErrorNote error={new Error(fixError)} /> : null}
      {latestFix ? (
        <FixPanel fixId={latestFix} canApply={review.can_apply_fixes} onApplied={changed} />
      ) : null}

      {detail.data && detail.data.events.length ? (
        <section className="fd-section">
          <h3>History</h3>
          <ul className="history">
            {detail.data.events.map((e, i) => (
              <li key={i}>
                <span>
                  {e.event === "status_changed" ? `${e.from} → ${e.to}` : e.event.replace("_", " ")}
                </span>
                {e.note ? <span className="muted"> {e.note}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}

const SEVERITIES: Severity[] = ["high", "medium", "low"];

export function FindingsTab({
  review,
  findings,
  selectedId,
  onChanged,
}: {
  review: ReviewDetail;
  findings: Finding[];
  selectedId: string | null;
  onChanged: () => void;
}) {
  const [showSuppressed, setShowSuppressed] = useState(false);
  const [severities, setSeverities] = useState<Set<Severity>>(new Set(SEVERITIES));
  const [category, setCategory] = useState<Category | "all">("all");

  const categories = useMemo(
    () => [...new Set(findings.map((f) => f.category))].sort(),
    [findings],
  );
  const list = useMemo(
    () =>
      findings
        .filter((f) => showSuppressed || !f.suppressed)
        .filter((f) => severities.has(f.severity))
        .filter((f) => category === "all" || f.category === category)
        .sort(
          (a, b) => Number(a.suppressed) - Number(b.suppressed) || bySeverityThenPriority(a, b),
        ),
    [findings, showSuppressed, severities, category],
  );
  const selected =
    findings.find((f) => f.id === selectedId || f.merged_ids.includes(selectedId ?? "")) ??
    list[0] ??
    null;

  if (findings.length === 0) {
    return <Empty title="No findings">Sentinel found nothing to report in this change.</Empty>;
  }

  return (
    <div className="findings">
      <div className="findings-list">
        <div className="filters" role="group" aria-label="Filter findings">
          <div className="chips">
            {SEVERITIES.map((s) => (
              <button
                key={s}
                className={`chip ${severities.has(s) ? "on" : ""}`}
                aria-pressed={severities.has(s)}
                onClick={() => {
                  const next = new Set(severities);
                  if (next.has(s)) next.delete(s);
                  else next.add(s);
                  setSeverities(next);
                }}
              >
                <SeverityMark severity={s} withLabel />
              </button>
            ))}
          </div>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as Category | "all")}
            aria-label="Category"
          >
            <option value="all">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <label className="toggle">
            <input
              type="checkbox"
              checked={showSuppressed}
              onChange={(e) => setShowSuppressed(e.target.checked)}
            />
            Include suppressed ({findings.filter((f) => f.suppressed).length})
          </label>
        </div>
        <ul className="flist">
          {list.map((f) => (
            <li key={f.id}>
              <button
                className={`fitem ${selected?.id === f.id ? "on" : ""} ${f.suppressed ? "fitem-suppressed" : ""}`}
                aria-current={selected?.id === f.id}
                onClick={() => navigate(`/reviews/${review.id}/findings/${f.id}`)}
              >
                <SeverityMark severity={f.severity} />
                <span className="fitem-body">
                  <span className="fitem-title">
                    <Inline text={f.title} />
                  </span>
                  <span className="fitem-loc">{location(f)}</span>
                  <VerificationRibbon verification={f.verification} compact />
                </span>
                <span className="fitem-side">
                  <VerificationPill status={f.verification?.status} />
                  <span className="fitem-conf">{Math.round(f.confidence * 100)}%</span>
                </span>
              </button>
            </li>
          ))}
          {list.length === 0 ? (
            <li className="muted pad">No findings match these filters.</li>
          ) : null}
        </ul>
      </div>
      <div className="findings-detail">
        {selected ? (
          <FindingDetailView
            key={selected.id}
            review={review}
            finding={selected}
            onChanged={onChanged}
          />
        ) : (
          <Spinner />
        )}
      </div>
    </div>
  );
}
