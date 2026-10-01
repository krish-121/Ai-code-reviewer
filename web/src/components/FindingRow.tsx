import { location } from "../format";
import { navigate } from "../hooks";
import type { Finding } from "../types";
import { Inline, SeverityMark, VerificationPill } from "./ui";

export function FindingRow({ f, reviewId }: { f: Finding; reviewId: string }) {
  return (
    <li className={`srow ${f.suppressed ? "srow-suppressed" : ""}`}>
      <SeverityMark severity={f.severity} />
      <button className="linkish" onClick={() => navigate(`/reviews/${reviewId}/findings/${f.id}`)}>
        <Inline text={f.title} />
      </button>
      <span className="muted srow-loc">{location(f)}</span>
      <VerificationPill status={f.verification?.status} />
      {f.suppressed ? <span className="srow-reason">{f.suppressed_reason}</span> : null}
    </li>
  );
}
