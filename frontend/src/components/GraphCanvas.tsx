import { useEffect, useMemo, useRef } from "react";
import {
  Background, BackgroundVariant, ControlButton, Controls, MarkerType, ReactFlow,
  useReactFlow, type Edge,
} from "@xyflow/react";
import { Maximize, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import type { GEdge, GNode } from "../types/graph";
import { layout, type Direction } from "../graph/layout";
import { EDGE_STYLE } from "../graph/style";
import CodeNode, { type CodeFlowNode } from "./CodeNode";

const nodeTypes = { code: CodeNode };

interface Props {
  nodes: GNode[];
  edges: GEdge[];
  selectedId: string | null;
  matchIds: Set<string>;
  direction: Direction;
  onSelect: (id: string | null) => void;
  onReset: () => void;
}

export default function GraphCanvas({ nodes, edges, selectedId, matchIds, direction, onSelect, onReset }: Props) {
  const rf = useReactFlow();
  const positions = useMemo(() => layout(nodes, edges, direction), [nodes, edges, direction]);

  const related = useMemo(() => {
    if (!selectedId) return null;
    const s = new Set([selectedId]);
    edges.forEach((e) => {
      if (e.source === selectedId && e.target) s.add(e.target);
      if (e.target === selectedId) s.add(e.source);
    });
    return s;
  }, [edges, selectedId]);

  const flowNodes: CodeFlowNode[] = useMemo(
    () => nodes.map((n) => ({
      id: n.id, type: "code", position: positions[n.id] ?? { x: 0, y: 0 },
      data: {
        node: n, dir: direction, selected: n.id === selectedId,
        dimmed: related ? !related.has(n.id) : false,
        matched: matchIds.has(n.id), owner: n.qualified_name.split(".").slice(-2, -1)[0],
      },
    })),
    [nodes, positions, direction, selectedId, related, matchIds],
  );

  const flowEdges: Edge[] = useMemo(() => {
    const ids = new Set(nodes.map((n) => n.id));
    return edges.filter((e) => e.target && ids.has(e.source) && ids.has(e.target)).map((e) => {
      const st = EDGE_STYLE[e.type];
      const active = !selectedId || e.source === selectedId || e.target === selectedId;
      const dashed = e.status === "inferred" ? "5 4" : st.dash;
      return {
        id: e.id, source: e.source, target: e.target as string, type: "smoothstep",
        label: e.count > 1 && e.type !== "CONTAINS" ? `${st.label} ×${e.count}` : undefined,
        data: { type: e.type },
        markerEnd: { type: MarkerType.ArrowClosed, color: st.color, width: 16, height: 16 },
        style: { stroke: st.color, strokeWidth: active ? 1.8 : 1, strokeDasharray: dashed, opacity: active ? 0.95 : 0.2 },
        labelStyle: { fontSize: 10, fill: "#e2e8f0", fontWeight: 600 },
        labelBgStyle: { fill: "rgba(15, 23, 42, 0.9)", stroke: "rgba(148, 163, 184, 0.2)", strokeWidth: 1 },
        labelBgPadding: [6, 4],
      } as Edge;
    });
  }, [edges, nodes, selectedId]);

  const key = useMemo(() => nodes.map((n) => n.id).join(",") + direction, [nodes, direction]);
  const previousKey = useRef(key);
  useEffect(() => {
    const graphChanged = previousKey.current !== key;
    previousKey.current = key;
    const t = setTimeout(() => {
      if (!graphChanged && selectedId) {
        const node = rf.getNode(selectedId);
        if (node) {
          rf.fitView({ nodes: [node], padding: 0.5, duration: 350, maxZoom: 1.4 });
          return;
        }
      }
      rf.fitView({ padding: 0.2, duration: 300, maxZoom: 1.1 });
    }, 80);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, selectedId]);

  return (
    <ReactFlow
      nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} minZoom={0.05} maxZoom={2}
      nodesConnectable={false} nodesDraggable edgesFocusable={false} fitView
      onNodeClick={(_, n) => onSelect(n.id)} onPaneClick={() => onSelect(null)}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1e293b" />
      <Controls showInteractive={false} showZoom={false} showFitView={false} orientation="horizontal">
        <ControlButton onClick={() => rf.zoomIn({ duration: 150 })} title="Zoom in"><ZoomIn size={14} /></ControlButton>
        <ControlButton onClick={() => rf.zoomOut({ duration: 150 })} title="Zoom out"><ZoomOut size={14} /></ControlButton>
        <ControlButton onClick={() => rf.fitView({ padding: 0.2, duration: 300 })} title="Fit graph to screen"><Maximize size={14} /></ControlButton>
        <ControlButton onClick={onReset} title="Reset view (back to overview)"><RotateCcw size={14} /></ControlButton>
      </Controls>
    </ReactFlow>
  );
}
