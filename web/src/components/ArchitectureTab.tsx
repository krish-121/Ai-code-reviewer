import { useMemo, useState } from "react";

import { api } from "../api";
import { layoutGraph, type LaidOutNode } from "../graphLayout";
import { navigate, useQuery, useSearchParam } from "../hooks";
import type { CodeGraphJson, Finding, GraphNode } from "../types";
import { CodeView, Empty, ErrorNote, Inline, SeverityMark, Spinner } from "./ui";

const KIND_LABEL: Record<string, string> = {
  endpoint: "Endpoint",
  function: "Function",
  method: "Method",
  class: "Class",
  test: "Test",
  database: "Data store",
};

function findingsIn(node: GraphNode, findings: Finding[]): Finding[] {
  if (!node.file || node.line_start === null || node.line_end === null) return [];
  return findings.filter(
    (f) =>
      f.file === node.file &&
      f.line_start >= (node.line_start ?? 0) &&
      f.line_start <= (node.line_end ?? 0),
  );
}

function shortName(node: GraphNode): string {
  if (node.kind === "endpoint" || node.kind === "database") return node.name;
  const parts = node.name.split(".");
  return parts.length > 1 ? `${parts.slice(-2).join(".")}()` : `${node.name}()`;
}

function NodePanel({
  reviewId,
  node,
  graph,
  findings,
  onSelect,
}: {
  reviewId: string;
  node: GraphNode;
  graph: CodeGraphJson;
  findings: Finding[];
  onSelect: (id: string) => void;
}) {
  const source = useQuery(node.file ? `source:${reviewId}:${node.file}` : null, () =>
    api.source(reviewId, node.file ?? ""),
  );
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const incoming = graph.edges.filter((e) => e.target === node.id && e.kind !== "defines");
  const outgoing = graph.edges.filter((e) => e.source === node.id && e.kind !== "defines");
  const own = findingsIn(node, findings);
  const rel = (ids: { id: string; kind: string }[]) =>
    ids.map(({ id, kind }) => {
      const other = byId.get(id);
      return other ? (
        <li key={`${id}-${kind}`}>
          <button className="linkish" onClick={() => onSelect(id)}>
            {shortName(other)}
          </button>
          <span className="muted"> {kind}</span>
        </li>
      ) : null;
    });

  return (
    <aside className="node-panel" aria-label={`Details for ${node.name}`}>
      <p className="np-kind">{KIND_LABEL[node.kind] ?? node.kind}</p>
      <h2>{node.name}</h2>
      {node.file ? (
        <p className="np-loc">
          {node.file}
          {node.line_start ? `:${node.line_start}` : ""}
        </p>
      ) : null}
      {node.meta.changed ? <p className="np-changed">Changed in this review</p> : null}
      {own.length ? (
        <ul className="np-findings">
          {own.map((f) => (
            <li key={f.id}>
              <SeverityMark severity={f.severity} />
              <button
                className="linkish"
                onClick={() => navigate(`/reviews/${reviewId}/findings/${f.id}`)}
              >
                <Inline text={f.title} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="np-rel">
        {incoming.length ? (
          <div>
            <h3>Used by</h3>
            <ul>{rel(incoming.map((e) => ({ id: e.source, kind: e.kind })))}</ul>
          </div>
        ) : null}
        {outgoing.length ? (
          <div>
            <h3>Uses</h3>
            <ul>{rel(outgoing.map((e) => ({ id: e.target, kind: e.kind })))}</ul>
          </div>
        ) : null}
      </div>
      {source.data && node.line_start ? (
        <CodeView
          path={node.file ?? ""}
          content={source.data.content}
          start={node.line_start}
          end={Math.min(node.line_end ?? node.line_start, node.line_start + 40)}
        />
      ) : null}
    </aside>
  );
}

function NodeBox({
  n,
  selected,
  findings,
  onSelect,
}: {
  n: LaidOutNode;
  selected: boolean;
  findings: Finding[];
  onSelect: () => void;
}) {
  const own = findingsIn(n.node, findings);
  const worst =
    own.find((f) => f.severity === "high") ?? own.find((f) => f.severity === "medium") ?? own[0];
  const label = shortName(n.node);
  return (
    <g
      className={`gnode gnode-${n.node.kind} ${n.node.meta.changed ? "gnode-changed" : ""} ${selected ? "gnode-selected" : ""}`}
      transform={`translate(${n.x},${n.y})`}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
      role="button"
      tabIndex={0}
      aria-label={`${KIND_LABEL[n.node.kind] ?? n.node.kind} ${n.node.name}`}
    >
      <rect
        width={n.w}
        height={n.h}
        rx={n.node.kind === "endpoint" ? 22 : n.node.kind === "database" ? 4 : 8}
      />
      <text x={12} y={18} className="gkind">
        {KIND_LABEL[n.node.kind] ?? n.node.kind}
      </text>
      <text x={12} y={34} className="glabel">
        {label.length > 22 ? `${label.slice(0, 21)}…` : label}
      </text>
      {worst ? (
        <g transform={`translate(${n.w - 14},${14})`}>
          <circle r={9} className={`gbadge gbadge-${worst.severity}`} />
          <text textAnchor="middle" y={4} className="gbadge-text">
            {own.length}
          </text>
        </g>
      ) : null}
    </g>
  );
}

export function ArchitectureTab({ reviewId, findings }: { reviewId: string; findings: Finding[] }) {
  const graph = useQuery(`graph:${reviewId}`, () => api.graph(reviewId));
  const focus = useSearchParam("focus");
  const layout = useMemo(() => (graph.data ? layoutGraph(graph.data, 5) : null), [graph.data]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (graph.error) return <ErrorNote error={graph.error} />;
  if (!graph.data || !layout) return <Spinner label="Laying out the code graph" />;
  if (layout.nodes.length === 0) {
    return (
      <Empty title="No code graph for this change">
        The changed files contain no functions or classes Sentinel could map.
      </Empty>
    );
  }
  const focused =
    selectedId ??
    (focus ? layout.nodes.find((n) => n.node.name === focus)?.node.id : undefined) ??
    layout.nodes.find((n) => n.node.meta.changed)?.node.id ??
    null;
  const selectedNode = graph.data.nodes.find((n) => n.id === focused) ?? null;
  const pos = new Map(layout.nodes.map((n) => [n.node.id, n]));
  const touching = new Set(
    layout.edges
      .filter((e) => e.source === focused || e.target === focused)
      .map((e) => `${e.source}>${e.target}`),
  );

  return (
    <div className="arch">
      <div className="arch-canvas">
        <p className="arch-caption">
          The changed code (outlined), what calls it and what it calls, the endpoints that reach it
          and the data it touches. Select a node to see its source.
        </p>
        <div className="arch-scroll">
          <svg
            width={layout.width}
            height={layout.height}
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            role="img"
            aria-label="Code graph of the change"
          >
            <defs>
              <marker
                id="arrow"
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M0,0 L10,5 L0,10 z" className="garrow" />
              </marker>
            </defs>
            {layout.edges.map((e) => (
              <path
                key={`${e.source}>${e.target}>${e.kind}`}
                d={e.path}
                className={`gedge gedge-${e.kind} ${touching.has(`${e.source}>${e.target}`) ? "gedge-hot" : ""}`}
                markerEnd="url(#arrow)"
              />
            ))}
            {layout.nodes.map((n) => (
              <NodeBox
                key={n.node.id}
                n={n}
                selected={n.node.id === focused}
                findings={findings}
                onSelect={() => setSelectedId(n.node.id)}
              />
            ))}
          </svg>
        </div>
        <ul className="arch-legend" aria-label="Legend">
          <li>
            <span className="lg lg-calls" />
            calls
          </li>
          <li>
            <span className="lg lg-routes" />
            routes to
          </li>
          <li>
            <span className="lg lg-data" />
            reads / writes
          </li>
          <li>
            <span className="lg lg-tests" />
            tests
          </li>
        </ul>
        <p className="sr-only">{pos.size} nodes</p>
      </div>
      {selectedNode ? (
        <NodePanel
          reviewId={reviewId}
          node={selectedNode}
          graph={graph.data}
          findings={findings}
          onSelect={setSelectedId}
        />
      ) : null}
    </div>
  );
}
