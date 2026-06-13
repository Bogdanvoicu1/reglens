import { useState } from "react";
import { api } from "../lib/api";
import type { AssessmentReport, GapStatus, ReportObligation } from "../types";

const GAP_STYLE: Record<GapStatus, { label: string; cls: string }> = {
  met: { label: "Met", cls: "bg-emerald-500/15 text-emerald-300 ring-emerald-400/30" },
  partial: { label: "Partial", cls: "bg-amber-500/15 text-amber-200 ring-amber-400/30" },
  missing: { label: "Missing", cls: "bg-red-500/15 text-red-300 ring-red-400/30" },
  unknown: { label: "Unknown", cls: "bg-zinc-500/15 text-zinc-300 ring-zinc-400/30" },
};

const PRIORITY_STYLE: Record<string, string> = {
  blocker: "bg-red-500/15 text-red-300 ring-red-400/30",
  high: "bg-amber-500/15 text-amber-200 ring-amber-400/30",
  medium: "bg-blue-500/15 text-blue-300 ring-blue-400/30",
  low: "bg-zinc-500/15 text-zinc-300 ring-zinc-400/30",
};

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-zinc-900/60 px-4 py-3">
      <div className={`text-2xl font-semibold tabular-nums ${tone ?? "text-white"}`}>{value}</div>
      <div className="text-[11px] uppercase tracking-wider text-zinc-500">{label}</div>
    </div>
  );
}

function ObligationCard({ o }: { o: ReportObligation }) {
  const gap = GAP_STYLE[o.gap_status];
  return (
    <div className="rounded-xl border border-white/10 bg-zinc-900/60 p-4">
      <div className="mb-1.5 flex items-start justify-between gap-3">
        <h4 className="text-sm font-semibold text-zinc-100">{o.title}</h4>
        <span
          className={`shrink-0 rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase ring-1 ring-inset ${gap.cls}`}
        >
          {gap.label}
        </span>
      </div>
      <p className="text-[13px] leading-relaxed text-zinc-400">{o.summary}</p>
      {o.gap_reasoning && (
        <p className="mt-2 border-l-2 border-white/10 pl-3 text-xs italic text-zinc-500">
          {o.gap_reasoning}
        </p>
      )}
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {o.citations.map((c) => (
          <span
            key={c}
            className="rounded-md bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-300 ring-1 ring-inset ring-blue-400/20"
          >
            {c}
          </span>
        ))}
        {!o.audience_established && (
          <span className="text-[11px] text-zinc-500">· conditional on being a {o.audience}</span>
        )}
      </div>
    </div>
  );
}

export function ReportView({
  report,
  assessmentId,
  fresh = false,
}: {
  report: AssessmentReport;
  assessmentId: string;
  fresh?: boolean;
}) {
  const [downloading, setDownloading] = useState(false);
  const g = report.gap_counts;

  const download = async () => {
    setDownloading(true);
    try {
      const md = await api.reportMarkdown(assessmentId);
      const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `reglens-assessment-${assessmentId.slice(0, 8)}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 px-6 py-8">
      <header>
        {fresh && (
          <div className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2.5 py-1 text-[11px] font-medium text-emerald-300">
            ✓ Assessment complete
          </div>
        )}
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-2xl font-semibold tracking-tight text-white">{report.title}</h1>
          <button
            onClick={download}
            disabled={downloading}
            className="shrink-0 rounded-lg border border-white/10 bg-zinc-900/80 px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:border-blue-400/40 hover:text-white disabled:opacity-50"
          >
            {downloading ? "…" : "Download .md"}
          </button>
        </div>
        <p className="mt-1 text-[11px] text-zinc-600">
          {new Date(report.generated_at).toLocaleString()} · rulebook {report.rulebook_version}
        </p>
      </header>

      <section className="rounded-2xl border border-blue-400/20 bg-blue-500/[0.07] p-5">
        <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-blue-300">
          Executive summary
        </h2>
        <p className="text-[15px] leading-relaxed text-zinc-200">{report.executive_summary}</p>
      </section>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label="Blockers"
          value={report.blockers.length}
          tone={report.blockers.length ? "text-red-400" : "text-emerald-400"}
        />
        <Stat label="Obligations" value={report.obligations.length} />
        <Stat label="Missing" value={g.missing ?? 0} tone="text-red-300" />
        <Stat label="Partial" value={g.partial ?? 0} tone="text-amber-200" />
      </section>

      {report.blockers.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-red-300">⛔ Blockers — prohibited practices</h2>
          {report.blockers.map((b) => (
            <div
              key={b.rule_id}
              className="rounded-xl border border-red-400/30 bg-red-500/10 p-4"
            >
              <h3 className="mb-1 text-sm font-semibold text-red-200">{b.title}</h3>
              <p className="text-[13px] leading-relaxed text-zinc-300">{b.reasoning}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {b.citations.map((c) => (
                  <span key={c} className="text-[11px] text-red-300/80">
                    {c}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </section>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-zinc-200">
          Applicable obligations{" "}
          <span className="text-zinc-500">({report.obligations.length})</span>
        </h2>
        {report.obligations.length === 0 ? (
          <p className="text-sm text-zinc-500">No obligations were triggered.</p>
        ) : (
          <div className="space-y-2.5">
            {report.obligations.map((o) => (
              <ObligationCard key={o.id} o={o} />
            ))}
          </div>
        )}
      </section>

      {report.remediation.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-zinc-200">Remediation roadmap</h2>
          <ol className="space-y-2.5">
            {report.remediation.map((r, i) => (
              <li key={i} className="rounded-xl border border-white/10 bg-zinc-900/60 p-4">
                <div className="mb-1.5 flex items-center gap-2">
                  <span
                    className={`rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase ring-1 ring-inset ${
                      PRIORITY_STYLE[r.priority] ?? PRIORITY_STYLE.low
                    }`}
                  >
                    {r.priority}
                  </span>
                  <span className="text-[11px] text-zinc-500">effort {r.effort}</span>
                  <h4 className="text-sm font-semibold text-zinc-100">{r.title}</h4>
                </div>
                <p className="text-[13px] leading-relaxed text-zinc-400">{r.description}</p>
                <p className="mt-2 text-xs text-zinc-500">
                  <span className="font-medium text-zinc-400">Tradeoffs:</span> {r.tradeoffs}
                </p>
              </li>
            ))}
          </ol>
        </section>
      )}

      <p className="border-t border-white/5 pt-4 text-[11px] leading-relaxed text-zinc-600">
        {report.disclaimer.replace(/\*\*/g, "")}
      </p>
    </div>
  );
}
