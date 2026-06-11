import { useState } from "react";
import { setToken } from "../lib/auth";

export function TokenGate({ onAuthed }: { onAuthed: () => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-lg">
        <h1 className="mb-1 text-2xl font-bold text-slate-900">RegLens</h1>
        <p className="mb-6 text-sm text-slate-500">
          Grounded compliance Q&A over the EU AI Act and GDPR.
        </p>
        <label className="mb-2 block text-sm font-medium text-slate-700">
          Access token
        </label>
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          rows={4}
          placeholder="Paste your JWT…"
          className="mb-2 w-full rounded-lg border border-slate-300 p-2 font-mono text-xs
                     focus:border-indigo-500 focus:outline-none"
        />
        <p className="mb-4 text-xs text-slate-400">
          Sign in with your Supabase session token, or mint a local one:{" "}
          <code className="rounded bg-slate-100 px-1">
            uv run python scripts/dev_token.py
          </code>
        </p>
        <button
          disabled={value.trim().split(".").length !== 3}
          onClick={() => {
            setToken(value);
            onAuthed();
          }}
          className="w-full rounded-lg bg-indigo-600 py-2 font-semibold text-white
                     hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Continue
        </button>
      </div>
    </div>
  );
}
