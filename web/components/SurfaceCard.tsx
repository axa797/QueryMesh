import type { ReactNode } from "react";

type Props = {
  children: ReactNode;
  className?: string;
};

/** Shared elevated panel for landing and auth screens. */
export function SurfaceCard({ children, className = "" }: Props) {
  return (
    <div
      className={`rounded-2xl border border-white/10 bg-zinc-900/45 px-8 py-10 shadow-[0_24px_60px_-12px_rgba(0,0,0,0.55)] backdrop-blur-md ring-1 ring-white/[0.06] sm:px-10 ${className}`}
    >
      {children}
    </div>
  );
}
