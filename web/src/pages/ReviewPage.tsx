import { useEffect, useState } from "react";

import { api, subscribeProgress } from "../lib/api";
import { duration, pluralize } from "../lib/format";
import { invalidate, navigate, setSearchParam, useQuery, useSearchParam } from "../lib/hooks";
import type { Finding, ReviewDetail, Stage } from "../lib/types";
import { ArchitectureTab } from "../review/ArchitectureTab";
import { FilesTab } from "../review/FilesTab";
import { FindingsTab } from "../findings/FindingsTab";
import { OverviewTab } from "../review/OverviewTab";
import { Pipeline } from "../review/Pipeline";
import { SecurityTab } from "../review/SecurityTab";
import { TestsTab } from "../review/TestsTab";
import { ErrorNote, RiskBadge, Spinner } from "../components/ui";

const TABS = ["overview", "files", "findings", "architecture", "security", "tests"] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = {
  overview: "Overview",
  files: "Files",
  findings: "Findings",
  architecture: "Architecture",
  security: "Security",
  tests: "Tests",
};
const RUNNING = new Set(["queued", "running"]);

function reviewerLabel(review: ReviewDetail): string {
  const aiStage = review.stages.find((stage) => stage.name === "ai_review");
  if (aiStage?.status === "failed") return "AI review unavailable";
  if (RUNNING.has(review.status)) return "Awaiting review result";
  if (aiStage?.status === "skipped") return "Static analysis only";
  return review.provider ? `${review.provider} / ${review.model}` : "Static analysis only";
}

export function ReviewHeader({ review }: { review: ReviewDetail }) {
  const s = review.summary?.stats;
  return (
    <div className="review-head">
      <div className="review-head-main">
        <p className="crumbs">
          <a
            href="/"
            onClick={(e) => {
              e.preventDefault();
              navigate("/");
            }}
          >
            Reviews
          </a>
          <span aria-hidden="true">/</span>
          <span>{review.repository}</span>
        </p>
        <h1>
          {review.pull_request ? (
            <>
              <span className="pr-number">#{review.pull_request.number}</span>{" "}
              {review.pull_request.title}
            </>
          ) : (
            (review.title ?? review.id)
          )}
        </h1>
        <dl className="facts">
          {s ? (
            <>
              <div>
                <dt>Files</dt>
                <dd>{s.files_reviewed}</dd>
              </div>
              <div>
                <dt>Added</dt>
                <dd className="plus">+{s.lines_added}</dd>
              </div>
              <div>
                <dt>Removed</dt>
                <dd className="minus">−{s.lines_removed}</dd>
              </div>
            </>
          ) : null}
          <div>
            <dt>Reviewer</dt>
            <dd>{reviewerLabel(review)}</dd>
          </div>
          <div>
            <dt>Took</dt>
            <dd>{duration(review.duration_ms)}</dd>
          </div>
          {review.pull_request?.url ? (
            <div>
              <dt>Pull request</dt>
              <dd>
                <a href={review.pull_request.url} target="_blank" rel="noreferrer">
                  Open on GitHub
                </a>
              </dd>
            </div>
          ) : null}
        </dl>
      </div>
      <div className="review-head-side">
        <RiskBadge risk={review.risk} />
        {review.summary ? <p className="headline">{review.summary.headline}</p> : null}
        {review.status === "partial" ? (
          <p className="partial-note">Partial review: some stages failed (see Overview).</p>
        ) : null}
      </div>
    </div>
  );
}

function LiveProgress({ review, onDone }: { review: ReviewDetail; onDone: () => void }) {
  const [stages, setStages] = useState<Stage[]>(review.stages);
  useEffect(
    () =>
      subscribeProgress(
        review.id,
        (e) => setStages(e.stages),
        () => onDone(),
      ),
    [review.id],
  );
  return (
    <div className="progress-panel" aria-live="polite">
      <h2>Analyzing this change</h2>
      <p className="muted">
        Each stage below is real work: parsing the diff, building the code graph, running static
        analysis, asking the model, then checking what it said.
      </p>
      <Pipeline stages={stages} live />
    </div>
  );
}

export function ReviewPage({
  reviewId,
  findingId,
}: {
  reviewId: string;
  findingId: string | null;
}) {
  const review = useQuery(`review:${reviewId}`, () => api.review(reviewId));
  const findings = useQuery<Finding[]>(
    review.data && !RUNNING.has(review.data.status) ? `findings:${reviewId}` : null,
    () => api.findings(reviewId),
  );
  const tabParam = useSearchParam("tab");
  const tab: Tab = findingId
    ? "findings"
    : TABS.includes(tabParam as Tab)
      ? (tabParam as Tab)
      : "overview";

  if (review.error) return <ErrorNote error={review.error} />;
  if (!review.data) return <Spinner label="Loading review" />;
  const r = review.data;

  const reload = () => {
    invalidate(`findings:${reviewId}`);
    invalidate("reviews");
    review.reload();
    findings.reload();
  };

  if (RUNNING.has(r.status)) {
    return (
      <section className="page">
        <ReviewHeader review={r} />
        <LiveProgress review={r} onDone={reload} />
      </section>
    );
  }

  const visible = (findings.data ?? []).filter((f) => !f.suppressed);
  const counts: Partial<Record<Tab, number>> = {
    findings: visible.length,
    security: visible.filter((f) => f.category === "security").length,
    tests: visible.filter((f) => f.category === "tests").length,
  };

  const selectTab = (t: Tab) => {
    if (findingId) navigate(`/reviews/${reviewId}?tab=${t}`);
    else setSearchParam("tab", t === "overview" ? null : t);
  };

  return (
    <section className="page page-wide">
      <ReviewHeader review={r} />
      <div className="tabs" role="tablist" aria-label="Review sections">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "tab on" : "tab"}
            onClick={() => selectTab(t)}
          >
            {TAB_LABEL[t]}
            {counts[t] ? <span className="tab-count">{counts[t]}</span> : null}
          </button>
        ))}
      </div>
      {findings.error ? <ErrorNote error={findings.error} /> : null}
      <div className="tab-body" role="tabpanel">
        {tab === "overview" ? <OverviewTab review={r} findings={findings.data ?? []} /> : null}
        {tab === "files" ? <FilesTab reviewId={reviewId} findings={visible} /> : null}
        {tab === "findings" ? (
          <FindingsTab
            review={r}
            findings={findings.data ?? []}
            selectedId={findingId}
            onChanged={reload}
          />
        ) : null}
        {tab === "architecture" ? <ArchitectureTab reviewId={reviewId} findings={visible} /> : null}
        {tab === "security" ? (
          <SecurityTab reviewId={reviewId} findings={findings.data ?? []} />
        ) : null}
        {tab === "tests" ? <TestsTab reviewId={reviewId} findings={visible} /> : null}
      </div>
      <p className="footnote">
        {pluralize(visible.length, "finding")} shown,{" "}
        {pluralize((findings.data ?? []).length - visible.length, "suppressed finding")}. Review{" "}
        <code>{r.id}</code>
      </p>
    </section>
  );
}
