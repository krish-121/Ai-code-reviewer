import { type FormEvent, useState } from "react";

import { api, type NewReview } from "../lib/api";
import { duration, relativeTime } from "../lib/format";
import { navigate, useQuery } from "../lib/hooks";
import type { ReviewItem } from "../lib/types";
import { Empty, ErrorNote, RiskBadge, Spinner } from "../components/ui";

function sourceLabel(r: ReviewItem): string {
  if (r.pull_request) return `Pull request #${r.pull_request.number}`;
  return (
    {
      staged: "Staged changes",
      worktree: "Uncommitted changes",
      range: "Commit range",
      path: "Files",
    }[r.source] ?? r.source
  );
}

function Counts({ counts }: { counts: ReviewItem["counts"] }) {
  const items = (["high", "medium", "low"] as const).filter((s) => (counts[s] ?? 0) > 0);
  if (items.length === 0) return <span className="muted">No findings</span>;
  return (
    <span className="counts">
      {items.map((s) => (
        <span key={s} className={`count count-${s}`} title={`${counts[s]} ${s}`}>
          {counts[s]}
        </span>
      ))}
    </span>
  );
}

function NewReviewForm({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState<NewReview>({ path: "", mode: "staged" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { id } = await api.createReview(form);
      navigate(`/reviews/${id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <form className="new-review" onSubmit={submit} aria-label="Start a review">
      <label>
        Repository path on this machine
        <input
          required
          autoFocus
          placeholder="/home/you/projects/shop"
          value={form.path}
          onChange={(e) => setForm({ ...form, path: e.target.value })}
        />
      </label>
      <fieldset>
        <legend>What to review</legend>
        {(
          [
            ["staged", "Staged changes"],
            ["worktree", "Uncommitted changes"],
            ["range", "A commit range"],
            ["path", "Every file under a folder"],
          ] as const
        ).map(([value, label]) => (
          <label key={value} className="radio">
            <input
              type="radio"
              name="mode"
              value={value}
              checked={form.mode === value}
              onChange={() => setForm({ ...form, mode: value })}
            />
            {label}
          </label>
        ))}
      </fieldset>
      {form.mode === "range" ? (
        <div className="row">
          <label>
            Base
            <input
              value={form.base ?? ""}
              placeholder="main"
              onChange={(e) => setForm({ ...form, base: e.target.value })}
            />
          </label>
          <label>
            Head
            <input
              value={form.head ?? ""}
              placeholder="HEAD"
              onChange={(e) => setForm({ ...form, head: e.target.value })}
            />
          </label>
        </div>
      ) : null}
      {form.mode === "path" ? (
        <label>
          Folder inside the repository (optional)
          <input
            value={form.subpath ?? ""}
            placeholder="src"
            onChange={(e) => setForm({ ...form, subpath: e.target.value })}
          />
        </label>
      ) : null}
      {error ? <p className="form-error">{error}</p> : null}
      <div className="actions">
        <button type="button" className="btn" onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Starting…" : "Start review"}
        </button>
      </div>
    </form>
  );
}

export function ReviewsPage() {
  const reviews = useQuery("reviews", api.reviews, 5000);
  const [creating, setCreating] = useState(false);

  return (
    <section className="page">
      <div className="page-head">
        <div>
          <h1>Reviews</h1>
          <p className="lede">
            Every change Sentinel has looked at. Findings are checked against the code before they
            reach you; anything the evidence contradicts is set aside, not hidden.
          </p>
        </div>
        {!creating ? (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            Review a local repository
          </button>
        ) : null}
      </div>
      {creating ? <NewReviewForm onClose={() => setCreating(false)} /> : null}
      {reviews.error ? <ErrorNote error={reviews.error} /> : null}
      {reviews.loading && !reviews.data ? <Spinner /> : null}
      {reviews.data && reviews.data.length === 0 ? (
        <Empty title="No reviews yet">
          <p>
            Run <code>sentinel review --staged</code> in a repository, open a pull request on a
            repository with the GitHub App installed, or review a local repository from here.
          </p>
        </Empty>
      ) : null}
      {reviews.data && reviews.data.length > 0 ? (
        <table className="review-table">
          <thead>
            <tr>
              <th scope="col">Change</th>
              <th scope="col">Risk</th>
              <th scope="col">Findings</th>
              <th scope="col">Status</th>
              <th scope="col" className="num">
                Took
              </th>
              <th scope="col" className="num">
                When
              </th>
            </tr>
          </thead>
          <tbody>
            {reviews.data.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => navigate(`/reviews/${r.id}`)}>
                <td>
                  <a
                    href={`/reviews/${r.id}`}
                    className="review-title"
                    onClick={(e) => {
                      e.preventDefault();
                      navigate(`/reviews/${r.id}`);
                    }}
                  >
                    {r.pull_request?.title ?? r.title ?? r.id}
                  </a>
                  <span className="review-sub">
                    <span>{r.repository}</span>
                    <span>{sourceLabel(r)}</span>
                  </span>
                </td>
                <td>
                  <RiskBadge risk={r.risk} />
                </td>
                <td>
                  <Counts counts={r.counts} />
                </td>
                <td>
                  <span className={`status status-${r.status}`}>{r.status}</span>
                </td>
                <td className="num">{duration(r.duration_ms)}</td>
                <td className="num muted">{relativeTime(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
