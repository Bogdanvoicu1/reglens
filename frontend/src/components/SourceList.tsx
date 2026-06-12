import type { Source } from "../types";

const CORPUS_STYLE: Record<string, { label: string; badge: string; ring: string }> = {
  "ai-act": {
    label: "EU AI Act",
    badge: "bg-sky-500/15 text-sky-300 ring-sky-400/30",
    ring: "ring-sky-400/40",
  },
  gdpr: {
    label: "GDPR",
    badge: "bg-emerald-500/15 text-emerald-300 ring-emerald-400/30",
    ring: "ring-emerald-400/40",
  },
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
    <aside className="space-y-2.5">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
        Sources
      </h3>
      {sources.map((s) => {
        const style = CORPUS_STYLE[s.corpus] ?? {
          label: s.corpus,
          badge: "bg-zinc-500/15 text-zinc-300 ring-zinc-400/30",
          ring: "ring-zinc-400/40",
        };
        const isCited = cited.length === 0 || cited.includes(s.id);
        const isHighlighted = highlighted === s.id;
        return (
          <div
            key={s.id}
            id={`source-${s.id}`}
            className={`rounded-xl border bg-zinc-900/60 p-3.5 transition-all ${
              isHighlighted
                ? `source-pulse border-blue-400/50 ring-1 ${style.ring}`
                : isCited
                  ? "border-white/10"
                  : "border-white/5 opacity-50"
            }`}
          >
            <div className="mb-1.5 flex items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded-md bg-zinc-800 text-[11px] font-bold text-zinc-300 ring-1 ring-inset ring-white/10">
                {s.id}
              </span>
              <span
                className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${style.badge}`}
              >
                {style.label}
              </span>
              <span className="text-[13px] font-semibold text-zinc-200">{s.ref}</span>
            </div>
            {s.title && (
              <div className="mb-1.5 text-[11px] italic text-zinc-500">{s.title}</div>
            )}
            <p className="line-clamp-4 text-xs leading-relaxed text-zinc-400">
              {s.text.replace(/^\[[^\]]*\]\n?/, "")}
            </p>
          </div>
        );
      })}
    </aside>
  );
}
