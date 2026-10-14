import dagre from "@dagrejs/dagre";
import type { GEdge, GNode } from "../types/graph";

export const NODE_W = 230;
export const NODE_H = 66;

export type Direction = "LR" | "TB";

// Layered, directional layout: ranks follow edge direction, so containment and
// dependency flows read left-to-right (or top-to-bottom) without force-directed tangles.
export function layout(nodes: GNode[], edges: GEdge[], dir: Direction): Record<string, { x: number; y: number }> {
  if (nodes.length && nodes.every((n) => n.level !== undefined)) {
    const layers = new Map<number, GNode[]>();
    nodes.forEach((n) => {
      const level = n.level ?? 0;
      layers.set(level, [...(layers.get(level) ?? []), n]);
    });
    const out: Record<string, { x: number; y: number }> = {};
    [...layers.entries()].sort(([a], [b]) => a - b).forEach(([level, layer]) => {
      layer.sort((a, b) => a.qualified_name.localeCompare(b.qualified_name));
      layer.forEach((n, index) => {
        out[n.id] = dir === "LR"
          ? { x: level * (NODE_W + 120), y: index * (NODE_H + 36) }
          : { x: index * (NODE_W + 50), y: level * (NODE_H + 100) };
      });
    });
    return out;
  }

  const g = new dagre.graphlib.Graph({ multigraph: false });
  g.setGraph({ rankdir: dir, nodesep: 28, ranksep: 90, edgesep: 14, ranker: "network-simplex", marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  const ids = new Set(nodes.map((n) => n.id));
  const seen = new Set<string>();
  edges.forEach((e) => {
    if (!e.target || !ids.has(e.source) || !ids.has(e.target) || e.source === e.target) return;
    const k = `${e.source}>${e.target}`;
    if (seen.has(k)) return;
    seen.add(k);
    g.setEdge(e.source, e.target, { weight: e.type === "CONTAINS" ? 3 : 1 });
  });
  dagre.layout(g);
  const out: Record<string, { x: number; y: number }> = {};
  nodes.forEach((n) => {
    const p = g.node(n.id);
    out[n.id] = { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 };
  });
  return out;
}
