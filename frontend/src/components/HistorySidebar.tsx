import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

export function HistorySidebar({
  activeId,
  onSelect,
  onNew,
  onDelete,
}: {
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete?: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const [deleting, setDeleting] = useState<string | null>(null);
  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: api.listConversations,
  });

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!confirm("Delete this conversation?")) return;
    setDeleting(id);
    try {
      await api.deleteConversation(id);
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      onDelete?.(id);
    } catch (err) {
      console.error("Failed to delete conversation:", err);
      alert("Failed to delete conversation: " + (err instanceof Error ? err.message : String(err)));
      setDeleting(null);
    }
  };

  return (
    <nav className="flex h-full w-66 flex-col border-r border-white/5 bg-zinc-925 bg-zinc-900/40">
      <div className="p-4">
        <div className="mb-3 px-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
          Ask
        </div>
        <button
          onClick={onNew}
          className="w-full rounded-xl bg-gradient-to-r from-blue-500 to-blue-700 py-2
                     text-sm font-semibold text-white shadow-md shadow-blue-950/50
                     transition hover:brightness-110"
        >
          New question
        </button>
      </div>

      <div className="mx-4 mb-2 text-[11px] font-medium uppercase tracking-wider text-zinc-600">
        History
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {(conversations ?? []).map((c) => {
          const active = c.id === activeId;
          return (
            <div
              key={c.id}
              className={`group mb-0.5 flex w-full items-center gap-2 rounded-lg transition ${
                active ? "bg-blue-500/10" : "hover:bg-white/5"
              }`}
            >
              <button
                onClick={() => onSelect(c.id)}
                title={c.title}
                className={`flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-[13px] transition ${
                  active
                    ? "text-blue-200"
                    : "text-zinc-400 group-hover:text-zinc-200"
                }`}
              >
                <span
                  className={`h-1 w-1 shrink-0 rounded-full transition ${
                    active ? "bg-blue-400" : "bg-zinc-700 group-hover:bg-zinc-500"
                  }`}
                />
                <span className="min-w-0 truncate">{c.title || "Untitled"}</span>
              </button>
              <button
                onClick={(e) => handleDelete(e, c.id)}
                disabled={deleting === c.id}
                className="shrink-0 rounded px-2 py-1 text-xs text-zinc-500 opacity-0 transition hover:bg-red-500/20 hover:text-red-400 group-hover:opacity-100 disabled:opacity-50 disabled:cursor-not-allowed"
                title="Delete conversation"
              >
                {deleting === c.id ? "..." : "✕"}
              </button>
            </div>
          );
        })}
        {conversations?.length === 0 && (
          <p className="px-3 py-2 text-xs text-zinc-600">No conversations yet.</p>
        )}
      </div>

      <p className="border-t border-white/5 p-4 text-[11px] leading-snug text-zinc-600">
        Regulatory information, not legal advice.
      </p>
    </nav>
  );
}
