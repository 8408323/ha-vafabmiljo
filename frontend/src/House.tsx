// Isometric house with its bins, same projection style as the villa-energy panel. Pure SVG, drawn back to front.
// Bins due today/tomorrow roll out to the curb; the next pickup's bins glow.

type V = [number, number, number];
const S = 34, CX = 320, CY = 135;
// isometric projection: x runs right-down, y left-down, z up
const P = ([x, y, z]: V): [number, number] => [CX + (x - y) * 0.866 * S, CY + (x + y) * 0.5 * S - z * S];
const pts = (vs: V[]) => vs.map((v) => P(v).join(",")).join(" ");

// Bins as at Öster Råby: green Restavfall, brown 140 l Matavfall, black two-lid SULO for plastic + paper.
// Sizes in metres (approx. EN 840: w = width along the wall, d = depth, h = height), drawn at 1.3x so they read at this scale.
type Spec = { re: RegExp; body: string; lid: string; w: number; d: number; h: number; split?: boolean };
const SPECS: Spec[] = [
  { re: /papp|plast|förpack|tidning/i, body: "#24272c", lid: "#30343b", w: 0.86, d: 0.87, h: 1.1, split: true },
  { re: /mat|bio|kompost/i, body: "#6b4226", lid: "#7a4e30", w: 0.48, d: 0.555, h: 1.065 },
  { re: /rest|hush/i, body: "#7fa66a", lid: "#9cc08a", w: 0.48, d: 0.73, h: 1.07 },
];
const OTHER: Spec = { re: /./, body: "#4a5260", lid: "#5d6675", w: 0.58, d: 0.73, h: 1.07 };
const spec = (type: string) => SPECS.find((x) => x.re.test(type)) ?? OTHER;
export const binColor = (type: string) => { const s = spec(type); return s === SPECS[0] ? "#8e44ad" : s.lid; };
const K = 1.3;

export type SceneBin = { type: string; when: string; sub: string; days: number | null; next: boolean };

// axis-aligned box seen from the front-right: front face (y = y1), right face (x = x1), top (z = z1)
function box(x0: number, x1: number, y0: number, y1: number, z0: number, z1: number, front: string, side: string, top: string) {
  return <g>
    <polygon points={pts([[x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]])} fill={side} />
    <polygon points={pts([[x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]])} fill={front} />
    <polygon points={pts([[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]])} fill={top} />
  </g>;
}

const shade = (hex: string, f: number) =>
  "#" + [1, 3, 5].map((i) => Math.round(Math.min(255, parseInt(hex.slice(i, i + 2), 16) * f)).toString(16).padStart(2, "0")).join("");

function Bin({ x, y, type, glow }: { x: number; y: number; type: string; glow: boolean }) {
  const s = spec(type), w = s.w * K, d = s.d * K, h = s.h * K;
  const [gx, gy] = P([x + w / 2, y + d / 2, 0]);
  const face = (x0: number, x1: number, z0: number, z1: number, fill: string) =>
    <polygon points={pts([[x0, y + d + 0.01, z0], [x1, y + d + 0.01, z0], [x1, y + d + 0.01, z1], [x0, y + d + 0.01, z1]])} fill={fill} />;
  const top = (x0: number, x1: number, y0: number, y1: number, z: number, fill: string) =>
    <polygon points={pts([[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]])} fill={fill} />;
  return <g>
    {glow && <ellipse cx={gx} cy={gy} rx={22 + 22 * w} ry={12 + 12 * w} className="bin-glow" />}
    {box(x, x + w, y, y + d, 0, h, s.body, shade(s.body, 0.78), shade(s.body, 1.15))}
    {/* lid with a small overhang, plus the handle bar at the back */}
    {box(x - 0.04, x + w + 0.04, y - 0.04, y + d + 0.06, h, h + 0.1, s.lid, shade(s.lid, 0.78), shade(s.lid, 1.18))}
    {box(x + 0.08, x + w - 0.08, y - 0.12, y - 0.04, h + 0.05, h + 0.16, shade(s.lid, 0.7), shade(s.lid, 0.6), shade(s.lid, 0.9))}
    {face(x + 0.12, x + w - 0.12, h - 0.18, h - 0.08, shade(s.body, 0.6))}
    {s.split ? <>
      {/* two lids on a centre hinge, plastic (purple) and paper (beige) stickers */}
      {top(x + w / 2 - 0.05, x + w / 2 + 0.05, y - 0.04, y + d + 0.06, h + 0.14, "#15171a")}
      {top(x + 0.1, x + 0.28, y + d - 0.38, y + d - 0.14, h + 0.101, "#9b3fc4")}
      {top(x + w - 0.28, x + w - 0.1, y + d - 0.38, y + d - 0.14, h + 0.101, "#d9b98a")}
    </> : top(x + w / 2 - 0.12, x + w / 2 + 0.12, y + 0.05, y + d - 0.05, h + 0.105, shade(s.lid, 1.08))}
  </g>;
}

function tree(x: number, y: number) {
  const [tx, ty] = P([x, y, 0]);
  return <g key={`${x},${y}`}><rect x={tx - 2} y={ty - 26} width={4} height={26} rx={2} fill="#7a5a3a" />
    <ellipse cx={tx} cy={ty - 44} rx={15} ry={24} fill="#22b07d" /><ellipse cx={tx - 4} cy={ty - 50} rx={7} ry={11} fill="#3ccf96" opacity={0.6} /></g>;
}

export default function House({ bins, truck }: { bins: SceneBin[]; truck: boolean }) {
  // bins side by side along the front wall, each as wide as its real counterpart
  const xs = bins.reduce<number[]>((acc, b, i) => [...acc, i ? acc[i - 1] + spec(bins[i - 1].type).w * K + 0.25 : 0.3], []);
  const home = (i: number): V => [xs[i], 3.75, 0];
  const curb = (i: number): V => [xs[i], 6.0, 0];
  const out = (b: SceneBin) => b.days != null && b.days <= 1;
  // draw the bins still by the wall first, the ones out at the curb (closer to the viewer) last
  const order = bins.map((b, i) => [b, i] as const).sort(([a], [b]) => Number(out(a)) - Number(out(b)));
  return (
    <svg viewBox="0 0 640 430" className="house-scene" role="img" aria-label="house with waste bins">
      <defs>
        <linearGradient id="hs-wall" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#f4f7fb" /><stop offset="100%" stopColor="#dde4ee" />
        </linearGradient>
        <radialGradient id="hs-ground" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--vm-accent)" stopOpacity="0.16" /><stop offset="100%" stopColor="var(--vm-accent)" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx={P([3, 4, 0])[0]} cy={P([3, 4, 0])[1]} rx={300} ry={140} fill="url(#hs-ground)" />
      {/* plot, path to the street, street with its centre line */}
      <polygon points={pts([[-1.5, -0.5, 0], [9, -0.5, 0], [9, 6.9, 0], [-1.5, 6.9, 0]])} className="hs-plot" />
      <polygon points={pts([[3.5, 3.5, 0], [4.5, 3.5, 0], [4.5, 6.9, 0], [3.5, 6.9, 0]])} className="hs-path" />
      <polygon points={pts([[-1.5, 6.9, 0], [9, 6.9, 0], [9, 8.6, 0], [-1.5, 8.6, 0]])} className="hs-street" />
      <polyline points={pts([[-1.5, 7.75, 0], [9, 7.75, 0]])} className="hs-lane" />
      {tree(-1, 0.4)}{tree(-0.6, -0.2)}

      {/* house: side wall with gable, front wall, windows, door, roof */}
      <polygon points={pts([[6, 0, 0], [6, 3.5, 0], [6, 3.5, 2.6], [6, 1.75, 4.3], [6, 0, 2.6]])} fill="#c9d3e0" stroke="#b7c2d1" />
      <polygon points={pts([[0, 3.5, 0], [6, 3.5, 0], [6, 3.5, 2.6], [0, 3.5, 2.6]])} fill="url(#hs-wall)" stroke="#c3ccd8" />
      {[[0.5, 1.4], [1.9, 2.8], [5, 5.6]].map(([a, b], i) => (
        <polygon key={i} points={pts([[a, 3.5, 1.2], [b, 3.5, 1.2], [b, 3.5, 2.1], [a, 3.5, 2.1]])} className="hs-window" />
      ))}
      <polygon points={pts([[3.6, 3.5, 0], [4.4, 3.5, 0], [4.4, 3.5, 1.9], [3.6, 3.5, 1.9]])} fill="#8a6a4a" />
      {[0.8, 2.1].map((y0, i) => (
        <polygon key={i} points={pts([[6, y0, 1.2], [6, y0 + 0.7, 1.2], [6, y0 + 0.7, 2.1], [6, y0, 2.1]])} className="hs-window side" />
      ))}
      <polygon points={pts([[6.3, 1.75, 4.3], [6.3, -0.4, 2.45], [6.3, -0.4, 2.3], [6.3, 1.75, 4.15]])} fill="#1d2027" />
      <polygon points={pts([[-0.3, 3.9, 2.45], [6.3, 3.9, 2.45], [6.3, 1.75, 4.3], [-0.3, 1.75, 4.3]])} className="hs-roof" />
      <polygon points={pts([[6.3, 3.9, 2.45], [6.3, 3.9, 2.3], [6.3, 1.75, 4.15], [6.3, 1.75, 4.3]])} fill="#1d2027" />
      {tree(8, 3.2)}

      {order.map(([b, i]) => {
        const [hx, hy] = P(home(i)), [cx, cy] = P(curb(i));
        const [dx, dy] = out(b) ? [cx - hx, cy - hy] : [0, 0];
        return <g key={b.type} className="bin" style={{ transform: `translate(${dx}px,${dy}px)` }}>
          <Bin x={home(i)[0]} y={home(i)[1]} type={b.type} glow={b.next} />
        </g>;
      })}

      {truck && <g className="truck">
        {box(4, 7.6, 7.0, 8.3, 0.35, 2.2, "#2f9e5b", "#257d48", "#3cb96c")}
        {box(7.6, 8.6, 7.0, 8.3, 0.35, 1.6, "#e9eef5", "#c9d3e0", "#f4f7fb")}
        <polygon points={pts([[8.61, 7.2, 1.0], [8.61, 8.1, 1.0], [8.61, 8.1, 1.45], [8.61, 7.2, 1.45]])} fill="#9fd3f2" />
      </g>}

      {/* labels in a column on the left, each with a leader line to its bin's lid */}
      {bins.map((b, i) => {
        const ly = 40 + i * 62, [x, y] = (out(b) ? curb : home)(i), sp = spec(b.type);
        const [tx, ty] = P([x + sp.w * K / 2, y + sp.d * K / 2, sp.h * K + 0.1]);
        return <g key={b.type} className="hs-tag">
          <polyline points={`150,${ly + 22} 162,${ly + 22} ${tx},${ty}`} className="hs-leader" />
          <circle cx={tx} cy={ty} r={2.5} fill={binColor(b.type)} />
          <text className="hs-title" x={16} y={ly}>{b.type}</text>
          <text className="hs-value" x={16} y={ly + 22} style={{ fill: b.next ? "var(--vm-accent)" : undefined }}>{b.when}</text>
          <text className="hs-sub" x={16} y={ly + 38}>{b.sub}</text>
        </g>;
      })}
    </svg>
  );
}
