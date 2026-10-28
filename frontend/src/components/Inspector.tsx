import { EyeOff, ListTree, X } from "lucide-react";
import type { EdgeView, NodeDetails } from "../types/graph";
import { EDGE_STYLE, graphColor, LanguageLogo, kindOf, typeLabel, type Theme } from "../graph/style";

interface Props {
  details: NodeDetails | null;
  loading: boolean;
  onClose: () => void;
  onMembers: (id: string) => void;
  onFocus: (id: string) => void;
  onSelect: (id: string) => void;
  theme: Theme;
}

function Group({ title, edges, onSelect, outgoing, theme }: { title: string; edges: EdgeView[]; onSelect: (id: string) => void; outgoing: boolean; theme: Theme }) {
  if (!edges.length) return null;
  const byType = new Map<string, EdgeView[]>();
  edges.forEach((e) => byType.set(e.type, [...(byType.get(e.type) ?? []), e]));
  return (
    <section>
      <h4>{title} ({edges.length})</h4>
      {[...byType.entries()].map(([type, list]) => (
        <div key={type} className="rel-group">
          <div className="rel-type" style={{ color: graphColor(EDGE_STYLE[type as keyof typeof EDGE_STYLE]?.color ?? "var(--text)", theme) }}>
            {EDGE_STYLE[type as keyof typeof EDGE_STYLE]?.label ?? type}
          </div>
          {list.slice(0, 60).map((e) => (
            <div key={e.id} className="rel-row">
              {e.other ? (
                <button className="link" onClick={() => onSelect(e.other!.id)} title={e.other.qualified_name}>{e.other.name}</button>
              ) : (
                <span className="unresolved-name" title={e.provenance}>{e.target_name ?? "?"}</span>
              )}
              <span className={`badge ${e.status}`} title={e.provenance}>{e.status}</span>
              {e.line ? <span className="muted">:{e.line}{e.count > 1 ? ` ×${e.count}` : ""}</span> : null}
              {!e.other && e.provenance && outgoing ? <div className="why">{e.provenance}</div> : null}
            </div>
          ))}
          {list.length > 60 && <div className="muted">…and {list.length - 60} more</div>}
        </div>
      ))}
    </section>
  );
}

export default function Inspector({ details, loading, onClose, onMembers, onFocus, onSelect, theme }: Props) {
  if (!details) {
    return (
      <aside className="inspector empty">
        {loading ? <p>Loading…</p> : <p>Select a node to inspect its source location and relationships.</p>}
      </aside>
    );
  }
  const n = details.node;
  const kind = kindOf(n);
  const isTypeLike = ["class", "interface", "object", "enum", "annotation"].includes(n.type);
  return (
    <aside className="inspector">
      <div className="insp-head">
        <div className="cn-icon" style={{ background: `${graphColor(kind.color, theme)}22` }}><kind.Icon size={22} color={graphColor(kind.color, theme)} /></div>
        <div>
          <div className="insp-name">{n.name}</div>
          <div className="cn-type">{typeLabel(n)} <LanguageLogo lang={n.language} theme={theme} /></div>
        </div>
        <button className="icon-btn" onClick={onClose} title="Close"><X size={16} /></button>
      </div>
      <dl className="meta">
        <dt>Qualified name</dt><dd className="mono">{n.qualified_name}</dd>
        {n.signature && (<><dt>Signature</dt><dd className="mono">{n.signature}</dd></>)}
        {n.file_path && (<><dt>Source</dt><dd className="mono">{n.file_path}{n.start_line ? `:${n.start_line}${n.end_line && n.end_line !== n.start_line ? `-${n.end_line}` : ""}` : ""}</dd></>)}
        {n.annotations.length > 0 && (<><dt>Annotations</dt><dd>{n.annotations.map((a) => `@${a}`).join(" ")}</dd></>)}
        {n.modifiers.length > 0 && (<><dt>Modifiers</dt><dd>{n.modifiers.join(" ")}</dd></>)}
        {n.roles.length > 0 && (<><dt>Role evidence</dt><dd>{n.roles.map((r) => (<div key={r}><b>{r}</b>: {n.role_evidence[r]}</div>))}</dd></>)}
        {details.parent && (<><dt>Contained in</dt><dd><button className="link" onClick={() => onSelect(details.parent!.id)}>{details.parent.name}</button></dd></>)}
      </dl>
      <div className="actions">
        {(isTypeLike || n.type === "package" || n.type === "file") && (
          <button onClick={() => onMembers(n.id)} title="Show contained declarations"><ListTree size={14} /> Contents</button>
        )}
        <button onClick={() => onFocus(n.id)} title="Hide everything not connected to this node"><EyeOff size={14} /> Hide unrelated</button>
      </div>
      <Group title="Outgoing" edges={details.outgoing} onSelect={onSelect} outgoing theme={theme} />
      <Group title="Incoming" edges={details.incoming} onSelect={onSelect} outgoing={false} theme={theme} />
      {details.children.length > 0 && (
        <section>
          <h4>Declares ({details.children.length})</h4>
          {details.children.slice(0, 80).map((c) => (
            <div key={c.id} className="rel-row">
              <button className="link" onClick={() => onSelect(c.id)}>{c.signature ?? c.name}</button>
              {c.start_line ? <span className="muted">:{c.start_line}</span> : null}
            </div>
          ))}
        </section>
      )}
    </aside>
  );
}
