import { useCallback, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { streamSSE } from "../lib/sse";
import type { AssessmentReport } from "../types";

export type AssessmentPhase = "idle" | "running" | "clarifying" | "complete" | "error";

export const STAGES = [
  "profile_extraction",
  "classification",
  "obligation_mapping",
  "gap_analysis",
  "remediation",
  "report",
] as const;

export const STAGE_LABELS: Record<string, string> = {
  profile_extraction: "Profile extraction",
  classification: "Classification",
  obligation_mapping: "Obligation mapping",
  gap_analysis: "Gap analysis",
  remediation: "Remediation",
  report: "Report",
};

export interface AssessmentState {
  phase: AssessmentPhase;
  assessmentId: string | null;
  currentStage: string | null;
  stagesDone: string[];
  profileSummary: string | null;
  tallies: Record<string, number>; // verdict → count, accumulated live
  obligationCount: number;
  questions: string[];
  report: AssessmentReport | null;
  blockers: string[];
  error: string;
}

const INITIAL: AssessmentState = {
  phase: "idle",
  assessmentId: null,
  currentStage: null,
  stagesDone: [],
  profileSummary: null,
  tallies: {},
  obligationCount: 0,
  questions: [],
  report: null,
  blockers: [],
  error: "",
};

export function useAssessmentStream(onSettled?: () => void) {
  const [state, setState] = useState<AssessmentState>(INITIAL);
  const busy = useRef(false);

  const consume = useCallback(
    async (resp: Response) => {
      await streamSSE(resp, ({ event, data }) => {
        const payload = JSON.parse(data);
        setState((s) => {
          switch (event) {
            case "assessment_created":
              return { ...s, assessmentId: payload.assessment_id };
            case "stage_started":
              return {
                ...s,
                phase: "running",
                currentStage: payload.stage,
                stagesDone: s.currentStage
                  ? [...new Set([...s.stagesDone, s.currentStage])]
                  : s.stagesDone,
              };
            case "profile":
              return { ...s, profileSummary: payload.profile.summary };
            case "clarification_needed":
              return { ...s, phase: "clarifying", questions: payload.questions };
            case "finding":
              return {
                ...s,
                tallies: {
                  ...s.tallies,
                  [payload.verdict]: (s.tallies[payload.verdict] ?? 0) + 1,
                },
              };
            case "obligations":
              return { ...s, obligationCount: payload.obligations.length };
            case "report_ready":
              return { ...s, report: payload.report };
            case "assessment_completed":
              return {
                ...s,
                phase: "complete",
                blockers: payload.blockers ?? [],
                stagesDone: [...STAGES],
                currentStage: null,
              };
            case "error":
              return { ...s, phase: "error", error: payload.message };
            default:
              return s;
          }
        });
      });
    },
    [],
  );

  const run = useCallback(
    async (starter: () => Promise<Response>) => {
      if (busy.current) return;
      busy.current = true;
      try {
        await consume(await starter());
      } catch (err) {
        const message =
          err instanceof ApiError && err.status === 429
            ? "Daily assessment limit reached for this workspace — try again tomorrow."
            : err instanceof Error
              ? err.message
              : "Request failed";
        setState((s) => ({ ...s, phase: "error", error: message }));
      } finally {
        busy.current = false;
        onSettled?.();
      }
    },
    [consume, onSettled],
  );

  const start = useCallback(
    (description: string, title: string, clarify: boolean) => {
      setState({ ...INITIAL, phase: "running" });
      return run(() => api.createAssessment({ description, title, clarify }));
    },
    [run],
  );

  const answer = useCallback(
    (answers: string[]) => {
      const id = state.assessmentId;
      if (!id) return;
      setState((s) => ({ ...INITIAL, phase: "running", assessmentId: s.assessmentId }));
      return run(() => api.answerClarification(id, answers));
    },
    [run, state.assessmentId],
  );

  const reset = useCallback(() => setState(INITIAL), []);
  return { state, start, answer, reset };
}
