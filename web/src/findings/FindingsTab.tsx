// The Findings tab: a filterable list on the left, the selected finding on the right.

import { useMemo, useState } from "react";

import { bySeverityThenPriority, location } from "../lib/format";
import { navigate } from "../lib/hooks";
import type { Finding, ReviewDetail } from "../lib/types";
import {
  Empty,
  Inline,
  SeverityMark,
  Spinner,
  VerificationPill,
  VerificationRibbon,
} from "../components/ui";
import { FindingDetailView } from "./FindingDetailView";
import { FindingFilters, SEVERITIES, type Filters } from "./FindingFilters";

interface Props {
  review: ReviewDetail;
  findings: Finding[];
  selectedId: string | null;
  onChanged: () => void;
}

export function FindingsTab({ review, findings, selectedId, onChanged }: Props) {
  const [filters, setFilters] = useState<Filters>({
    severities: new Set(SEVERITIES),
    category: "all",
    showSuppressed: false,
  });
  const categories = useMemo(
    () => [...new Set(findings.map((f) => f.category))].sort(),
    [findings],
  );
  const visible = useMemo(() => applyFilters(findings, filters), [findings, filters]);
  const selected =
    findings.find((f) => f.id === selectedId || f.merged_ids.includes(selectedId ?? "")) ??
    visible[0] ??
    null;

  if (findings.length === 0) {
    return <Empty title="No findings">Sentinel found nothing to report in this change.</Empty>;
  }
  return (
    <div className="findings">
      <div className="findings-list">
        <FindingFilters
          filters={filters}
          categories={categories}
          suppressedCount={findings.filter((f) => f.suppressed).length}
          onChange={setFilters}
        />
        <ul className="flist">
          {visible.map((finding) => (
            <li key={finding.id}>
              <FindingListItem
                finding={finding}
                selected={selected?.id === finding.id}
                onSelect={() => navigate(`/reviews/${review.id}/findings/${finding.id}`)}
              />
            </li>
          ))}
          {visible.length === 0 ? (
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

/** Findings that pass the filters: shown ones first, then by severity and priority. */
function applyFilters(findings: Finding[], filters: Filters): Finding[] {
  return findings
    .filter((f) => filters.showSuppressed || !f.suppressed)
    .filter((f) => filters.severities.has(f.severity))
    .filter((f) => filters.category === "all" || f.category === filters.category)
    .sort((a, b) => Number(a.suppressed) - Number(b.suppressed) || bySeverityThenPriority(a, b));
}

function FindingListItem({
  finding,
  selected,
  onSelect,
}: {
  finding: Finding;
  selected: boolean;
  onSelect: () => void;
}) {
  const classes = ["fitem", selected ? "on" : "", finding.suppressed ? "fitem-suppressed" : ""];
  return (
    <button className={classes.join(" ")} aria-current={selected} onClick={onSelect}>
      <SeverityMark severity={finding.severity} />
      <span className="fitem-body">
        <span className="fitem-title">
          <Inline text={finding.title} />
        </span>
        <span className="fitem-loc">{location(finding)}</span>
        <VerificationRibbon verification={finding.verification} compact />
      </span>
      <span className="fitem-side">
        <VerificationPill status={finding.verification?.status} />
        <span className="fitem-conf">{Math.round(finding.confidence * 100)}%</span>
      </span>
    </button>
  );
}
