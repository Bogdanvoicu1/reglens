import type { Source } from "../types";

const CORPUS_LABELS: Record<string, string> = {
  "ai-act": "AI Act",
  gdpr: "GDPR",
};

export function SourceList({
  sources,
  cited,
  highlighted,
}: {
  sources: Source[];
  cited: number[];
  highlighted: number | null;
}) {
  if (sources.length === 0) return null;
  return (
    <aside className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Sources
      </h3>
      {sources.map((s) => {
        const isCited = cited.includes(s.id);
        const isHighlighted = highlighted === s.id;
        return (
          <div
            key={s.id}
            id={`source-${s.id}`}
            className={`rounded-lg border p-3 text-sm transition-colors ${
              isHighlighted
                ? "border-indigo-400 bg-indigo-50"
                : isCited
                  ? "border-slate-300 bg-white"
                  : "border-slate-200 bg-slate-50 opacity-70"
            }`}
          >
            <div className="mb-1 flex items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-xs font-bold text-white">
                {s.id}
              </span>
              <span className="font-semibold text-slate-700">
                {CORPUS_LABELS[s.corpus] ?? s.corpus} · {s.ref}
              </span>
            </div>
            {s.title && <div className="mb-1 text-xs italic text-slate-500">{s.title}</div>}
            <p className="line-clamp-4 text-xs leading-snug text-slate-600">
              {s.text.replace(/^\[[^\]]*\]\n?/, "")}
            </p>
          </div>
        );
      })}
    </aside>
  );
}
