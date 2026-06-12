import { Fragment } from "react";

// Lightweight renderer for the model's constrained output: paragraphs,
// numbered/bulleted lines, **bold**, and [n] citation chips that scroll to
// the matching source card. Full markdown is deliberately out of scope.

function renderInline(text: string, onCite: (n: number) => void) {
  const parts = text.split(/(\*\*[^*]+\*\*|\[\d+\])/g);
  return parts.map((part, i) => {
    const bold = part.match(/^\*\*([^*]+)\*\*$/);
    if (bold) return <strong key={i} className="font-semibold text-zinc-100">{bold[1]}</strong>;
    const cite = part.match(/^\[(\d+)\]$/);
    if (cite) {
      const n = Number(cite[1]);
      return (
        <button
          key={i}
          onClick={() => onCite(n)}
          title={`Show source ${n}`}
          className="mx-0.5 inline-flex h-4.5 min-w-4.5 -translate-y-0.5 items-center
                     justify-center rounded-md bg-blue-500/15 px-1 text-[10px] font-bold
                     text-blue-300 ring-1 ring-inset ring-blue-400/30 transition
                     hover:bg-blue-500/30 hover:text-blue-200"
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
  streaming = false,
}: {
  text: string;
  onCite: (n: number) => void;
  streaming?: boolean;
}) {
  const blocks = text.split(/\n{2,}/);
  return (
    <div
      className={`space-y-3 text-[14.5px] leading-relaxed text-zinc-300 ${
        streaming ? "streaming-caret" : ""
      }`}
    >
      {blocks.map((block, bi) => {
        const lines = block.split("\n");
        const isList = lines.length > 1 && lines.every((l) => /^(\d+\.|[-•])\s/.test(l.trim()));
        if (isList) {
          return (
            <ul key={bi} className="space-y-1.5 pl-1">
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
