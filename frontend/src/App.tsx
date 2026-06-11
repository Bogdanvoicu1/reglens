import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { getToken } from "./lib/auth";
import { TokenGate } from "./components/TokenGate";
import { HistorySidebar } from "./components/HistorySidebar";
import { ChatPanel } from "./components/ChatPanel";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

export default function App() {
  const [authed, setAuthed] = useState(() => getToken() !== null);
  const [conversationId, setConversationId] = useState<string | null>(null);

  if (!authed) return <TokenGate onAuthed={() => setAuthed(true)} />;

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex h-screen bg-slate-100">
        <HistorySidebar
          activeId={conversationId}
          onSelect={setConversationId}
          onNew={() => setConversationId(null)}
        />
        <ChatPanel
          conversationId={conversationId}
          onConversationCreated={setConversationId}
        />
      </div>
    </QueryClientProvider>
  );
}
