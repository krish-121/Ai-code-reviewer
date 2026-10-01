import { type ReactNode, useMemo } from "react";

import { checkLabel, pct, VERIFICATION_LABEL } from "../format";
import { highlightLines, languageOf } from "../highlight";
import type { Risk, Severity, Verification, VerificationStatus } from "../types";

export function SeverityMark({
  severity,
  withLabel = false,
}: {
  severity: Severity;
  withLabel?: boolean;
}) {
  const label = severity[0]?.toUpperCase() + severity.slice(1);
  return (
    <span className={`sev sev-${severity}`} title={`${label} severity`}>
      <span className="sev-shape" aria-hidden="true" />
      {withLabel ? (
        <span className="sev-label">{label}</span>
      ) : (
        <span className="sr-only">{label}</span>
      )}
    </span>
  );
}

export function RiskBadge({ risk }: { risk: Risk | null }) {
  if (!risk) return <span className="risk risk-pending">Pending</span>;
  const text = risk === "none" ? "No risk found" : `${risk[0]?.toUpperCase()}${risk.slice(1)} risk`;
  return <span className={`risk risk-${risk}`}>{text}</span>;
}

export function VerificationPill({ status }: { status: VerificationStatus | null | undefined }) {
  if (!status) return <span className="ver ver-none">Unverified</span>;
  return (
    <span className={`ver ver-${status}`} title="Result of deterministic verification">
      <span className="ver-glyph" aria-hidden="true" />
      {VERIFICATION_LABEL[status]}
    </span>
  );
}

export function ConfidenceMeter({ value }: { value: number }) {
  const segments = 5;
  const filled = Math.round(value * segments);
  return (
    <span
      className="conf"
      title={`Confidence ${pct(value)}`}
      aria-label={`Confidence ${pct(value)}`}
    >
      <span className="conf-bars" aria-hidden="true">
        {Array.from({ length: segments }, (_, i) => (
          <span key={i} className={i < filled ? "on" : ""} />
        ))}
      </span>
      <span className="conf-num">{pct(value)}</span>
    </span>
  );
}

/**
 * The verification ribbon: one cell per check, filled when it supports the claim,
 * hatched when it contradicts it, hollow when it had nothing to say.
 */
export function VerificationRibbon({
  verification,
  compact = false,
}: {
  verification: Verification | null;
  compact?: boolean;
}) {
  if (!verification || verification.checks.length === 0) return null;
  return (
    <ol className={`ribbon ${compact ? "ribbon-compact" : ""}`} aria-label="Verification checks">
      {verification.checks.map((c) => (
        <li
          key={c.name}
          className={`cell cell-${c.outcome} ${c.decisive ? "cell-decisive" : ""}`}
          title={`${checkLabel(c.name)}: ${c.outcome}. ${c.detail}`}
        >
          {compact ? <span className="sr-only">{checkLabel(c.name)}</span> : checkLabel(c.name)}
        </li>
      ))}
    </ol>
  );
}

/** Plain text with `code` spans rendered as <code>. */
export function Inline({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.length > 2 && p.startsWith("`") && p.endsWith("`") ? (
          <code key={i}>{p.slice(1, -1)}</code>
        ) : (
          p
        ),
      )}
    </>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <p className="empty-title">{title}</p>
      {children ? <div className="empty-body">{children}</div> : null}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="spinner" role="status">
      <span className="spinner-dot" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorNote({ error }: { error: Error }) {
  return (
    <div className="error-note" role="alert">
      {error.message}
    </div>
  );
}

export interface CodeViewProps {
  path: string;
  content: string;
  start?: number;
  end?: number;
  highlight?: [number, number];
  onLineClick?: (line: number) => void;
}

/** Source excerpt with line numbers and syntax highlighting. */
export function CodeView({ path, content, start = 1, end, highlight }: CodeViewProps) {
  const lines = useMemo(() => content.split("\n"), [content]);
  const tokens = useMemo(() => highlightLines(lines, languageOf(path)), [lines, path]);
  const last = Math.min(end ?? lines.length, lines.length);
  const first = Math.max(1, start);
  const rows = [];
  for (let n = first; n <= last; n++) {
    const marked = highlight && n >= highlight[0] && n <= highlight[1];
    rows.push(
      <div key={n} className={`code-row ${marked ? "code-marked" : ""}`}>
        <span className="code-ln">{n}</span>
        <span className="code-text">
          {(tokens[n - 1] ?? []).map((t, i) => (
            <span key={i} className={`tok-${t.t}`}>
              {t.v}
            </span>
          ))}
          {"\n"}
        </span>
      </div>,
    );
  }
  return (
    <pre className="code" aria-label={`${path} lines ${first} to ${last}`}>
      {rows}
    </pre>
  );
}
