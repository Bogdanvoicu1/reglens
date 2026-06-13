import { getAccessToken } from "./auth";
import type {
  AssessmentReport,
  AssessmentSummary,
  ConversationDetail,
  ConversationSummary,
  CorpusOut,
} from "../types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await getAccessToken();
  const resp = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  // A 401 surfaces as an ApiError; supabase-js refreshes tokens in the
  // background and useSession() drops the app to the login screen if the
  // session is truly gone, so there's nothing to force here.
  if (!resp.ok && resp.headers.get("content-type")?.includes("json")) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body.detail ?? resp.statusText);
  }
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
  return resp;
}

export const api = {
  chat: (body: {
    question: string;
    corpus_slugs?: string[] | null;
    conversation_id?: string | null;
  }) => request("/api/v1/chat", { method: "POST", body: JSON.stringify(body) }),

  listConversations: async (): Promise<ConversationSummary[]> =>
    (await request("/api/v1/conversations")).json(),

  getConversation: async (id: string): Promise<ConversationDetail> =>
    (await request(`/api/v1/conversations/${id}`)).json(),

  listCorpora: async (): Promise<CorpusOut[]> => (await request("/api/v1/corpora")).json(),

  createAssessment: (body: { title?: string; description: string; clarify: boolean }) =>
    request("/api/v1/assessments", { method: "POST", body: JSON.stringify(body) }),

  answerClarification: (id: string, answers: string[]) =>
    request(`/api/v1/assessments/${id}/answers`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),

  listAssessments: async (): Promise<AssessmentSummary[]> =>
    (await request("/api/v1/assessments")).json(),

  getReport: async (id: string): Promise<{ version: number; report: AssessmentReport }> =>
    (await request(`/api/v1/assessments/${id}/report`)).json(),

  reportMarkdown: async (id: string): Promise<string> =>
    (await request(`/api/v1/assessments/${id}/report.md`)).text(),

  deleteAssessment: async (id: string): Promise<void> => {
    await request(`/api/v1/assessments/${id}`, { method: "DELETE" });
  },
};
