import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useAssessmentStream } from "../hooks/useAssessmentStream";
import type { AssessmentSummary } from "../types";
import { AssessmentIntake } from "./AssessmentIntake";
import { StageTimeline } from "./StageTimeline";
import { ClarificationPanel } from "./ClarificationPanel";
import { ReportView } from "./ReportView";

type Mode = "intake" | "live" | "saved";

const STATUS_STYLE: Record<string, string> = {
  complete: "bg-emerald-500/15 text-emerald-300",
  running: "bg-blue-500/15 text-blue-300",
  clarifying: "bg-amber-500/15 text-amber-200",
  failed: "bg-red-500/15 text-red-300",
  draft: "bg-zinc-500/15 text-zinc-400",
};

function Sidebar({
  activeId,
  onNew,
  onSelect,
  onDeleted,
}: {
  activeId: string | null;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDeleted: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const { data: assessments } = useQuery({
    queryKey: ["assessments"],
    queryFn: api.listAssessments,
  });

  const remove = async (id: string) => {
    await api.deleteAssessment(id);
    queryClient.invalidateQueries({ queryKey: ["assessments"] });
    onDeleted(id);
  };

  return (
    <nav className="flex h-full w-66 flex-col border-r border-white/5 bg-zinc-900/40">
      <div className="p-4">
        <div className="mb-3 px-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
          Assess
        </div>
        <button
          onClick={onNew}
          className="w-full rounded-xl bg-gradient-to-r from-blue-500 to-blue-700 py-2 text-sm
                     font-semibold text-white shadow-md shadow-blue-950/50 transition hover:brightness-110"
        >
          New assessment
        </button>
      </div>
      <div className="mx-4 mb-2 text-[11px] font-medium uppercase tracking-wider text-zinc-600">
        History
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {(assessments ?? []).map((a: AssessmentSummary) => (
          <div
            key={a.id}
            className={`group mb-0.5 flex items-center gap-2 rounded-lg px-3 py-2 text-left transition ${
              a.id === activeId ? "bg-blue-500/10" : "hover:bg-white/5"
            }`}
          >
            <button onClick={() => onSelect(a.id)} className="min-w-0 flex-1 text-left">
              <div
                className={`truncate text-[13px] ${
                  a.id === activeId ? "text-blue-200" : "text-zinc-300"
                }`}
              >
                {a.title || "Untitled"}
              </div>
              <span
                className={`mt-0.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${
                  STATUS_STYLE[a.status] ?? STATUS_STYLE.draft
                }`}
              >
                {a.status}
              </span>
            </button>
            <button
              onClick={() => remove(a.id)}
              title="Delete"
              className="shrink-0 rounded p-1 text-zinc-600 opacity-0 transition hover:text-red-300 group-hover:opacity-100"
            >
              <svg viewBox="0 0 24 24" fill="none" className="h-3.5 w-3.5">
                <path
                  d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V7"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </div>
        ))}
        {assessments?.length === 0 && (
          <p className="px-3 py-2 text-xs text-zinc-600">No assessments yet.</p>
        )}
      </div>
      <p className="border-t border-white/5 p-4 text-[11px] leading-snug text-zinc-600">
        Readiness analysis, not legal advice.
      </p>
    </nav>
  );
}

function SavedReport({ id }: { id: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["assessmentReport", id],
    queryFn: () => api.getReport(id),
    retry: false,
  });

  if (isLoading) {
    return <div className="px-6 py-10 text-sm text-zinc-500">Loading report…</div>;
  }
  if (error) {
    const msg =
      error instanceof ApiError && error.status === 404
        ? "This assessment has no report yet (it may be incomplete or failed)."
        : "Could not load the report.";
    return <div className="px-6 py-10 text-sm text-zinc-500">{msg}</div>;
  }
  return data ? <ReportView report={data.report} assessmentId={id} /> : null;
}

export function AssessmentsView() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("intake");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const onSettled = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["assessments"] });
  }, [queryClient]);

  const { state, start, answer, reset } = useAssessmentStream(onSettled);

  const newAssessment = () => {
    reset();
    setSelectedId(null);
    setMode("intake");
  };
  const selectSaved = (id: string) => {
    setSelectedId(id);
    setMode("saved");
  };

  // The assessment currently shown in the main panel (saved view or fresh run).
  const activeViewId = mode === "saved" ? selectedId : mode === "live" ? state.assessmentId : null;
  const handleDeleted = (id: string) => {
    if (id === activeViewId) newAssessment(); // don't leave a deleted report on screen
  };

  return (
    <div className="flex h-full flex-1 overflow-hidden">
      <Sidebar
        activeId={mode === "saved" ? selectedId : null}
        onNew={newAssessment}
        onSelect={selectSaved}
        onDeleted={handleDeleted}
      />
      <main className="flex-1 overflow-y-auto">
        {mode === "intake" && (
          <AssessmentIntake
            onStart={(d, t, c) => {
              setMode("live");
              start(d, t, c);
            }}
          />
        )}
        {mode === "saved" && selectedId && <SavedReport id={selectedId} />}
        {mode === "live" && (
          <>
            {state.phase === "running" && <StageTimeline state={state} />}
            {state.phase === "clarifying" && (
              <ClarificationPanel questions={state.questions} onSubmit={answer} />
            )}
            {state.phase === "complete" && state.report && state.assessmentId && (
              <ReportView report={state.report} assessmentId={state.assessmentId} fresh />
            )}
            {state.phase === "error" && (
              <div className="mx-auto max-w-2xl px-6 py-10">
                <div className="rounded-xl border border-red-400/20 bg-red-500/10 p-4 text-sm text-red-300">
                  {state.error}
                </div>
                <button
                  onClick={newAssessment}
                  className="mt-4 rounded-lg border border-white/10 px-3 py-1.5 text-sm text-zinc-300 hover:text-white"
                >
                  Start over
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
