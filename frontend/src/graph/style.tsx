import type { ComponentType } from "react";
import {
  AtSign, Box, Cable, Cog, Database, FileCode, FolderGit2, Hammer, LayoutTemplate, ListOrdered,
  Package, Plug, Radio, SquareFunction, Timer, Warehouse, Layers, Cuboid,
} from "lucide-react";
import { siAndroid, siGithub, siJetpackcompose, siKotlin, siOpenjdk, siPython } from "simple-icons";
import type { EdgeType, GNode } from "../types/graph";

export type IconProps = { size?: number; color?: string };
export type Theme = "light" | "dark";

const brand = (icon: { path: string; hex: string }) =>
  function BrandIcon({ size = 18, color }: IconProps) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" role="img" aria-hidden="true">
        <path d={icon.path} fill={color ?? `#${icon.hex}`} />
      </svg>
    );
  };

export const GithubLogo = brand(siGithub);
export const AndroidLogo = brand(siAndroid);
export const ComposeLogo = brand(siJetpackcompose);
export const KotlinLogo = brand(siKotlin);
export const JavaLogo = brand(siOpenjdk);
export const PythonLogo = brand(siPython);

type Lucide = ComponentType<{ size?: number; color?: string }>;
const lucide = (I: Lucide) => ({ size = 18, color }: IconProps) => <I size={size} color={color} />;

export interface Kind { key: string; label: string; color: string; Icon: ComponentType<IconProps> }

export function graphColor(color: string, theme: Theme): string {
  if (theme !== "light") return color;
  const match = /^#([0-9a-f]{6})$/i.exec(color);
  if (!match) return color;
  const value = Number.parseInt(match[1], 16);
  const channel = (shift: number) => Math.round(((value >> shift) & 0xff) * 0.58);
  return `#${[channel(16), channel(8), channel(0)].map((part) => part.toString(16).padStart(2, "0")).join("")}`;
}

export const KINDS: Record<string, Kind> = {
  activity: { key: "activity", label: "Activity", color: "#3ddc84", Icon: AndroidLogo },
  fragment: { key: "fragment", label: "Fragment", color: "#2fb8a0", Icon: lucide(Cuboid) },
  service: { key: "service", label: "Service", color: "#e0a030", Icon: lucide(Cog) },
  receiver: { key: "receiver", label: "BroadcastReceiver", color: "#d9822b", Icon: lucide(Radio) },
  viewmodel: { key: "viewmodel", label: "ViewModel", color: "#7c6cf0", Icon: lucide(Layers) },
  repository: { key: "repository", label: "Repository", color: "#3b82f6", Icon: lucide(Warehouse) },
  dao: { key: "dao", label: "DAO", color: "#0ea5b7", Icon: lucide(Database) },
  worker: { key: "worker", label: "Worker", color: "#c27ac0", Icon: lucide(Timer) },
  composable: { key: "composable", label: "Composable", color: "#4285f4", Icon: ComposeLogo },
  class: { key: "class", label: "Class", color: "#64748b", Icon: lucide(Box) },
  interface: { key: "interface", label: "Interface", color: "#a78bfa", Icon: lucide(Plug) },
  object: { key: "object", label: "Object", color: "#94a3b8", Icon: lucide(Cable) },
  enum: { key: "enum", label: "Enum", color: "#f59e0b", Icon: lucide(ListOrdered) },
  annotation: { key: "annotation", label: "Annotation", color: "#ec4899", Icon: lucide(AtSign) },
  function: { key: "function", label: "Function / Method", color: "#22c55e", Icon: lucide(SquareFunction) },
  constructor: { key: "constructor", label: "Constructor", color: "#84cc16", Icon: lucide(Hammer) },
  package: { key: "package", label: "Package", color: "#eab308", Icon: lucide(Package) },
  file: { key: "file", label: "File", color: "#cbd5e1", Icon: lucide(FileCode) },
  layout: { key: "layout", label: "XML layout", color: "#f97316", Icon: lucide(LayoutTemplate) },
  repo: { key: "repo", label: "Repository root", color: "#e2e8f0", Icon: lucide(FolderGit2) },
};

const ROLE_PRIORITY = ["activity", "fragment", "composable", "viewmodel", "dao", "repository", "worker", "service", "receiver"];

export function kindOf(n: GNode): Kind {
  const role = ROLE_PRIORITY.find((r) => n.roles.includes(r));
  if (role) return KINDS[role];
  if (n.type === "repository") return KINDS.repo;
  return KINDS[n.type] ?? KINDS.class;
}

export function typeLabel(n: GNode): string {
  const base = KINDS[n.type]?.label ?? n.type;
  const roles = n.roles.map((r) => KINDS[r]?.label ?? r);
  return roles.length ? `${roles.join(" · ")} (${base})` : base;
}

export const LanguageLogo = ({ lang, size = 12 }: { lang?: string | null; size?: number }) =>
  lang === "kotlin" ? <KotlinLogo size={size} />
    : lang === "java" ? <JavaLogo size={size} />
      : lang === "python" ? <PythonLogo size={size} /> : null;

export const EDGE_STYLE: Record<EdgeType, { color: string; label: string; dash?: string }> = {
  CONTAINS: { color: "#475569", label: "Contains" },
  IMPORTS: { color: "#94a3b8", label: "Imports", dash: "2 4" },
  CALLS: { color: "#22c55e", label: "Calls" },
  EXTENDS: { color: "#a78bfa", label: "Extends" },
  IMPLEMENTS: { color: "#c084fc", label: "Implements", dash: "6 3" },
  OVERRIDES: { color: "#f472b6", label: "Overrides", dash: "6 3" },
  USES: { color: "#38bdf8", label: "Uses" },
  INJECTS: { color: "#f59e0b", label: "Injects" },
  NAVIGATES_TO: { color: "#3ddc84", label: "Navigates to" },
  DECLARES: { color: "#64748b", label: "Declares", dash: "2 4" },
};

export const ALL_EDGE_TYPES = Object.keys(EDGE_STYLE) as EdgeType[];
export const DEFAULT_EDGE_TYPES: EdgeType[] = ["CALLS", "EXTENDS", "IMPLEMENTS", "OVERRIDES", "USES", "INJECTS", "NAVIGATES_TO", "CONTAINS"];
export const NODE_FILTERS = ["package", "file", "class", "interface", "object", "enum", "annotation", "function", "constructor", "layout"] as const;
