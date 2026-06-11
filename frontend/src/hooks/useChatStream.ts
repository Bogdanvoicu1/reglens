import { useCallback, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { streamSSE } from "../lib/sse";
import type { DoneMeta, Source } from "../types";

export type Phase = "idle" | "loading" | "streaming" | "done" | "refused" | "error";

export interface ChatState {
  phase: Phase;
  answer: string;
  sources: Source[];
  done: DoneMeta | null;
  refusalReason: string;
  error: string;
}

const INITIAL: ChatState = {
  phase: "idle",
  answer: "",
  sources: [],
  done: null,
  refusalReason: "",
  error: "",
};

export function useChatStream(onDone?: (meta: DoneMeta) => void) {
  const [state, setState] = useState<ChatState>(INITIAL);
  const busy = useRef(false);

  const send = useCallback(
    async (question: string, corpusSlugs: string[], conversationId: string | null) => {
      if (busy.current) return;
      busy.current = true;
      setState({ ...INITIAL, phase: "loading" });
      try {
        const resp = await api.chat({
          question,
          corpus_slugs: corpusSlugs.length > 0 ? corpusSlugs : null,
          conversation_id: conversationId,
        });
        await streamSSE(resp, ({ event, data }) => {
          const payload = JSON.parse(data);
          // State updaters must stay pure: fire callbacks after scheduling
          // the update, never inside it.
          setState((s) => {
            switch (event) {
              case "sources":
                return { ...s, phase: "streaming", sources: payload.sources };
              case "token":
                return { ...s, phase: "streaming", answer: s.answer + payload.token };
              case "done":
                return { ...s, phase: "done", done: payload };
              case "refusal":
                return { ...s, phase: "refused", refusalReason: payload.reason };
              case "error":
                return { ...s, phase: "error", error: payload.message };
              default:
                return s;
            }
          });
          if (event === "done") onDone?.(payload);
        });
      } catch (err) {
        const message =
          err instanceof ApiError && err.status === 429
            ? "Rate limit reached — please wait a moment and try again."
            : err instanceof Error
              ? err.message
              : "Request failed";
        setState((s) => ({ ...s, phase: "error", error: message }));
      } finally {
        busy.current = false;
      }
    },
    [onDone],
  );

  const reset = useCallback(() => setState(INITIAL), []);
  return { state, send, reset };
}
