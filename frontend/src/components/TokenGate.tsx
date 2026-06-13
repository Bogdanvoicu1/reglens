import { useState } from "react";
import { setToken } from "../lib/auth";
import { type AppConfig, isSupabaseConfigured } from "../lib/config";
import { getSupabaseClient } from "../lib/supabase";

const FEATURES = [
  ["Cited answers", "Every claim links to the exact article or recital."],
  ["Honest refusals", "Out-of-corpus questions are refused, not improvised."],
  ["Eval-gated quality", "Faithfulness 0.99 · refusal accuracy 1.00 on a versioned golden dataset."],
];

const CARD = "rounded-2xl border border-white/10 bg-zinc-900/70 p-6 shadow-2xl shadow-black/40 backdrop-blur";
const INPUT =
  "w-full rounded-xl border border-white/10 bg-zinc-950/80 px-4 py-2.5 text-sm text-zinc-200 " +
  "placeholder:text-zinc-600 transition focus:border-blue-500/60 focus:outline-none focus:ring-2 focus:ring-blue-500/20";
const BUTTON =
  "w-full rounded-xl bg-gradient-to-r from-blue-500 to-blue-700 py-2.5 text-sm font-semibold text-white " +
  "shadow-lg shadow-blue-900/40 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none";

function SupabaseLogin({ config }: { config: AppConfig }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const supabase = getSupabaseClient(config.supabaseUrl, config.supabaseAnonKey);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) setError(error.message);
    // On success, App's onAuthStateChange writes the token and flips to the app.
  };

  return (
    <form onSubmit={submit} className={CARD}>
      <label className="mb-1.5 block text-sm font-medium text-zinc-300">Email</label>
      <input
        type="email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@company.com"
        className={`${INPUT} mb-4`}
      />
      <label className="mb-1.5 block text-sm font-medium text-zinc-300">Password</label>
      <input
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="••••••••"
        className={`${INPUT} mb-2`}
      />
      {error && <p className="mb-3 text-xs text-red-400">{error}</p>}
      <button type="submit" disabled={busy || !email || !password} className={`${BUTTON} mt-3`}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
      <p className="mt-4 text-center text-[11px] text-zinc-600">
        Regulatory information, not legal advice.
      </p>
    </form>
  );
}

function DevTokenLogin({ onAuthed }: { onAuthed: () => void }) {
  const [value, setValue] = useState("");
  const valid = value.trim().split(".").length === 3;

  return (
    <div className={CARD}>
      <label className="mb-2 block text-sm font-medium text-zinc-300">Access token</label>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={4}
        placeholder="Paste your JWT…"
        className="mb-2 w-full resize-none rounded-xl border border-white/10 bg-zinc-950/80 p-3
                   font-mono text-xs text-zinc-300 placeholder:text-zinc-600
                   focus:border-blue-500/60 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
      />
      <p className="mb-5 text-xs leading-relaxed text-zinc-500">
        Local dev — mint a token:{" "}
        <code className="rounded bg-white/5 px-1.5 py-0.5 text-[11px] text-zinc-400">
          uv run python scripts/dev_token.py
        </code>
      </p>
      <button
        disabled={!valid}
        onClick={() => {
          setToken(value);
          onAuthed();
        }}
        className={BUTTON}
      >
        Continue
      </button>
      <p className="mt-4 text-center text-[11px] text-zinc-600">
        Regulatory information, not legal advice.
      </p>
    </div>
  );
}

export function TokenGate({ config, onAuthed }: { config: AppConfig; onAuthed: () => void }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-zinc-950 p-6">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-150 w-225 -translate-x-1/2
                   rounded-full bg-blue-600/25 blur-[140px]"
      />
      <div className="relative grid w-full max-w-4xl gap-10 md:grid-cols-2 md:items-center">
        <div>
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-blue-700 text-lg font-bold text-white shadow-lg shadow-blue-900/40">
              R
            </div>
            <span className="text-xl font-semibold tracking-tight text-white">RegLens</span>
          </div>
          <h1 className="mb-3 text-3xl font-semibold tracking-tight text-white">
            Compliance answers you can{" "}
            <span className="bg-gradient-to-r from-blue-400 to-sky-300 bg-clip-text text-transparent">
              actually verify
            </span>
            .
          </h1>
          <p className="mb-8 text-sm leading-relaxed text-zinc-400">
            Grounded Q&A over the EU AI Act and GDPR. Hybrid retrieval, citation-validated
            generation, multi-tenant — built as a production RAG system, not a demo.
          </p>
          <ul className="space-y-3">
            {FEATURES.map(([title, body]) => (
              <li key={title} className="flex gap-3">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-400" />
                <p className="text-sm text-zinc-400">
                  <span className="font-medium text-zinc-200">{title}.</span> {body}
                </p>
              </li>
            ))}
          </ul>
        </div>

        {isSupabaseConfigured(config) ? (
          <SupabaseLogin config={config} />
        ) : (
          <DevTokenLogin onAuthed={onAuthed} />
        )}
      </div>
    </div>
  );
}
