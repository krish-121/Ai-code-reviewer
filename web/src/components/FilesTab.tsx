import { Fragment, useEffect, useMemo } from "react";

import { api } from "../api";
import { groupByFile } from "../format";
import { highlightLines, languageOf } from "../highlight";
import { navigate, setSearchParam, useQuery, useSearchParam } from "../hooks";
import type { FileChange, Finding } from "../types";
import { Empty, ErrorNote, Inline, SeverityMark, Spinner, VerificationPill } from "./ui";

const CHANGE_LABEL: Record<FileChange["change_type"], string> = {
  added: "added",
  modified: "modified",
  deleted: "deleted",
  renamed: "renamed",
};

function stats(f: FileChange): { add: number; del: number } {
  let add = 0;
  let del = 0;
  for (const h of f.hunks)
    for (const l of h.lines) {
      if (l.kind === "added") add += 1;
      else if (l.kind === "removed") del += 1;
    }
  return { add, del };
}

function Callout({ finding, reviewId }: { finding: Finding; reviewId: string }) {
  return (
    <div className={`callout callout-${finding.severity}`}>
      <SeverityMark severity={finding.severity} />
      <button
        className="linkish callout-title"
        onClick={() => navigate(`/reviews/${reviewId}/findings/${finding.id}`)}
      >
        <Inline text={finding.title} />
      </button>
      <VerificationPill status={finding.verification?.status} />
    </div>
  );
}

function FileDiff({
  file,
  findings,
  reviewId,
  focusLine,
}: {
  file: FileChange;
  findings: Finding[];
  reviewId: string;
  focusLine: number | null;
}) {
  const lang = languageOf(file.path);
  const anchored = useMemo(() => {
    const m = new Map<number, Finding[]>();
    for (const f of findings) m.set(f.line_end, [...(m.get(f.line_end) ?? []), f]);
    return m;
  }, [findings]);
  const hunkTokens = useMemo(
    () =>
      file.hunks.map((h) =>
        highlightLines(
          h.lines.map((l) => l.content),
          lang,
        ),
      ),
    [file, lang],
  );
  useEffect(() => {
    if (focusLine === null) return;
    document.getElementById(`L${focusLine}`)?.scrollIntoView({ block: "center" });
  }, [focusLine, file.path]);

  if (file.is_binary) return <Empty title="Binary file">No textual diff to show.</Empty>;
  if (file.hunks.length === 0)
    return <Empty title="No content changes">Renamed or mode change only.</Empty>;
  // Findings whose line isn't visible in any hunk are listed at the top.
  const visible = new Set<number>();
  for (const h of file.hunks) for (const l of h.lines) if (l.new_lineno) visible.add(l.new_lineno);
  const orphans = findings.filter((f) => !visible.has(f.line_end));

  return (
    <div className="diff-file">
      {orphans.length ? (
        <div className="orphans">
          {orphans.map((f) => (
            <Callout key={f.id} finding={f} reviewId={reviewId} />
          ))}
        </div>
      ) : null}
      <table className="difftable">
        <tbody>
          {file.hunks.map((h, hi) => (
            <Fragment key={hi}>
              <tr className="hunk-head">
                <td colSpan={3}>
                  @@ −{h.old_start},{h.old_count} +{h.new_start},{h.new_count} @@ {h.header}
                </td>
              </tr>
              {h.lines.map((l, li) => {
                const here =
                  l.new_lineno !== null && l.kind !== "removed"
                    ? anchored.get(l.new_lineno)
                    : undefined;
                const focused = focusLine !== null && l.new_lineno === focusLine;
                return (
                  <Fragment key={li}>
                    <tr
                      id={
                        l.new_lineno !== null && l.kind !== "removed"
                          ? `L${l.new_lineno}`
                          : undefined
                      }
                      className={`dl dl-${l.kind} ${focused ? "dl-focus" : ""}`}
                    >
                      <td className="ln">{l.old_lineno ?? ""}</td>
                      <td className="ln">{l.new_lineno ?? ""}</td>
                      <td className="dc">
                        <span className="dsign" aria-hidden="true">
                          {l.kind === "added" ? "+" : l.kind === "removed" ? "−" : " "}
                        </span>
                        {(hunkTokens[hi]?.[li] ?? []).map((t, ti) => (
                          <span key={ti} className={`tok-${t.t}`}>
                            {t.v}
                          </span>
                        ))}
                      </td>
                    </tr>
                    {here ? (
                      <tr className="dl-callouts">
                        <td colSpan={3}>
                          {here.map((f) => (
                            <Callout key={f.id} finding={f} reviewId={reviewId} />
                          ))}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FilesTab({ reviewId, findings }: { reviewId: string; findings: Finding[] }) {
  const files = useQuery(`files:${reviewId}`, () => api.files(reviewId));
  const selectedPath = useSearchParam("file");
  const lineParam = useSearchParam("line");
  const byFile = useMemo(() => groupByFile(findings), [findings]);

  if (files.error) return <ErrorNote error={files.error} />;
  if (!files.data) return <Spinner />;
  const list = files.data.files;
  if (list.length === 0) return <Empty title="No reviewable files in this change" />;
  const selected = list.find((f) => f.path === selectedPath) ?? list[0];
  if (!selected) return null;

  return (
    <div className="files">
      <nav className="filelist" aria-label="Changed files">
        <ul>
          {list.map((f) => {
            const s = stats(f);
            const n = byFile.get(f.path)?.length ?? 0;
            return (
              <li key={f.path}>
                <button
                  className={f.path === selected.path ? "on" : ""}
                  aria-current={f.path === selected.path}
                  onClick={() => {
                    setSearchParam("line", null);
                    setSearchParam("file", f.path);
                  }}
                >
                  <span className="fl-path">{f.path}</span>
                  <span className="fl-meta">
                    <span className={`ct ct-${f.change_type}`}>{CHANGE_LABEL[f.change_type]}</span>
                    <span className="plus">+{s.add}</span>
                    <span className="minus">−{s.del}</span>
                    {n ? (
                      <span className="fl-findings" title={`${n} findings`}>
                        {n}
                      </span>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        {files.data.skipped.length ? (
          <div className="skipped">
            <h3>Not analyzed</h3>
            <ul>
              {files.data.skipped.map((s) => (
                <li key={s.path}>
                  <code>{s.path}</code>
                  <span className="muted">{s.reason}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </nav>
      <div className="diffpane">
        <h2 className="diff-path">{selected.path}</h2>
        <FileDiff
          file={selected}
          findings={byFile.get(selected.path) ?? []}
          reviewId={reviewId}
          focusLine={lineParam ? Number(lineParam) : null}
        />
      </div>
    </div>
  );
}
