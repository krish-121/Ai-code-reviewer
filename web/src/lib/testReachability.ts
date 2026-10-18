import type { CodeGraphJson } from "./types";

/** Bounded graph evidence, not a claim that test assertions cover the behaviour. */
export function testsReaching(graph: CodeGraphJson, target: string, maxDepth = 4) {
  const seen = new Set([target]);
  let frontier = [target];
  for (let depth = 0; depth < maxDepth && frontier.length; depth++) {
    const next: string[] = [];
    for (const edge of graph.edges) {
      if (
        (edge.kind === "tests" || edge.kind === "calls") &&
        frontier.includes(edge.target) &&
        !seen.has(edge.source)
      ) {
        seen.add(edge.source);
        next.push(edge.source);
      }
    }
    frontier = next;
  }
  return graph.nodes.filter((node) => node.kind === "test" && seen.has(node.id));
}
