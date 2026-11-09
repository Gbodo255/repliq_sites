/* Original isometric artwork: a tower of captured "layers" (pages/breakpoints)
   stacking into one faithful copy. One layer glows in the accent blue. Built
   from scratch — not derived from any template's illustration. */

type Cube = { top: string; left: string; right: string; stroke: string };

const INK = "#0b0b0d";
const BORDER = "#dfdfdb";

function cubePolys(cx: number, topY: number, w = 118, th = 60, d = 54): {
  top: string;
  left: string;
  right: string;
} {
  const top = `${cx},${topY} ${cx + w},${topY + th} ${cx},${topY + 2 * th} ${cx - w},${topY + th}`;
  const left = `${cx - w},${topY + th} ${cx},${topY + 2 * th} ${cx},${topY + 2 * th + d} ${cx - w},${topY + th + d}`;
  const right = `${cx},${topY + 2 * th} ${cx + w},${topY + th} ${cx + w},${topY + th + d} ${cx},${topY + 2 * th + d}`;
  return { top, left, right };
}

export default function HeroArt({ className }: { className?: string }) {
  const cx = 240;
  const d = 54;
  // 5 stacked cubes from bottom (y high) to top (y low).
  const levels = [300, 246, 192, 138, 84];
  const fills: Cube[] = [
    { top: "#f5f5f3", left: "#e9e9e6", right: "#efefec", stroke: BORDER },
    { top: "#f3f3f1", left: "#e7e7e4", right: "#ededea", stroke: BORDER },
    { top: "#2337ff", left: "#1a28c7", right: "#1f31e6", stroke: "#1a28c7" }, // accent layer
    { top: "#f3f3f1", left: "#e7e7e4", right: "#ededea", stroke: BORDER },
    { top: "#ffffff", left: "#f0f0ed", right: "#f6f6f4", stroke: BORDER },
  ];

  return (
    <svg
      viewBox="0 0 480 520"
      className={className}
      role="img"
      aria-label="Pile de couches répliquées formant une copie fidèle"
    >
      <defs>
        <radialGradient id="rx-glow" cx="50%" cy="38%" r="55%">
          <stop offset="0%" stopColor="#2337ff" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#2337ff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect x="0" y="0" width="480" height="520" fill="url(#rx-glow)" />

      {levels.map((topY, i) => {
        const p = cubePolys(cx, topY, 118, 60, d);
        const f = fills[i];
        return (
          <g key={i}>
            <polygon points={p.left} fill={f.left} stroke={f.stroke} strokeWidth="1.5" strokeLinejoin="round" />
            <polygon points={p.right} fill={f.right} stroke={f.stroke} strokeWidth="1.5" strokeLinejoin="round" />
            <polygon points={p.top} fill={f.top} stroke={f.stroke} strokeWidth="1.5" strokeLinejoin="round" />
          </g>
        );
      })}

      {/* Browser "dots" on the very top layer. */}
      <g transform={`translate(${cx - 44}, ${84 + 52})`}>
        <circle cx="0" cy="0" r="5" fill={INK} opacity="0.22" />
        <circle cx="16" cy="8" r="5" fill={INK} opacity="0.22" />
        <circle cx="32" cy="16" r="5" fill={INK} opacity="0.22" />
      </g>

      {/* Accent "capture" ray pointing at the stack. */}
      <g opacity="0.9">
        <circle cx="408" cy="150" r="7" fill="#2337ff" />
        <path d="M402 156 L300 224" stroke="#2337ff" strokeWidth="2" strokeDasharray="3 6" strokeLinecap="round" />
      </g>
    </svg>
  );
}
