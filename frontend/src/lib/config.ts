// Runtime config fetched once from the backend (GET /api/v1/config) so a single
// frontend build works against any backend. When supabaseUrl is empty the SPA
// falls back to local dev-token sign-in instead of the Supabase login.

export interface AppConfig {
  supabaseUrl: string;
  supabaseAnonKey: string;
}

let cached: AppConfig | null = null;

export async function loadConfig(): Promise<AppConfig> {
  if (cached) return cached;
  try {
    const resp = await fetch("/api/v1/config");
    const body = resp.ok ? await resp.json() : {};
    cached = {
      supabaseUrl: body.supabase_url ?? "",
      supabaseAnonKey: body.supabase_anon_key ?? "",
    };
  } catch {
    // Backend unreachable — degrade to dev-token sign-in rather than blocking.
    cached = { supabaseUrl: "", supabaseAnonKey: "" };
  }
  return cached;
}

export const isSupabaseConfigured = (c: AppConfig): boolean =>
  Boolean(c.supabaseUrl && c.supabaseAnonKey);
