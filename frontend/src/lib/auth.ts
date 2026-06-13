// Token storage — the single source of truth the API client and SSE streamers
// read. In Supabase mode the login flow writes the Supabase access token here
// (and refreshes it via onAuthStateChange); for local dev, mint a token with
// backend/scripts/dev_token.py and paste it into the dev sign-in.

import { supabaseClientOrNull } from "./supabase";

const KEY = "reglens.token";

export const getToken = (): string | null => localStorage.getItem(KEY);
export const setToken = (token: string): void => localStorage.setItem(KEY, token.trim());
export const clearToken = (): void => localStorage.removeItem(KEY);

export async function signOut(): Promise<void> {
  // Ends the Supabase session when present (also clears its persisted token);
  // harmless no-op in dev-token mode.
  await supabaseClientOrNull()?.auth.signOut();
  clearToken();
}
