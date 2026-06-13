import { STAGE_LABELS, STAGES, type AssessmentState } from "../hooks/useAssessmentStream";

function Dot({ status }: { status: "done" | "active" | "pending" }) {
  if (status === "done") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-300">
        <svg viewBox="0 0 24 24" fill="none" className="h-3 w-3">
          <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    );
  }
  if (status === "active") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-500/20">
        <span className="source-pulse h-2 w-2 rounded-full bg-blue-400" />
      </span>
    );
  }
  return <span className="h-5 w-5 rounded-full border border-white/10 bg-zinc-900" />;
}

export function StageTimeline({ state }: { state: AssessmentState }) {
  const total = Object.values(state.tallies).reduce((a, b) => a + b, 0);
  return (
    <div className="mx-auto w-full max-w-md px-6 py-12">
      <h2 className="mb-1 text-lg font-semibold tracking-tight text-white">Assessing…</h2>
      {state.profileSummary && (
        <p className="mb-6 text-sm leading-relaxed text-zinc-500">{state.profileSummary}</p>
      )}
      <ol className="space-y-1">
        {STAGES.map((stage) => {
          const status = state.stagesDone.includes(stage)
            ? "done"
            : state.currentStage === stage
              ? "active"
              : "pending";
          return (
            <li key={stage} className="flex items-center gap-3 py-1.5">
              <Dot status={status} />
              <span
                className={`text-sm ${
                  status === "pending"
                    ? "text-zinc-600"
                    : status === "active"
                      ? "font-medium text-blue-200"
                      : "text-zinc-300"
                }`}
              >
                {STAGE_LABELS[stage]}
              </span>
              {stage === "classification" && state.currentStage === "classification" && total > 0 && (
                <span className="ml-auto text-xs tabular-nums text-zinc-500">{total} rules</span>
              )}
              {stage === "obligation_mapping" && state.obligationCount > 0 && (
                <span className="ml-auto text-xs tabular-nums text-zinc-500">
                  {state.obligationCount} duties
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
