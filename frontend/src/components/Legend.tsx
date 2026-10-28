import { ALL_EDGE_TYPES, EDGE_STYLE, graphColor, KINDS, type Theme } from "../graph/style";

const ENTRIES = ["activity", "fragment", "composable", "viewmodel", "repository", "dao", "worker", "service", "receiver",
  "class", "interface", "object", "enum", "annotation", "function", "constructor", "package", "file", "layout"];

export default function Legend({ theme }: { theme: Theme }) {
  return (
    <div className="legend">
      <h4>Node types</h4>
      <div className="legend-grid">
        {ENTRIES.map((k) => {
          const kd = KINDS[k];
          const color = graphColor(kd.color, theme);
          return (
            <div key={k} className="legend-item">
              <span className="legend-icon" style={{ background: `${color}22` }}><kd.Icon size={14} color={color} /></span>
              {kd.label}
            </div>
          );
        })}
      </div>
      <h4>Relationships</h4>
      <div className="legend-grid">
        {ALL_EDGE_TYPES.map((t) => (
          <div key={t} className="legend-item">
            <svg width="30" height="8"><line x1="0" y1="4" x2="30" y2="4" stroke={graphColor(EDGE_STYLE[t].color, theme)} strokeWidth="2" strokeDasharray={EDGE_STYLE[t].dash} /></svg>
            {EDGE_STYLE[t].label}
          </div>
        ))}
        <div className="legend-item"><svg width="30" height="8"><line x1="0" y1="4" x2="30" y2="4" stroke="#94a3b8" strokeWidth="2" strokeDasharray="5 4" /></svg>Inferred (heuristic)</div>
      </div>
      <p className="legend-note">Unresolved and external (SDK/library) targets are never drawn as edges; they appear in the node inspector.</p>
    </div>
  );
}
