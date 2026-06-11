import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { clearToken } from "../lib/auth";

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
    <nav className="flex h-full w-64 flex-col border-r border-slate-200 bg-white">
      <div className="border-b border-slate-200 p-4">
        <div className="mb-3 flex items-baseline justify-between">
          <span className="text-lg font-bold text-slate-900">RegLens</span>
          <button
            onClick={() => {
              clearToken();
              window.location.reload();
            }}
            className="text-xs text-slate-400 hover:text-slate-600"
          >
            Sign out
          </button>
        </div>
        <button
          onClick={onNew}
          className="w-full rounded-lg bg-indigo-600 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700"
        >
          New question
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {(conversations ?? []).map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={`mb-1 w-full truncate rounded-lg px-3 py-2 text-left text-sm ${
              c.id === activeId
                ? "bg-indigo-50 font-medium text-indigo-800"
                : "text-slate-600 hover:bg-slate-50"
            }`}
            title={c.title}
          >
            {c.title || "Untitled"}
          </button>
        ))}
      </div>
      <p className="border-t border-slate-200 p-3 text-[11px] leading-snug text-slate-400">
        Regulatory information, not legal advice.
      </p>
    </nav>
  );
}
