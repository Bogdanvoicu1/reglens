// Thin wrappers over the Supabase session. The access token is never stored by
// app code — it's read fresh from supabase-js whenever a request needs it.

import { supabase } from "./supabase";

export async function getAccessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

export async function signOut(): Promise<void> {
  await supabase.auth.signOut();
}
