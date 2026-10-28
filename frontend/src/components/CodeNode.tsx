import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { GNode } from "../types/graph";
import { graphColor, LanguageLogo, kindOf, typeLabel, type Theme } from "../graph/style";

export type CodeNodeData = {
  node: GNode;
  dir: "LR" | "TB";
  selected: boolean;
  dimmed: boolean;
  matched: boolean;
  owner?: string;
  theme: Theme;
};
export type CodeFlowNode = Node<CodeNodeData, "code">;

export default function CodeNode({ data }: NodeProps<CodeFlowNode>) {
  const { node, dir, selected, dimmed, matched, owner, theme } = data;
  const kind = kindOf(node);
  const color = graphColor(kind.color, theme);
  const context =
    node.type === "package" ? null
      : node.type === "file" ? node.package
      : node.type === "function" || node.type === "constructor" ? owner ?? node.package
      : node.package;
  return (
    <div
      className={`code-node${selected ? " selected" : ""}${dimmed ? " dimmed" : ""}${matched ? " matched" : ""}`}
      style={{ borderLeftColor: color }}
      title={node.qualified_name}
    >
      <Handle type="target" position={dir === "LR" ? Position.Left : Position.Top} />
      <div className="cn-icon" style={{ background: `${color}22`, color }}>
        <kind.Icon size={20} color={color} />
      </div>
      <div className="cn-body">
        <div className="cn-header">
          <span className="cn-role" style={{ color, borderColor: `${color}66`, background: `${color}14` }}>
            {kind.label}
          </span>
          {node.type !== "package" && node.type !== "file" && node.language && <LanguageLogo lang={node.language} size={11} theme={theme} />}
        </div>
        <div className="cn-name">
          {node.name}
          {node.type === "function" || node.type === "constructor" ? "()" : ""}
        </div>
        <div className="cn-meta">
          <span className="cn-type">{typeLabel(node)}</span>
        </div>
        {context && <div className="cn-ctx">{context}</div>}
      </div>
      <Handle type="source" position={dir === "LR" ? Position.Right : Position.Bottom} />
    </div>
  );
}
