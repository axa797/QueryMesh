import type { SVGAttributes } from "react";

type Props = SVGAttributes<SVGSVGElement> & {
  size?: number;
};

/** Interconnected mesh mark — works on dark UI (nav, headers). */
export function QueryMeshLogo({ size = 28, className, ...rest }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden
      {...rest}
    >
      <defs>
        <linearGradient
          id="qmMarkStroke"
          x1="4"
          y1="6"
          x2="26"
          y2="26"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#7dd3fc" />
          <stop offset="1" stopColor="#818cf8" />
        </linearGradient>
        <linearGradient
          id="qmMarkEdge"
          x1="4"
          y1="6"
          x2="26"
          y2="26"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#38bdf8" stopOpacity="0.25" />
          <stop offset="1" stopColor="#6366f1" stopOpacity="0.35" />
        </linearGradient>
      </defs>
      <rect
        x="2"
        y="2"
        width="28"
        height="28"
        rx="8"
        fill="#0a0a0b"
        stroke="url(#qmMarkStroke)"
        strokeWidth="1.25"
      />
      <g strokeLinecap="round" strokeLinejoin="round">
        <path
          d="M10 12h12M12 20h8M16 8v6M10 20l6-6 6 6"
          stroke="url(#qmMarkEdge)"
          strokeWidth="1.2"
        />
        <path
          d="M16 14l-5-3M16 14l5-3M16 14v6M11 23l5-3 5 3"
          stroke="url(#qmMarkStroke)"
          strokeWidth="1.35"
        />
      </g>
      <circle cx="16" cy="11" r="2.5" fill="#e0f2fe" />
      <circle cx="11" cy="17" r="2" fill="url(#qmMarkStroke)" />
      <circle cx="21" cy="17" r="2" fill="url(#qmMarkStroke)" />
      <circle cx="16" cy="22" r="2.5" fill="#38bdf8" />
      <circle
        cx="16"
        cy="16"
        r="3"
        fill="#0284c7"
        stroke="#e0f2fe"
        strokeWidth="0.8"
      />
    </svg>
  );
}
