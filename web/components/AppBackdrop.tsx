/**
 * Decorative full-viewport layers behind app chrome (does not intercept pointer events).
 */
export function AppBackdrop() {
  return (
    <div
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
      aria-hidden
    >
      <div className="qm-mesh-grid absolute inset-0 opacity-[0.35]" />
      <div className="absolute -left-[20%] top-0 h-[min(70vh,560px)] w-[min(90vw,640px)] rounded-full bg-sky-500/15 blur-3xl" />
      <div className="absolute -right-[15%] bottom-0 h-[min(55vh,440px)] w-[min(75vw,520px)] rounded-full bg-indigo-600/14 blur-3xl" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_85%_55%_at_50%_-15%,rgba(56,189,248,0.09),transparent_55%)]" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_70%_45%_at_100%_100%,rgba(99,102,241,0.08),transparent_50%)]" />
      <div className="absolute inset-0 bg-gradient-to-b from-zinc-950/40 via-transparent to-zinc-950" />
    </div>
  );
}
