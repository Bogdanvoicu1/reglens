// Build-time configuration (Vite). One Supabase project per build; values come
// from frontend/.env (see .env.example). We fail fast on a missing var so a
// misconfigured build surfaces at boot instead of at first sign-in.

function required(name: string, value: string | undefined): string {
  if (!value) throw new Error(`Missing required environment variable: ${name}`);
  return value;
}

export const env = {
  supabaseUrl: required("VITE_SUPABASE_URL", import.meta.env.VITE_SUPABASE_URL),
  supabaseAnonKey: required("VITE_SUPABASE_ANON_KEY", import.meta.env.VITE_SUPABASE_ANON_KEY),
} as const;
