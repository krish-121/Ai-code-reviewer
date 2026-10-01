import assert from "node:assert/strict";
import { test } from "node:test";

import { layoutGraph } from "../src/graphLayout.ts";
import type { CodeGraphJson, GraphNode } from "../src/types.ts";

function node(id: string, kind: GraphNode["kind"] = "function"): GraphNode {
  return { id, kind, name: id, file: "a.py", line_start: 1, line_end: 2, meta: {} };
}

test("layers follow call direction; data stores go last", () => {
  const graph: CodeGraphJson = {
    nodes: [
      node("ep", "endpoint"),
      node("handler"),
      node("svc"),
      node("db", "database"),
      node("f", "file"),
    ],
    edges: [
      { source: "ep", target: "handler", kind: "routes", line: 1 },
      { source: "handler", target: "svc", kind: "calls", line: 2 },
      { source: "handler", target: "db", kind: "reads", line: 3 },
      { source: "f", target: "handler", kind: "defines", line: null },
    ],
  };
  const layout = layoutGraph(graph);
  const layer = Object.fromEntries(layout.nodes.map((n) => [n.node.id, n.layer]));
  assert.deepEqual(layer, { ep: 0, handler: 1, svc: 2, db: 3 });
  assert.equal(layout.edges.length, 3);
  assert.ok(layout.edges.every((e) => e.path.startsWith("M")));
  assert.ok(layout.width > 0 && layout.height > 0);
});

test("cycles do not break layering and wide layers wrap", () => {
  const nodes = [node("a"), node("b"), ...Array.from({ length: 9 }, (_, i) => node(`leaf${i}`))];
  const edges = [
    { source: "a", target: "b", kind: "calls", line: 1 },
    { source: "b", target: "a", kind: "calls", line: 2 },
    ...Array.from({ length: 9 }, (_, i) => ({
      source: "b",
      target: `leaf${i}`,
      kind: "calls",
      line: 3,
    })),
  ];
  const layout = layoutGraph({ nodes, edges }, 4);
  const rows = new Set(
    layout.nodes.filter((n) => n.node.id.startsWith("leaf")).map((n) => n.layer),
  );
  assert.equal(rows.size, 3); // 9 leaves, 4 per row
  const positions = new Set(layout.nodes.map((n) => `${n.x},${n.y}`));
  assert.equal(positions.size, layout.nodes.length); // no overlaps
});

test("empty graph", () => {
  const layout = layoutGraph({ nodes: [], edges: [] });
  assert.equal(layout.nodes.length, 0);
});
