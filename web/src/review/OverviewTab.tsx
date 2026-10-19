import { navigate } from "../lib/hooks";
import type { Finding, ReviewDetail, VerificationStatus } from "../lib/types";
import { Pipeline } from "./Pipeline";
import { Inline, SeverityMark, VerificationPill } from "../components/ui";

const VER_ORDER: VerificationStatus[] = ["supported", "likely", "uncertain", "rejected"];

function Section({ title, items, empty }: { title: string; items: string[]; empty?: string }) {
  if (items.length === 0 && !empty) return null;
  return (
    <section className="ov-section">
      <h2>{title}</h2>
      {items.length === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        <ul>
          {items.map((item, i) => (
            <li key={i}>
              <Inline text={item} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function OverviewTab({ review, findings }: { review: ReviewDetail; findings: Finding[] }) {
  const summary = review.summary;
  const surfaced = findings.filter((f) => !f.suppressed);
  const top = surfaced.slice(0, 5);
  const verCounts = new Map<VerificationStatus, number>();
  for (const f of findings) {
    const s = f.verification?.status;
    if (s) verCounts.set(s, (verCounts.get(s) ?? 0) + 1);
  }
  const sev = summary?.stats.by_severity ?? {};
  const sevTotal = (sev.high ?? 0) + (sev.medium ?? 0) + (sev.low ?? 0);

  return (
    <div className="overview">
      <div className="ov-main">
        <section className="ov-section">
          <h2>What deserves attention</h2>
          {top.length === 0 ? (
            <p className="muted">
              Nothing surfaced. Suppressed findings are listed under Findings.
            </p>
          ) : (
            <ol className="attention">
              {top.map((f) => (
                <li key={f.id}>
                  <button
                    className="attention-item"
                    onClick={() => navigate(`/reviews/${review.id}/findings/${f.id}`)}
                  >
                    <SeverityMark severity={f.severity} />
                    <span className="attention-title">
                      <Inline text={f.title} />
                    </span>
                    <span className="attention-loc">
                      {f.file}:{f.line_start}
                    </span>
                    <VerificationPill status={f.verification?.status} />
                  </button>
                </li>
              ))}
            </ol>
          )}
        </section>
        <Section title="What changed" items={summary?.what_changed ?? []} />
        <Section
          title="What was verified"
          items={summary?.verified ?? []}
          empty="No claims needed verification."
        />
        <Section
          title="What remains uncertain"
          items={summary?.uncertain ?? []}
          empty={
            review.status === "partial" || review.status === "failed"
              ? "This review is incomplete. Some checks did not finish; see Errors and Pipeline."
              : "Every surfaced finding was confirmed by the available checks."
          }
        />
        {review.errors.length ? (
          <section className="ov-section">
            <h2>Errors</h2>
            <ul className="errors">
              {review.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
      <aside className="ov-side">
        <section className="ov-card">
          <h3>Severity</h3>
          {sevTotal ? (
            <>
              <div
                className="stack"
                role="img"
                aria-label={`${sev.high ?? 0} high, ${sev.medium ?? 0} medium, ${sev.low ?? 0} low`}
              >
                {(["high", "medium", "low"] as const).map((s) =>
                  sev[s] ? (
                    <span key={s} className={`stack-${s}`} style={{ flexGrow: sev[s] }} />
                  ) : null,
                )}
              </div>
              <dl className="legend">
                {(["high", "medium", "low"] as const).map((s) => (
                  <div key={s}>
                    <dt>
                      <SeverityMark severity={s} withLabel />
                    </dt>
                    <dd>{sev[s] ?? 0}</dd>
                  </div>
                ))}
              </dl>
            </>
          ) : (
            <p className="muted">No surfaced findings.</p>
          )}
        </section>
        <section className="ov-card">
          <h3>Verification</h3>
          <dl className="legend">
            {VER_ORDER.map((s) => (
              <div key={s}>
                <dt>
                  <VerificationPill status={s} />
                </dt>
                <dd>{verCounts.get(s) ?? 0}</dd>
              </div>
            ))}
          </dl>
          <p className="fine">
            Counts include suppressed findings. Rejected claims are kept for the record, not shown
            as issues.
          </p>
        </section>
        <section className="ov-card">
          <h3>Pipeline</h3>
          <Pipeline stages={review.stages} />
        </section>
        <section className="ov-card">
          <h3>Analyzers</h3>
          <ul className="tools">
            {review.analysis_runs.map((r) => (
              <li key={r.tool} className={`tool tool-${r.status}`} title={r.detail}>
                <span className="tool-name">{r.tool}</span>
                <span className="tool-status">
                  {r.status === "ok" ? `${r.findings} found` : r.status}
                </span>
              </li>
            ))}
          </ul>
          {review.usage.input_tokens ? (
            <p className="fine">
              Model usage: {review.usage.input_tokens.toLocaleString()} input and{" "}
              {review.usage.output_tokens.toLocaleString()} output tokens.
            </p>
          ) : null}
        </section>
      </aside>
    </div>
  );
}
