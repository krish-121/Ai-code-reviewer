import { useMemo } from "react";

import { api } from "../lib/api";
import { useQuery } from "../lib/hooks";
import type { Finding } from "../lib/types";
import { FindingRow } from "../findings/FindingRow";
import { Empty, ErrorNote, Spinner } from "../components/ui";
import { testsReaching } from "../lib/testReachability";

export function TestsTab({ reviewId, findings }: { reviewId: string; findings: Finding[] }) {
  const graph = useQuery(`graph:${reviewId}`, () => api.graph(reviewId));
  const coverage = useMemo(() => {
    const data = graph.data;
    if (!data) return [];
    const changed = data.nodes.filter((n) => n.meta.changed === "true" && n.kind !== "test");
    return changed.map((n) => {
      return { node: n, tests: testsReaching(data, n.id) };
    });
  }, [graph.data]);
  const testFindings = findings.filter(
    (f) => f.category === "tests" || f.tags.includes("missing-test"),
  );

  if (graph.error) return <ErrorNote error={graph.error} retry={graph.reload} />;
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
                      <span className="cov-gap">No test path found in the available graph</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="fine">
          Graph evidence follows calls up to four edges. A call path does not prove assertion
          coverage; missing paths may reflect incomplete static analysis.
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
