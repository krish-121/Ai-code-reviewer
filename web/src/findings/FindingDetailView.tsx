// The right-hand panel of the Findings tab: everything about one finding, plus fixes.

import { useState } from "react";

import { api } from "../lib/api";
import { location, SOURCE_LABEL } from "../lib/format";
import { navigate, useQuery } from "../lib/hooks";
import type { Finding, ReviewDetail } from "../lib/types";
import {
  CodeView,
  ConfidenceMeter,
  ErrorNote,
  Inline,
  SeverityMark,
  VerificationPill,
} from "../components/ui";
import { CallPath, EvidenceList, History, StatusActions, VerifierChecks } from "./FindingSections";
import { FixPanel } from "./FixPanel";

const CODE_CONTEXT_LINES = 3;

interface Props {
  review: ReviewDetail;
  finding: Finding;
  onChanged: () => void;
}

export function FindingDetailView({ review, finding, onChanged }: Props) {
  const detail = useQuery(`finding:${finding.id}`, () => api.finding(finding.id));
  const changed = () => {
    detail.reload();
    onChanged();
  };
  const verification = finding.verification;
  return (
    <article className="finding-detail" aria-labelledby="fd-title">
      <FindingHeader review={review} finding={finding} />
      <FindingMeta finding={finding} />
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
      {verification ? <CallPath path={verification.call_path} /> : null}
      <FindingCode review={review} finding={finding} />
      {verification ? <VerifierChecks verification={verification} /> : null}
      <EvidenceList finding={finding} />
      {finding.suggested_fix ? (
        <section className="fd-section">
          <h3>Suggested fix</h3>
          <p className="prose">
            <Inline text={finding.suggested_fix} />
          </p>
        </section>
      ) : null}
      <FindingActions
        review={review}
        finding={finding}
        latestFixId={detail.data?.fixes[0]?.id ?? null}
        onChanged={changed}
      />
      <History events={detail.data?.events ?? []} />
    </article>
  );
}

function FindingHeader({ review, finding }: Omit<Props, "onChanged">) {
  const openInFiles = () =>
    navigate(
      `/reviews/${review.id}?tab=files&file=${encodeURIComponent(finding.file)}&line=${finding.line_start}`,
    );
  return (
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
      <button className="linkish fd-loc" onClick={openInFiles}>
        {location(finding)}
        {finding.symbol ? <span className="muted"> in {finding.symbol}</span> : null}
      </button>
    </header>
  );
}

function FindingMeta({ finding }: { finding: Finding }) {
  return (
    <div className="fd-meta">
      <div>
        <span className="fd-meta-label">Confidence</span>
        <ConfidenceMeter value={finding.confidence} />
      </div>
      <div>
        <span className="fd-meta-label">Verification</span>
        <VerificationPill status={finding.verification?.status} />
      </div>
      <div>
        <span className="fd-meta-label">Found by</span>
        <span>{SOURCE_LABEL[finding.source]}</span>
      </div>
    </div>
  );
}

/** The cited lines with a few lines of context, from the review's redacted snapshot. */
function FindingCode({ review, finding }: Omit<Props, "onChanged">) {
  const source = useQuery(`source:${review.id}:${finding.file}`, () =>
    api.source(review.id, finding.file),
  );
  if (!source.data) return null;
  return (
    <section className="fd-section">
      <h3>Code</h3>
      <CodeView
        path={finding.file}
        content={source.data.content}
        start={finding.line_start - CODE_CONTEXT_LINES}
        end={finding.line_end + CODE_CONTEXT_LINES}
        highlight={[finding.line_start, finding.line_end]}
      />
    </section>
  );
}

/** Generate fix / accept / dismiss / view context, and the latest fix attempt. */
function FindingActions({
  review,
  finding,
  latestFixId,
  onChanged,
}: Props & { latestFixId: string | null }) {
  const [requestedFixId, setRequestedFixId] = useState<string | null>(null);
  const [fixError, setFixError] = useState<string | null>(null);
  const fixId = requestedFixId ?? latestFixId;
  const requestFix = async () => {
    setFixError(null);
    try {
      const { id } = await api.requestFix(finding.id);
      setRequestedFixId(id);
    } catch (err) {
      setFixError(err instanceof Error ? err.message : String(err));
    }
  };
  const viewContext = () =>
    navigate(
      `/reviews/${review.id}?tab=architecture&focus=${encodeURIComponent(finding.symbol ?? "")}`,
    );
  return (
    <>
      <div className="fd-actions">
        <button className="btn btn-primary" onClick={requestFix}>
          Generate fix
        </button>
        <StatusActions finding={finding} onChanged={onChanged} />
        <button className="btn" onClick={viewContext}>
          View context
        </button>
      </div>
      {fixError ? <ErrorNote error={new Error(fixError)} /> : null}
      {fixId ? (
        <FixPanel fixId={fixId} canApply={review.can_apply_fixes} onApplied={onChanged} />
      ) : null}
    </>
  );
}
