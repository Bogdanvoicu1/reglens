import { Fragment } from "react";

// Lightweight renderer for the model's constrained output: paragraphs,
// numbered/bulleted lines, **bold**, and [n] citation chips that scroll to
// the matching source card. Full markdown is deliberately out of scope.

function renderInline(text: string, onCite: (n: number) => void) {
  const parts = text.split(/(\*\*[^*]+\*\*|\[\d+\])/g);
  return parts.map((part, i) => {
    const bold = part.match(/^\*\*([^*]+)\*\*$/);
    if (bold) return <strong key={i}>{bold[1]}</strong>;
    const cite = part.match(/^\[(\d+)\]$/);
    if (cite) {
      const n = Number(cite[1]);
      return (
        <button
          key={i}
          onClick={() => onCite(n)}
          className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full
                     bg-indigo-100 px-1 align-text-top text-xs font-semibold text-indigo-700
                     hover:bg-indigo-200"
          title={`Show source ${n}`}
        >
          {n}
        </button>
      );
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

export function AnswerView({
  text,
  onCite,
}: {
  text: string;
  onCite: (n: number) => void;
}) {
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="space-y-3 text-[15px] leading-relaxed text-slate-800">
      {blocks.map((block, bi) => {
        const lines = block.split("\n");
        const isList = lines.length > 1 && lines.every((l) => /^(\d+\.|[-•])\s/.test(l.trim()));
        if (isList) {
          return (
            <ul key={bi} className="space-y-1 pl-1">
              {lines.map((line, li) => (
                <li key={li}>{renderInline(line.trim(), onCite)}</li>
              ))}
            </ul>
          );
        }
        return <p key={bi}>{renderInline(block, onCite)}</p>;
      })}
    </div>
  );
}
