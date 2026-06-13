import { useState } from "react";

const SAMPLE = `We are a Berlin-based B2B SaaS. Our machine-learning model parses CVs and ranks job applicants for EU employers; recruiters see ranked shortlists and make every interview and hiring decision themselves. We host on AWS in Frankfurt and process applicant data on each employer's documented instructions.`;

const MIN = 80;

export function AssessmentIntake({
  onStart,
}: {
  onStart: (description: string, title: string, clarify: boolean) => void;
}) {
  const [description, setDescription] = useState("");
  const [title, setTitle] = useState("");
  const [clarify, setClarify] = useState(true);

  const tooShort = description.trim().length < MIN;

  return (
    <div className="mx-auto w-full max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight text-white">New assessment</h1>
      <p className="mt-2 text-sm leading-relaxed text-zinc-500">
        Describe the AI system or product you are building. RegLens classifies it against the EU
        AI Act and GDPR and returns a grounded readiness report — obligations, gaps, and a
        remediation roadmap, every claim cited to the article.
      </p>

      <div className="mt-6 space-y-4">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title (optional)"
          className="w-full rounded-xl border border-white/10 bg-zinc-900/80 px-4 py-2.5 text-sm
                     text-zinc-200 placeholder:text-zinc-600 transition
                     focus:border-blue-500/50 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
        />
        <div>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={9}
            placeholder="Describe the system: what it does, who builds and uses it, what data it processes, where it runs…"
            className="w-full resize-y rounded-xl border border-white/10 bg-zinc-900/80 px-4 py-3
                       text-sm leading-relaxed text-zinc-200 placeholder:text-zinc-600 transition
                       focus:border-blue-500/50 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          />
          <div className="mt-1.5 flex items-center justify-between text-[11px] text-zinc-600">
            <button
              onClick={() => setDescription(SAMPLE)}
              className="text-blue-400/80 transition hover:text-blue-300"
            >
              Use a sample description
            </button>
            <span className={tooShort ? "text-zinc-600" : "text-zinc-500"}>
              {description.trim().length} / {MIN} min
            </span>
          </div>
        </div>

        <label className="flex cursor-pointer items-center gap-2.5 text-sm text-zinc-400">
          <input
            type="checkbox"
            checked={clarify}
            onChange={(e) => setClarify(e.target.checked)}
            className="h-4 w-4 rounded border-white/20 bg-zinc-900 accent-blue-500"
          />
          Ask clarifying questions if key facts are missing
        </label>

        <button
          onClick={() => onStart(description.trim(), title.trim(), clarify)}
          disabled={tooShort}
          className="w-full rounded-xl bg-gradient-to-r from-blue-500 to-blue-700 py-2.5 text-sm
                     font-semibold text-white shadow-md shadow-blue-950/50 transition
                     hover:brightness-110 disabled:opacity-40 disabled:shadow-none"
        >
          Run assessment
        </button>
        <p className="text-center text-[11px] text-zinc-600">
          Regulatory readiness analysis, not legal advice.
        </p>
      </div>
    </div>
  );
}
