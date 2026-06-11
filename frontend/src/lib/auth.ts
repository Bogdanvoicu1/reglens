// Token storage. For local dev, mint a token with backend/scripts/dev_token.py.
// To use Supabase hosted auth instead, replace getToken with
// supabase.auth.getSession()?.access_token — the API accepts both.

const KEY = "reglens.token";

export const getToken = (): string | null => localStorage.getItem(KEY);
export const setToken = (token: string): void => localStorage.setItem(KEY, token.trim());
export const clearToken = (): void => localStorage.removeItem(KEY);
