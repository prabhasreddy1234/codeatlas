import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { MessageCircle, RotateCcw, Send, Sparkles, X } from "lucide-react";
import type { GEdge, GNode, GraphMeta } from "../types/graph";

interface Props {
  repository: string | null;
  graph: GraphMeta | null;
  nodes: GNode[];
  edges: GEdge[];
}

interface ChatMessage {
  id: number;
  role: "assistant" | "user";
  content: string;
}

const suggestions = [
  "How is this codebase organized?",
  "Show me the main entry points",
  "How are the key components connected?",
];

function nodeLabel(node: GNode): string {
  const location = node.file_path
    ? ` — ${node.file_path}${node.start_line ? `:${node.start_line}` : ""}`
    : "";
  const roles = node.roles.length ? ` (${node.roles.join(", ")})` : "";
  return `• ${node.qualified_name || node.name}${roles}${location}`;
}

function answerQuestion(question: string, graph: GraphMeta | null, nodes: GNode[], edges: GEdge[]): string {
  if (!graph) {
    return "There isn’t a code graph loaded yet. Select a repository and branch, then generate its code graph to explore it here.";
  }

  const normalized = question.toLowerCase();
  const loadedNodes = new Map(nodes.map((node) => [node.id, node]));
  const countsByType = nodes.reduce<Record<string, number>>((counts, node) => {
    counts[node.type] = (counts[node.type] ?? 0) + 1;
    return counts;
  }, {});

  if (/organiz|structure|overview|codebase|repository/.test(normalized)) {
    const summary = Object.entries(countsByType)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([type, count]) => `${count} ${type}${count === 1 ? "" : "s"}`)
      .join(", ");
    const sourceFiles = graph.stats.source_files;
    const totalNodes = graph.stats.nodes;
    return [
      `${graph.repository.owner}/${graph.repository.name} (${graph.branch}) has ${typeof sourceFiles === "number" ? `${sourceFiles} indexed source files` : "an indexed code graph"}.`,
      summary ? `Among the ${nodes.length} loaded nodes are ${summary}.` : "",
      typeof totalNodes === "number" && totalNodes > nodes.length
        ? "The graph view is partial, so this summary covers the nodes currently loaded."
        : "",
    ].filter(Boolean).join(" ");
  }

  if (/entry.?point|start|launch|main function/.test(normalized)) {
    const entryNodes = nodes.filter((node) => node.roles.some((role) =>
      ["activity", "service", "receiver", "worker"].includes(role),
    ));
    if (entryNodes.length) {
      return `Likely application entry points identified by their code roles:\n${entryNodes.slice(0, 6).map(nodeLabel).join("\n")}`;
    }

    const callCounts = new Map<string, number>();
    edges.filter((edge) => edge.type === "CALLS" && edge.target).forEach((edge) => {
      callCounts.set(edge.source, (callCounts.get(edge.source) ?? 0) + 1);
    });
    const callers = [...callCounts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([id, count]) => {
        const node = loadedNodes.get(id);
        return node ? `${nodeLabel(node)} (${count} outgoing call${count === 1 ? "" : "s"})` : null;
      })
      .filter((item): item is string => item !== null);
    return callers.length
      ? `No explicit entry-point role was found. These loaded nodes have the most outgoing calls, which can help you find starting points:\n${callers.join("\n")}`
      : "No entry-point roles or call relationships are available in the loaded graph.";
  }

  if (/connect|relationship|depend|call|flow|interact/.test(normalized)) {
    const examples = edges.slice(0, 4).flatMap((edge) => {
      const source = loadedNodes.get(edge.source);
      const target = edge.target ? loadedNodes.get(edge.target) : undefined;
      return source && target
        ? [`${source.qualified_name || source.name} → ${target.qualified_name || target.name} (${edge.type.toLowerCase()})`]
        : [];
    });
    const relationshipCounts = edges.reduce<Record<string, number>>((counts, edge) => {
      counts[edge.type] = (counts[edge.type] ?? 0) + 1;
      return counts;
    }, {});
    const summary = Object.entries(relationshipCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([type, count]) => `${type.toLowerCase()}: ${count}`)
      .join(", ");
    return summary
      ? `The loaded graph contains ${edges.length} relationships (${summary}).${examples.length ? ` For example:\n${examples.join("\n")}` : ""}`
      : "There are no relationships loaded yet. Expand a node in the graph to load its connections.";
  }

  const matches = nodes.filter((node) => {
    const searchable = `${node.name} ${node.qualified_name} ${node.file_path ?? ""}`.toLowerCase();
    return normalized.includes(node.name.toLowerCase()) || node.name.toLowerCase().includes(normalized) ||
      normalized.split(/\W+/).filter((word) => word.length > 2).some((word) => searchable.includes(word));
  }).slice(0, 5);
  if (matches.length) {
    const firstMatchIds = new Set(matches.map((node) => node.id));
    const related = edges.flatMap((edge) => {
      const source = loadedNodes.get(edge.source);
      const target = edge.target ? loadedNodes.get(edge.target) : undefined;
      if (!source || !target || (!firstMatchIds.has(source.id) && !firstMatchIds.has(target.id))) return [];
      return [`${source.name} → ${target.name} (${edge.type.toLowerCase()})`];
    }).slice(0, 5);
    return `I found these matching nodes in the loaded graph:\n${matches.map(nodeLabel).join("\n")}${related.length ? `\n\nLoaded connections:\n${related.join("\n")}` : ""}`;
  }

  return "I can answer from the loaded graph about its structure, likely entry points, relationships, and named code elements. Try one of the suggested questions or ask about a class, function, or file.";
}

export default function ChatPanel({ repository, graph, nodes, edges }: Props) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const messageId = useRef(1);
  const bodyRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const projectName = graph?.repository.name ?? repository?.split("/").pop() ?? "your project";

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, open]);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  const sendMessage = (text: string) => {
    const content = text.trim();
    if (!content) return;
    const userMessage: ChatMessage = { id: messageId.current++, role: "user", content };
    const assistantMessage: ChatMessage = {
      id: messageId.current++,
      role: "assistant",
      content: answerQuestion(content, graph, nodes, edges),
    };
    setMessages((current) => [...current, userMessage, assistantMessage]);
    setDraft("");
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    sendMessage(draft);
  };

  const onInputKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage(draft);
    }
  };

  return (
    <div className="chat-widget">
      {open && (
        <section className="chat-panel" aria-label="Codebase chat" aria-live="polite">
          <header className="chat-header">
            <div className="chat-title">
              <span className="chat-title-icon"><MessageCircle size={17} /></span>
              <div>
                <h2>Ask CodeAtlas</h2>
                <p>Explore your codebase</p>
              </div>
            </div>
            <div className="chat-header-actions">
              <button
                className="chat-icon-button"
                type="button"
                aria-label="Start a new chat"
                title="Start a new chat"
                onClick={() => { setMessages([]); setDraft(""); }}
              >
                <RotateCcw size={15} />
              </button>
              <button
                className="chat-icon-button"
                type="button"
                aria-label="Close chat"
                title="Close chat"
                onClick={() => setOpen(false)}
              >
                <X size={17} />
              </button>
            </div>
          </header>

          <div className="chat-body" ref={bodyRef} role="log" aria-label="Chat messages" aria-live="polite">
            {messages.length === 0 && (
              <div className="chat-welcome">
                <span className="chat-welcome-icon"><Sparkles size={18} /></span>
                <h3>Welcome!</h3>
                <p>You can ask me anything about <strong>{projectName}</strong>.</p>
              </div>
            )}
            <div className="chat-messages">
              {messages.map((message) => (
                <article className={`chat-message ${message.role}`} key={message.id}>
                  {message.role === "assistant" && <span className="chat-message-icon"><Sparkles size={13} /></span>}
                  <p>{message.content}</p>
                </article>
              ))}
            </div>
            {messages.length === 0 && (
              <div className="chat-suggestions" aria-label="Suggested questions">
                {suggestions.map((suggestion) => (
                  <button
                    className="chat-suggestion"
                    key={suggestion}
                    type="button"
                    onClick={() => sendMessage(suggestion)}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            )}
          </div>

          <form className="chat-composer" onSubmit={onSubmit}>
            <textarea
              ref={inputRef}
              aria-label="Message"
              placeholder="Ask about this codebase…"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onInputKeyDown}
              rows={2}
            />
            <button className="chat-send" type="submit" aria-label="Send message" disabled={!draft.trim()}>
              <Send size={16} />
            </button>
          </form>
          <p className="chat-note">Answers are based on the loaded graph; no AI service is connected.</p>
        </section>
      )}

      {!open && (
        <button
          className="chat-fab"
          type="button"
          aria-label="Open codebase chat"
          title="Ask CodeAtlas"
          onClick={() => setOpen(true)}
        >
          <MessageCircle size={22} />
          <span>Ask CodeAtlas</span>
        </button>
      )}
    </div>
  );
}
