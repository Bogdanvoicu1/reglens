import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useChatStream } from "../hooks/useChatStream";
import { AnswerView } from "./AnswerView";
import { SourceList } from "./SourceList";

const SAMPLE_QUESTIONS = [
  "Which AI practices are prohibited?",
  "When is a DPIA required?",
  "Do chatbots have to disclose they are AI?",
  "What are the lawful bases for processing personal data?",
];

const CORPUS_LABELS: Record<string, string> = { "ai-act": "EU AI Act", gdpr: "GDPR" };

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-blue-700 text-xl font-bold text-white shadow-lg shadow-blue-950/50">
        R
      </div>
      <h2 className="mb-2 text-xl font-semibold tracking-tight text-white">
        Ask the regulation, not the internet.
      </h2>
      <p className="mb-8 max-w-md text-sm leading-relaxed text-zinc-500">
        Answers are grounded in the EU AI Act and GDPR with article-level citations — and
        refused when the text doesn't support them.
      </p>
      <div className="grid w-full max-w-lg gap-2 sm:grid-cols-2">
        {SAMPLE_QUESTIONS.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="rounded-xl border border-white/10 bg-zinc-900/60 px-4 py-3 text-left
                       text-[13px] text-zinc-300 transition hover:border-blue-400/40
                       hover:bg-zinc-900 hover:text-white"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

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

  const ask = (text?: string) => {
    const q = (text ?? question).trim();
    if (q.length < 3 || state.phase === "loading" || state.phase === "streaming") return;
    setQuestion("");
    setHighlighted(null);
    void send(q, selectedCorpora, conversationId);
  };

  const busy = state.phase === "loading" || state.phase === "streaming";
  const showStream = state.phase !== "idle";
  const showEmpty = !showStream && messages.length === 0 && conversationId === null;

  return (
    <div className="flex h-full flex-1 overflow-hidden">
      <main className="flex flex-1 flex-col overflow-hidden">
        {showEmpty ? (
          <div className="flex-1 overflow-y-auto">
            <EmptyState onPick={(q) => ask(q)} />
          </div>
        ) : (
          <div className="flex-1 space-y-5 overflow-y-auto px-6 py-6">
            <div className="mx-auto w-full max-w-3xl space-y-5">
              {messages.map((m) => (
                <div key={m.id} className={m.role === "user" ? "flex justify-end" : ""}>
                  {m.role === "user" ? (
                    <span className="inline-block max-w-xl rounded-2xl rounded-br-md bg-blue-500/15 px-4 py-2.5 text-left text-sm text-blue-100 ring-1 ring-inset ring-blue-400/20">
                      {m.content}
                    </span>
                  ) : (
                    <div className="rounded-2xl border border-white/10 bg-zinc-900/60 p-5">
                      <AnswerView text={m.content} onCite={() => {}} />
                      {m.latency_ms !== null && (
                        <div className="mt-3 border-t border-white/5 pt-2 text-[11px] text-zinc-600">
                          {m.latency_ms} ms
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}

              {showStream && (
                <div className="rounded-2xl border border-white/10 bg-zinc-900/60 p-5">
                  {state.phase === "loading" && (
                    <div className="space-y-2.5">
                      <div className="shimmer h-3.5 w-2/3 rounded-md" />
                      <div className="shimmer h-3.5 w-1/2 rounded-md" />
                      <div className="text-xs text-zinc-600">Retrieving sources…</div>
                    </div>
                  )}
                  {state.phase === "refused" && (
                    <div className="rounded-xl border border-amber-400/20 bg-amber-500/10 p-3.5 text-sm text-amber-200">
                      <span className="font-semibold">Cannot answer from the corpus.</span>{" "}
                      {state.refusalReason}
                    </div>
                  )}
                  {state.phase === "error" && (
                    <div className="rounded-xl border border-red-400/20 bg-red-500/10 p-3.5 text-sm text-red-300">
                      {state.error}
                    </div>
                  )}
                  {state.answer && (
                    <AnswerView
                      text={state.answer}
                      onCite={onCite}
                      streaming={state.phase === "streaming"}
                    />
                  )}
                  {state.phase === "done" && state.done && (
                    <div className="mt-3 flex items-center gap-2.5 border-t border-white/5 pt-2.5 text-[11px] text-zinc-500">
                      <span>{state.done.latency_ms} ms</span>
                      {state.done.cached && (
                        <span className="rounded-md bg-emerald-500/15 px-1.5 py-0.5 font-medium text-emerald-300">
                          cached
                        </span>
                      )}
                      <span>cites {state.done.cited_sources.join(", ") || "—"}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        <div className="border-t border-white/5 bg-zinc-950/80 p-4 backdrop-blur">
          <div className="mx-auto w-full max-w-3xl">
            <div className="mb-2.5 flex gap-1.5">
              {(corpora ?? []).map((c) => {
                const all = (corpora ?? []).map((x) => x.slug);
                const active = selectedCorpora.length === 0 || selectedCorpora.includes(c.slug);
                return (
                  <button
                    key={c.slug}
                    onClick={() =>
                      setSelectedCorpora((prev) => {
                        const current = prev.length === 0 ? all : prev;
                        const next = current.includes(c.slug)
                          ? current.filter((s) => s !== c.slug)
                          : [...current, c.slug];
                        return next.length === all.length ? [] : next;
                      })
                    }
                    className={`rounded-full px-3 py-1 text-[11px] font-medium ring-1 ring-inset transition ${
                      active
                        ? "bg-blue-500/15 text-blue-300 ring-blue-400/30"
                        : "bg-transparent text-zinc-600 ring-white/10 hover:text-zinc-400"
                    }`}
                  >
                    {CORPUS_LABELS[c.slug] ?? c.slug}
                  </button>
                );
              })}
            </div>
            <div className="flex gap-2">
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && ask()}
                placeholder="Ask about the EU AI Act or GDPR…"
                className="flex-1 rounded-xl border border-white/10 bg-zinc-900/80 px-4 py-2.5
                           text-sm text-zinc-200 placeholder:text-zinc-600 transition
                           focus:border-blue-500/50 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              />
              <button
                onClick={() => ask()}
                disabled={busy}
                className="rounded-xl bg-gradient-to-r from-blue-500 to-blue-700 px-5 text-sm
                           font-semibold text-white shadow-md shadow-blue-950/50 transition
                           hover:brightness-110 disabled:opacity-40 disabled:shadow-none"
              >
                {busy ? "…" : "Ask"}
              </button>
            </div>
          </div>
        </div>
      </main>

      {state.sources.length > 0 && (
        <div className="w-84 overflow-y-auto border-l border-white/5 bg-zinc-900/30 p-4">
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
