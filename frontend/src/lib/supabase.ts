// Lazily-created Supabase client (only when the backend reports a project).
// supabase-js persists and auto-refreshes the session; App mirrors the access
// token into `reglens.token` via onAuthStateChange so api.ts and the SSE
// streamers — which read that key — stay untouched.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | null = null;

export function getSupabaseClient(url: string, anonKey: string): SupabaseClient {
  if (!client) client = createClient(url, anonKey);
  return client;
}

export const supabaseClientOrNull = (): SupabaseClient | null => client;
