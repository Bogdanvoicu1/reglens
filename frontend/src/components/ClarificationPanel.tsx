import { useState } from "react";

export function ClarificationPanel({
  questions,
  onSubmit,
}: {
  questions: string[];
  onSubmit: (answers: string[]) => void;
}) {
  const [answers, setAnswers] = useState<string[]>(() => questions.map(() => ""));
  const ready = answers.every((a) => a.trim().length > 0);

  return (
    <div className="mx-auto w-full max-w-2xl px-6 py-10">
      <div className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-amber-500/15 px-2.5 py-1 text-[11px] font-medium text-amber-200">
        A few questions first
      </div>
      <h1 className="text-2xl font-semibold tracking-tight text-white">
        Help sharpen the assessment
      </h1>
      <p className="mt-2 text-sm leading-relaxed text-zinc-500">
        These facts change the classification. Answer them and RegLens will re-run with the added
        context.
      </p>

      <div className="mt-6 space-y-5">
        {questions.map((q, i) => (
          <div key={i}>
            <label className="mb-1.5 block text-sm font-medium text-zinc-300">{q}</label>
            <input
              value={answers[i]}
              onChange={(e) =>
                setAnswers((prev) => prev.map((a, j) => (j === i ? e.target.value : a)))
              }
              className="w-full rounded-xl border border-white/10 bg-zinc-900/80 px-4 py-2.5 text-sm
                         text-zinc-200 placeholder:text-zinc-600 transition
                         focus:border-blue-500/50 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              placeholder="Your answer…"
            />
          </div>
        ))}
        <button
          onClick={() => onSubmit(answers.map((a) => a.trim()))}
          disabled={!ready}
          className="w-full rounded-xl bg-gradient-to-r from-blue-500 to-blue-700 py-2.5 text-sm
                     font-semibold text-white shadow-md shadow-blue-950/50 transition
                     hover:brightness-110 disabled:opacity-40 disabled:shadow-none"
        >
          Continue assessment
        </button>
      </div>
    </div>
  );
}
