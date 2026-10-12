import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { GNode } from "../types/graph";
import { LanguageLogo, kindOf, typeLabel } from "../graph/style";

export type CodeNodeData = {
  node: GNode;
  dir: "LR" | "TB";
  selected: boolean;
  dimmed: boolean;
  matched: boolean;
  owner?: string;
};
export type CodeFlowNode = Node<CodeNodeData, "code">;

export default function CodeNode({ data }: NodeProps<CodeFlowNode>) {
  const { node, dir, selected, dimmed, matched, owner } = data;
  const kind = kindOf(node);
  const context =
    node.type === "package" ? null
      : node.type === "file" ? node.package
      : node.type === "function" || node.type === "constructor" ? owner ?? node.package
      : node.package;
  return (
    <div
      className={`code-node${selected ? " selected" : ""}${dimmed ? " dimmed" : ""}${matched ? " matched" : ""}`}
      style={{ borderLeftColor: kind.color }}
      title={node.qualified_name}
    >
      <Handle type="target" position={dir === "LR" ? Position.Left : Position.Top} />
      <div className="cn-icon" style={{ background: `${kind.color}22`, color: kind.color }}>
        <kind.Icon size={20} color={kind.color} />
      </div>
      <div className="cn-body">
        <div className="cn-name">
          {node.name}
          {node.type === "function" || node.type === "constructor" ? "()" : ""}
        </div>
        <div className="cn-type">
          {typeLabel(node)} <LanguageLogo lang={node.language} />
        </div>
        {context && <div className="cn-ctx">{context}</div>}
      </div>
      <Handle type="source" position={dir === "LR" ? Position.Right : Position.Bottom} />
    </div>
  );
}
