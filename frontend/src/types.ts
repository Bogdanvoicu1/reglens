export interface Source {
  id: number;
  ref: string;
  title: string;
  corpus: string;
  text: string;
}

export interface DoneMeta {
  status: string;
  cached: boolean;
  cited_sources: number[];
  conversation_id: string;
  latency_ms: number;
}

export type SSEEvent =
  | { event: "sources"; data: { sources: Source[] } }
  | { event: "token"; data: { token: string } }
  | { event: "done"; data: DoneMeta }
  | { event: "refusal"; data: { reason: string } }
  | { event: "error"; data: { message: string } };

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
}

export interface MessageOut {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: { cited: number[] } | null;
  latency_ms: number | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: MessageOut[];
}

export interface CorpusOut {
  slug: string;
  title: string;
  version: string;
}
