import { clearToken, getToken } from "./auth";
import type { ConversationDetail, ConversationSummary, CorpusOut } from "../types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const resp = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (resp.status === 401) {
    clearToken();
    window.location.reload();
  }
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
};
