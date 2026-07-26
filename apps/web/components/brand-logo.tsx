export function BrandLogo({ className = "" }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 224 56"
      xmlns="http://www.w3.org/2000/svg"
    >
      <circle
        cx="28"
        cy="28"
        fill="none"
        r="18"
        stroke="var(--color-ink)"
        strokeWidth="2.5"
      />
      <path d="M28 28V10a18 18 0 0 1 14.6 7.5Z" fill="var(--color-signal)" />
      <path
        d="M28 16a12 12 0 0 0-10.1 18.4"
        fill="none"
        opacity=".72"
        stroke="var(--color-ink)"
        strokeLinecap="round"
        strokeWidth="1.7"
      />
      <path
        d="m16.5 42.5 9.4-20.8a2.3 2.3 0 0 1 4.2 0l9.4 20.8"
        fill="none"
        stroke="var(--color-ink)"
        strokeLinecap="square"
        strokeLinejoin="round"
        strokeWidth="4.7"
      />
      <circle cx="28" cy="34.3" fill="var(--color-signal)" r="2.7" />
      <text
        fontFamily="Arial, Helvetica, sans-serif"
        fontSize="24"
        fontWeight="700"
        letterSpacing="1.5"
        x="59"
        y="36"
      >
        <tspan fill="var(--color-ink)">AI</tspan>
        <tspan fill="var(--color-signal)">·RADAR</tspan>
      </text>
    </svg>
  );
}
