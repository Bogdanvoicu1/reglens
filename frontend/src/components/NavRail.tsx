import { signOut } from "../lib/auth";

export type View = "chat" | "assess";

function NavButton({
  active,
  label,
  onClick,
  children,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={`flex w-full flex-col items-center gap-1 rounded-xl py-2.5 text-[10px] font-medium transition ${
        active
          ? "bg-blue-500/15 text-blue-300 ring-1 ring-inset ring-blue-400/30"
          : "text-zinc-500 hover:bg-white/5 hover:text-zinc-300"
      }`}
    >
      <span className="flex h-5 w-5 items-center justify-center">{children}</span>
      {label}
    </button>
  );
}

export function NavRail({ view, onView }: { view: View; onView: (v: View) => void }) {
  return (
    <nav className="flex w-16 shrink-0 flex-col items-center border-r border-white/5 bg-zinc-950 px-2 py-4">
      <div className="mb-6 flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-blue-700 text-base font-bold text-white shadow-lg shadow-blue-950/50">
        R
      </div>
      <div className="flex w-full flex-col gap-1.5">
        <NavButton active={view === "chat"} label="Ask" onClick={() => onView("chat")}>
          <svg viewBox="0 0 24 24" fill="none" className="h-[18px] w-[18px]">
            <path
              d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7a8.5 8.5 0 0 1-.9-3.8A8.38 8.38 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5Z"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </NavButton>
        <NavButton active={view === "assess"} label="Assess" onClick={() => onView("assess")}>
          <svg viewBox="0 0 24 24" fill="none" className="h-[18px] w-[18px]">
            <path
              d="M9 4h6a2 2 0 0 1 2 2v0a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v0a2 2 0 0 1 2-2Z"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
            <path
              d="M7 6H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-1M9 13l2 2 4-4"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </NavButton>
      </div>
      <button
        onClick={() => {
          void signOut().finally(() => window.location.reload());
        }}
        title="Sign out"
        className="mt-auto flex h-9 w-9 items-center justify-center rounded-xl text-zinc-600 transition hover:bg-white/5 hover:text-zinc-300"
      >
        <svg viewBox="0 0 24 24" fill="none" className="h-[18px] w-[18px]">
          <path
            d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </nav>
  );
}
