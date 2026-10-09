/** Decorative light-trail waves from the reference design. Never data: aria-hidden, behind
 *  content, and kept out of the chart panel so nobody mistakes them for a price line. */
export function Waves({ className = "" }: { className?: string }) {
  const paths = Array.from({ length: 9 }, (_, i) => {
    const y = 60 + i * 3.2;
    const a = 22 + i * 2.4;
    return `M-10 ${y} C 50 ${y - a}, 90 ${y + a}, 150 ${y - a * 0.4} S 250 ${y + a * 0.9}, 330 ${y - a * 0.6}`;
  });
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 320 140"
      preserveAspectRatio="none"
      className={`pointer-events-none absolute ${className}`}
    >
      <defs>
        <linearGradient id="mm-wave" x1="0" x2="1">
          <stop offset="0" stopColor="#6d5dfc" stopOpacity="0" />
          <stop offset="0.45" stopColor="#7c6cff" stopOpacity="0.55" />
          <stop offset="1" stopColor="#38bdf8" stopOpacity="0" />
        </linearGradient>
      </defs>
      {paths.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="url(#mm-wave)" strokeWidth={0.7} opacity={0.35 + (i % 3) * 0.15} />
      ))}
    </svg>
  );
}
