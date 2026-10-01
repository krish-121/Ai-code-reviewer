// Layered (Sugiyama-style) layout for the architecture view: longest-path layering,
// barycenter ordering to reduce crossings, then fixed-size boxes. Pure and unit-tested.

import type { CodeGraphJson, GraphNode } from "./types";

export interface LaidOutNode {
  node: GraphNode;
  x: number;
  y: number;
  w: number;
  h: number;
  layer: number;
}

export interface LaidOutEdge {
  source: string;
  target: string;
  kind: string;
  path: string;
}

export interface Layout {
  nodes: LaidOutNode[];
  edges: LaidOutEdge[];
  width: number;
  height: number;
}

export const NODE_W = 172;
export const NODE_H = 44;
const GAP_X = 22;
const GAP_Y = 76;
const PAD = 24;
const FLOW_EDGES = new Set([
  "calls",
  "routes",
  "reads",
  "writes",
  "tests",
  "inherits",
  "implements",
]);

export function layoutGraph(graph: CodeGraphJson, maxPerLayer = 7): Layout {
  const nodes = graph.nodes.filter((n) => n.kind !== "file" && n.kind !== "module");
  const ids = new Set(nodes.map((n) => n.id));
  const edges = graph.edges.filter(
    (e) =>
      FLOW_EDGES.has(e.kind) && ids.has(e.source) && ids.has(e.target) && e.source !== e.target,
  );
  const out = new Map<string, string[]>();
  const indeg = new Map<string, number>();
  for (const n of nodes) {
    out.set(n.id, []);
    indeg.set(n.id, 0);
  }

  // Break cycles: DFS, drop back edges.
  const state = new Map<string, 0 | 1 | 2>();
  const adjacency = new Map<string, string[]>();
  for (const e of edges) adjacency.set(e.source, [...(adjacency.get(e.source) ?? []), e.target]);
  const dag: { source: string; target: string }[] = [];
  const visit = (id: string): void => {
    state.set(id, 1);
    for (const t of adjacency.get(id) ?? []) {
      const s = state.get(t) ?? 0;
      if (s === 1) continue; // back edge
      dag.push({ source: id, target: t });
      if (s === 0) visit(t);
    }
    state.set(id, 2);
  };
  const byKind = (n: GraphNode) => (n.kind === "endpoint" ? 0 : n.kind === "test" ? 1 : 2);
  for (const n of [...nodes].sort((a, b) => byKind(a) - byKind(b))) {
    if ((state.get(n.id) ?? 0) === 0) visit(n.id);
  }
  const seen = new Set<string>();
  for (const e of dag) {
    const key = `${e.source}>${e.target}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.get(e.source)?.push(e.target);
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1);
  }

  // Longest-path layering (Kahn order).
  const layer = new Map<string, number>();
  const queue = nodes.filter((n) => (indeg.get(n.id) ?? 0) === 0).map((n) => n.id);
  const remaining = new Map(indeg);
  for (const id of queue) layer.set(id, 0);
  while (queue.length) {
    const id = queue.shift() as string;
    for (const t of out.get(id) ?? []) {
      layer.set(t, Math.max(layer.get(t) ?? 0, (layer.get(id) ?? 0) + 1));
      remaining.set(t, (remaining.get(t) ?? 1) - 1);
      if (remaining.get(t) === 0) queue.push(t);
    }
  }
  let maxLayer = 0;
  for (const n of nodes) maxLayer = Math.max(maxLayer, layer.get(n.id) ?? 0);
  // Data stores always sit at the bottom.
  for (const n of nodes) if (n.kind === "database") layer.set(n.id, maxLayer + 1);

  // Wrap over-full layers so the picture stays readable.
  const rows: string[][] = [];
  const sortedLayers = [...new Set(nodes.map((n) => layer.get(n.id) ?? 0))].sort((a, b) => a - b);
  for (const l of sortedLayers) {
    const members = nodes.filter((n) => (layer.get(n.id) ?? 0) === l).map((n) => n.id);
    for (let i = 0; i < members.length; i += maxPerLayer)
      rows.push(members.slice(i, i + maxPerLayer));
  }

  // Barycenter ordering, a few downward/upward sweeps.
  const preds = new Map<string, string[]>();
  for (const [s, ts] of out) for (const t of ts) preds.set(t, [...(preds.get(t) ?? []), s]);
  const position = new Map<string, number>();
  const assign = () => rows.forEach((row) => row.forEach((id, i) => position.set(id, i)));
  assign();
  const bary = (id: string, neighbours: string[]) => {
    const ps = neighbours.map((n) => position.get(n)).filter((p): p is number => p !== undefined);
    return ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : (position.get(id) ?? 0);
  };
  for (let sweep = 0; sweep < 4; sweep++) {
    const order = sweep % 2 === 0 ? rows.slice(1) : rows.slice(0, -1).reverse();
    for (const row of order) {
      row.sort((a, b) =>
        sweep % 2 === 0
          ? bary(a, preds.get(a) ?? []) - bary(b, preds.get(b) ?? [])
          : bary(a, out.get(a) ?? []) - bary(b, out.get(b) ?? []),
      );
      row.forEach((id, i) => position.set(id, i));
    }
  }

  const widest = Math.max(1, ...rows.map((r) => r.length));
  const width = PAD * 2 + widest * NODE_W + (widest - 1) * GAP_X;
  const height = PAD * 2 + rows.length * NODE_H + Math.max(0, rows.length - 1) * GAP_Y;
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const laid = new Map<string, LaidOutNode>();
  rows.forEach((row, r) => {
    const rowWidth = row.length * NODE_W + (row.length - 1) * GAP_X;
    const x0 = (width - rowWidth) / 2;
    row.forEach((id, i) => {
      const node = nodeById.get(id);
      if (!node) return;
      laid.set(id, {
        node,
        x: x0 + i * (NODE_W + GAP_X),
        y: PAD + r * (NODE_H + GAP_Y),
        w: NODE_W,
        h: NODE_H,
        layer: r,
      });
    });
  });

  const laidEdges: LaidOutEdge[] = [];
  const drawn = new Set<string>();
  for (const e of edges) {
    const a = laid.get(e.source);
    const b = laid.get(e.target);
    const key = `${e.source}>${e.target}>${e.kind}`;
    if (!a || !b || drawn.has(key)) continue;
    drawn.add(key);
    laidEdges.push({ source: e.source, target: e.target, kind: e.kind, path: edgePath(a, b) });
  }
  return { nodes: [...laid.values()], edges: laidEdges, width, height };
}

export function edgePath(a: LaidOutNode, b: LaidOutNode): string {
  const x1 = a.x + a.w / 2;
  const x2 = b.x + b.w / 2;
  if (b.layer > a.layer) {
    const y1 = a.y + a.h;
    const y2 = b.y;
    const my = (y1 + y2) / 2;
    return `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`;
  }
  if (b.layer < a.layer) {
    // upward edge (from a cycle or a wrapped row): route along the sides
    const y1 = a.y;
    const y2 = b.y + b.h;
    const my = (y1 + y2) / 2;
    return `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`;
  }
  const y = a.y + a.h / 2;
  const [left, right] = a.x < b.x ? [a.x + a.w, b.x] : [a.x, b.x + b.w];
  return `M${left},${y} L${right},${y}`;
}
