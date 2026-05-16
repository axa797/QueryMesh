type Variant = "banner" | "inline";

const COPY = {
  title: "The engine room is dark",
  body: "The QueryMesh API isn’t answering—probably saving cloud coins. Flip the backend back on and try again.",
  short: "We can’t reach the API right now. When it’s back, this button will wake up too.",
} as const;

type Props = {
  variant: Variant;
  className?: string;
};

/**
 * Playful, non-technical messaging when the FastAPI host is unreachable.
 */
export function ApiOfflineNotice({ variant, className = "" }: Props) {
  const isBanner = variant === "banner";
  return (
    <div
      className={
        isBanner
          ? `rounded-lg border border-amber-500/30 bg-amber-950/25 px-3 py-2.5 text-left ${className}`
          : `rounded-xl border border-sky-500/25 bg-zinc-900/90 px-4 py-3 text-left shadow-inner ${className}`
      }
      role="alert"
      aria-live="polite"
    >
      <p
        className={
          isBanner
            ? "text-xs font-medium text-amber-200/95"
            : "text-sm font-semibold text-sky-100"
        }
      >
        {COPY.title}
      </p>
      <p className="mt-1 text-xs leading-relaxed text-zinc-400">
        {isBanner ? COPY.short : COPY.body}
      </p>
    </div>
  );
}
