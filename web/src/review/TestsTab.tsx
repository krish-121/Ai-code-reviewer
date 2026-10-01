import { useMemo } from "react";

import { api } from "../lib/api";
import { useQuery } from "../lib/hooks";
import type { Finding } from "../lib/types";
import { FindingRow } from "../findings/FindingRow";
import { Empty, Spinner } from "../components/ui";

export function TestsTab({ reviewId, findings }: { reviewId: string; findings: Finding[] }) {
  const graph = useQuery(`graph:${reviewId}`, () => api.graph(reviewId));
  const coverage = useMemo(() => {
    const data = graph.data;
    if (!data) return [];
    const byId = new Map(data.nodes.map((n) => [n.id, n]));
    const changed = data.nodes.filter((n) => n.meta.changed === "true" && n.kind !== "test");
    return changed.map((n) => {
      const tests = data.edges
        .filter((e) => e.target === n.id && (e.kind === "tests" || e.kind === "calls"))
        .map((e) => byId.get(e.source))
        .filter((s) => s?.kind === "test");
      return { node: n, tests: [...new Map(tests.map((t) => [t?.id, t])).values()] };
    });
  }, [graph.data]);
  const testFindings = findings.filter(
    (f) => f.category === "tests" || f.tags.includes("missing-test"),
  );

  if (!graph.data) return <Spinner />;
  return (
    <div className="tests">
      <section className="ov-section">
        <h2>Changed code and the tests that exercise it</h2>
        {coverage.length === 0 ? (
          <Empty title="No changed functions">
            This change doesn't modify any function or method.
          </Empty>
        ) : (
          <table className="cov">
            <thead>
              <tr>
                <th scope="col">Changed</th>
                <th scope="col">Tests that call it</th>
              </tr>
            </thead>
            <tbody>
              {coverage.map(({ node, tests }) => (
                <tr key={node.id} className={tests.length ? "" : "cov-none"}>
                  <td>
                    <code>{node.name}</code>
                    <span className="muted"> {node.file}</span>
                  </td>
                  <td>
                    {tests.length ? (
                      tests.map((t) => (
                        <code key={t?.id} className="cov-test">
                          {t?.name}
                        </code>
                      ))
                    ) : (
                      <span className="cov-gap">No test in the repository calls this</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="fine">
          Derived from the code graph: a test covers a function when it calls it directly or through
          a short call chain.
        </p>
      </section>
      {testFindings.length ? (
        <section className="ov-section">
          <h2>Test findings</h2>
          <ul className="srows">
            {testFindings.map((f) => (
              <FindingRow key={f.id} f={f} reviewId={reviewId} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
