import type { ReactNode } from "react";

/** Chat route shell: stay within `main` width — avoid `w-screen` + translate (causes `main` horizontal overflow). */
export default function ChatLayout({ children }: { children: ReactNode }) {
  return (
    <section className="relative flex h-full min-h-0 flex-1 flex-col">
      <div
        className="pointer-events-none absolute inset-0 z-0 overflow-hidden"
        aria-hidden
      >
        <div className="absolute left-[12%] top-[-10%] h-[min(280px,40vh)] w-[min(90vw,520px)] rounded-full bg-sky-500/12 blur-3xl" />
        <div className="absolute bottom-[-5%] right-[8%] h-[min(220px,32vh)] w-[min(75vw,480px)] rounded-full bg-indigo-600/10 blur-3xl" />
      </div>
      <div className="relative z-0 flex min-h-0 w-full min-w-0 max-w-full flex-1 px-3 pb-2 pt-0 sm:px-5">
        <div className="mx-auto flex min-h-0 w-full max-w-[1480px] flex-1 flex-col">
          {children}
        </div>
      </div>
    </section>
  );
}
