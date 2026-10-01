import { api } from "../lib/api";
import { location } from "../lib/format";
import { useQuery } from "../lib/hooks";
import type { Finding } from "../lib/types";
import { FindingRow } from "../findings/FindingRow";
import { Spinner } from "../components/ui";

export function SecurityTab({ reviewId, findings }: { reviewId: string; findings: Finding[] }) {
  const files = useQuery(`files:${reviewId}`, () => api.files(reviewId));
  const security = findings.filter((f) => f.category === "security");
  const surfaced = security.filter((f) => !f.suppressed);
  const rejected = security.filter((f) => f.suppressed);
  const secrets = surfaced.filter((f) => f.tags.includes("secret"));
  const injection = surfaced.filter((f) => f.tags.includes("prompt-injection"));
  const sensitive = (files.data?.skipped ?? []).filter((s) => s.reason.startsWith("sensitive"));

  return (
    <div className="security">
      <section className="ov-section">
        <h2>Security findings</h2>
        {surfaced.length ? (
          <ul className="srows">
            {surfaced.map((f) => (
              <FindingRow key={f.id} f={f} reviewId={reviewId} />
            ))}
          </ul>
        ) : (
          <p className="muted">No security issues surfaced in this change.</p>
        )}
      </section>
      <div className="security-grid">
        <section className="ov-card">
          <h3>Kept away from the AI</h3>
          {files.data ? null : <Spinner />}
          {sensitive.length ? (
            <ul className="plain">
              {sensitive.map((s) => (
                <li key={s.path}>
                  <code>{s.path}</code>
                  <span className="muted"> {s.reason.replace(" — never sent to AI", "")}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No sensitive files in this change.</p>
          )}
          <p className="fine">
            Sensitive files are dropped before analysis, and credentials inside other files (
            {secrets.length} here) are replaced with <code>[REDACTED:…]</code> in everything sent to
            a model or stored for this page.
          </p>
        </section>
        <section className="ov-card">
          <h3>Instructions planted in code</h3>
          {injection.length ? (
            <ul className="plain">
              {injection.map((f) => (
                <li key={f.id}>
                  <code>{location(f)}</code>
                  <span className="muted"> {f.evidence[0]?.text ?? ""}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">None found.</p>
          )}
          <p className="fine">
            Repository content is passed to the model as data inside nonce-tagged blocks and is
            never followed as instructions. Text aimed at AI reviewers is still reported, because
            other tools may obey it.
          </p>
        </section>
      </div>
      {rejected.length ? (
        <section className="ov-section">
          <h2>Security claims the evidence did not support</h2>
          <ul className="srows">
            {rejected.map((f) => (
              <FindingRow key={f.id} f={f} reviewId={reviewId} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
