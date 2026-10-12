import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDown, Search } from "lucide-react";

interface Props<T> {
  items: T[];
  value: T | null;
  getKey: (t: T) => string;
  getText: (t: T) => string;
  render: (t: T) => ReactNode;
  onChange: (t: T) => void;
  placeholder: string;
  disabled?: boolean;
  loading?: boolean;
}

export default function Combobox<T>({ items, value, getKey, getText, render, onChange, placeholder, disabled, loading }: Props<T>) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const filtered = useMemo(() => {
    const ql = query.trim().toLowerCase();
    return (ql ? items.filter((i) => getText(i).toLowerCase().includes(ql)) : items).slice(0, 200);
  }, [items, query, getText]);
  return (
    <div className="combo" ref={ref}>
      <button className="combo-btn" disabled={disabled} onClick={() => setOpen((o) => !o)} type="button">
        <span className="combo-val">{loading ? "Loading…" : value ? render(value) : <span className="muted">{placeholder}</span>}</span>
        <ChevronDown size={16} />
      </button>
      {open && (
        <div className="combo-pop">
          <div className="combo-search"><Search size={14} /><input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search…" /></div>
          <div className="combo-list">
            {filtered.length === 0 && <div className="muted pad">No matches</div>}
            {filtered.map((i) => (
              <div key={getKey(i)} className={`combo-item${value && getKey(value) === getKey(i) ? " active" : ""}`}
                   onClick={() => { onChange(i); setOpen(false); setQuery(""); }}>
                {render(i)}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
