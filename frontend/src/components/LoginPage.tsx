import { useState } from "react";
import { supabase } from "../lib/supabase";

const FEATURES = [
  ["Ask, with citations", "Question the EU AI Act and GDPR; every claim links to the exact article or recital, or it's refused."],
  ["Readiness assessments", "Describe your AI system — get a grounded report: risk classification, obligations, gap analysis and a remediation roadmap."],
  ["Eval- & safety-gated", "Faithfulness 1.00 on a versioned golden dataset; prohibited-practice detection never silently clears."],
];

const CARD = "rounded-2xl border border-white/10 bg-zinc-900/70 p-6 shadow-2xl shadow-black/40 backdrop-blur";
const INPUT =
  "w-full rounded-xl border border-white/10 bg-zinc-950/80 px-4 py-2.5 text-sm text-zinc-200 " +
  "placeholder:text-zinc-600 transition focus:border-blue-500/60 focus:outline-none focus:ring-2 focus:ring-blue-500/20";
const BUTTON =
  "w-full rounded-xl bg-gradient-to-r from-blue-500 to-blue-700 py-2.5 text-sm font-semibold text-white " +
  "shadow-lg shadow-blue-900/40 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none";

function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) setError(error.message);
    // On success, useSession's listener flips the app in — nothing to do here.
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

export function LoginPage() {
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
            Grounded Q&A <span className="text-zinc-300">and compliance readiness reports</span>{" "}
            over the EU AI Act and GDPR — hybrid retrieval, citation-validated generation, and a
            typed assessment agent, multi-tenant and eval-gated.
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

        <LoginForm />
      </div>
    </div>
  );
}
