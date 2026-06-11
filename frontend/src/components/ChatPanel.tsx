import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useChatStream } from "../hooks/useChatStream";
import { AnswerView } from "./AnswerView";
import { SourceList } from "./SourceList";
import type { CorpusOut } from "../types";

export function ChatPanel({
  conversationId,
  onConversationCreated,
}: {
  conversationId: string | null;
  onConversationCreated: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [selectedCorpora, setSelectedCorpora] = useState<string[]>([]);
  const [highlighted, setHighlighted] = useState<number | null>(null);

  const { data: corpora } = useQuery({ queryKey: ["corpora"], queryFn: api.listCorpora });
  const { data: history } = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.getConversation(conversationId!),
    enabled: conversationId !== null,
  });

  const { state, send, reset } = useChatStream((meta) => {
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
    queryClient.invalidateQueries({ queryKey: ["conversation", meta.conversation_id] });
    if (conversationId === null) onConversationCreated(meta.conversation_id);
  });

  const streamedConvId = state.done?.conversation_id ?? null;
  useEffect(() => {
    // Keep the live stream card (with its sources panel) when the change is
    // just the newly-created conversation becoming active; reset otherwise.
    if (conversationId !== null && conversationId === streamedConvId) return;
    reset();
    setHighlighted(null);
  }, [conversationId, streamedConvId, reset]);

  // The streamed exchange is also persisted; don't render it twice.
  const allMessages = history?.messages ?? [];
  const messages =
    state.phase === "done" && conversationId === streamedConvId
      ? allMessages.slice(0, -2)
      : allMessages;

  const onCite = (n: number) => {
    setHighlighted(n);
    document.getElementById(`source-${n}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const ask = () => {
    const q = question.trim();
    if (q.length < 3 || state.phase === "loading" || state.phase === "streaming") return;
    setQuestion("");
    setHighlighted(null);
    void send(q, selectedCorpora, conversationId);
  };

  const showStream = state.phase !== "idle";

  return (
    <div className="flex h-full flex-1 overflow-hidden">
      <main className="flex flex-1 flex-col overflow-hidden">
        <div className="flex-1 space-y-4 overflow-y-auto p-6">
          {messages.map((m) => (
            <div key={m.id} className={m.role === "user" ? "text-right" : ""}>
              {m.role === "user" ? (
                <span className="inline-block max-w-xl rounded-2xl bg-indigo-600 px-4 py-2 text-left text-sm text-white">
                  {m.content}
                </span>
              ) : (
                <div className="max-w-2xl rounded-2xl border border-slate-200 bg-white p-4">
                  <AnswerView text={m.content} onCite={() => {}} />
                  {m.latency_ms !== null && (
                    <div className="mt-2 text-xs text-slate-400">{m.latency_ms} ms</div>
                  )}
                </div>
              )}
            </div>
          ))}

          {showStream && (
            <div className="max-w-2xl rounded-2xl border border-slate-200 bg-white p-4">
              {state.phase === "loading" && (
                <div className="text-sm text-slate-400">Retrieving sources…</div>
              )}
              {state.phase === "refused" && (
                <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
                  <strong>Cannot answer from the corpus.</strong> {state.refusalReason}
                </div>
              )}
              {state.phase === "error" && (
                <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{state.error}</div>
              )}
              {state.answer && <AnswerView text={state.answer} onCite={onCite} />}
              {state.phase === "done" && state.done && (
                <div className="mt-3 flex gap-3 border-t border-slate-100 pt-2 text-xs text-slate-400">
                  <span>{state.done.latency_ms} ms</span>
                  {state.done.cached && <span className="text-emerald-600">cached</span>}
                  <span>cites {state.done.cited_sources.join(", ") || "—"}</span>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="border-t border-slate-200 bg-white p-4">
          <div className="mb-2 flex gap-3">
            {(corpora ?? []).map((c: CorpusOut) => {
              const active = selectedCorpora.length === 0 || selectedCorpora.includes(c.slug);
              return (
                <label key={c.slug} className="flex items-center gap-1.5 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() =>
                      setSelectedCorpora((prev) => {
                        const all = (corpora ?? []).map((x) => x.slug);
                        const current = prev.length === 0 ? all : prev;
                        const next = current.includes(c.slug)
                          ? current.filter((s) => s !== c.slug)
                          : [...current, c.slug];
                        return next.length === all.length ? [] : next;
                      })
                    }
                  />
                  {c.slug === "ai-act" ? "EU AI Act" : c.slug.toUpperCase()}
                </label>
              );
            })}
          </div>
          <div className="flex gap-2">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && ask()}
              placeholder="e.g. Which AI practices are prohibited?"
              className="flex-1 rounded-xl border border-slate-300 px-4 py-2.5 text-sm
                         focus:border-indigo-500 focus:outline-none"
            />
            <button
              onClick={ask}
              disabled={state.phase === "loading" || state.phase === "streaming"}
              className="rounded-xl bg-indigo-600 px-5 text-sm font-semibold text-white
                         hover:bg-indigo-700 disabled:opacity-40"
            >
              Ask
            </button>
          </div>
        </div>
      </main>

      {state.sources.length > 0 && (
        <div className="w-80 overflow-y-auto border-l border-slate-200 bg-slate-50 p-4">
          <SourceList
            sources={state.sources}
            cited={state.done?.cited_sources ?? []}
            highlighted={highlighted}
          />
        </div>
      )}
    </div>
  );
}
