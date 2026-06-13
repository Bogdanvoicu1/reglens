import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

export function HistorySidebar({
  activeId,
  onSelect,
  onNew,
}: {
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: api.listConversations,
  });

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
            <button
              key={c.id}
              onClick={() => onSelect(c.id)}
              title={c.title}
              className={`group mb-0.5 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px] transition ${
                active
                  ? "bg-blue-500/10 text-blue-200"
                  : "text-zinc-400 hover:bg-white/5 hover:text-zinc-200"
              }`}
            >
              <span
                className={`h-1 w-1 shrink-0 rounded-full transition ${
                  active ? "bg-blue-400" : "bg-zinc-700 group-hover:bg-zinc-500"
                }`}
              />
              <span className="truncate">{c.title || "Untitled"}</span>
            </button>
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
