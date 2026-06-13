import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { clearToken, getToken, setToken } from "./lib/auth";
import { type AppConfig, isSupabaseConfigured, loadConfig } from "./lib/config";
import { getSupabaseClient } from "./lib/supabase";
import { TokenGate } from "./components/TokenGate";
import { NavRail, type View } from "./components/NavRail";
import { HistorySidebar } from "./components/HistorySidebar";
import { ChatPanel } from "./components/ChatPanel";
import { AssessmentsView } from "./components/AssessmentsView";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [authed, setAuthed] = useState(() => getToken() !== null);
  const [view, setView] = useState<View>("chat");
  const [conversationId, setConversationId] = useState<string | null>(null);

  useEffect(() => {
    let unsubscribe: (() => void) | undefined;
    loadConfig().then((cfg) => {
      setConfig(cfg);
      if (isSupabaseConfigured(cfg)) {
        const supabase = getSupabaseClient(cfg.supabaseUrl, cfg.supabaseAnonKey);
        // Mirror the Supabase session into reglens.token on sign-in, token
        // refresh, and sign-out (also fires INITIAL_SESSION on load), so the
        // API client and SSE streamers keep reading a single token key.
        const { data } = supabase.auth.onAuthStateChange((_event, session) => {
          if (session?.access_token) {
            setToken(session.access_token);
            setAuthed(true);
          } else {
            clearToken();
            setAuthed(false);
          }
        });
        unsubscribe = () => data.subscription.unsubscribe();
      }
    });
    return () => unsubscribe?.();
  }, []);

  if (config === null) {
    return <div className="h-screen bg-zinc-950" />;
  }
  if (!authed) {
    return <TokenGate config={config} onAuthed={() => setAuthed(true)} />;
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
