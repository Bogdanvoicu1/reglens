// The app's single Supabase client. supabase-js persists the session in
// localStorage and refreshes the access token in the background; useSession()
// subscribes to it, and api.ts reads the current token on demand — so there's
// no second copy of the token for the app to keep in sync.

import { createClient } from "@supabase/supabase-js";

import { env } from "./env";

export const supabase = createClient(env.supabaseUrl, env.supabaseAnonKey);
