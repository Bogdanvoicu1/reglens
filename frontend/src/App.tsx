import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useSession } from "./hooks/useSession";
import { LoginPage } from "./components/LoginPage";
import { NavRail, type View } from "./components/NavRail";
import { HistorySidebar } from "./components/HistorySidebar";
import { ChatPanel } from "./components/ChatPanel";
import { AssessmentsView } from "./components/AssessmentsView";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

export default function App() {
  const session = useSession();
  const [view, setView] = useState<View>("chat");
  const [conversationId, setConversationId] = useState<string | null>(null);

  if (session === undefined) {
    return <div className="h-screen bg-zinc-950" />; // resolving the persisted session
  }
  if (session === null) {
    return <LoginPage />;
  }

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex h-screen bg-zinc-950">
        <NavRail view={view} onView={setView} />
        {view === "chat" ? (
          <>
            <HistorySidebar
              activeId={conversationId}
              onSelect={setConversationId}
              onNew={() => setConversationId(null)}
            />
            <ChatPanel conversationId={conversationId} onConversationCreated={setConversationId} />
          </>
        ) : (
          <AssessmentsView />
        )}
      </div>
    </QueryClientProvider>
  );
}
