import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { formatBytes, formatTickBytes, niceByteScale, niceScale } from "../lib/format";

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(el);
    setWidth(Math.floor(el.getBoundingClientRect().width));
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

interface Tip {
  x: number;
  y: number;
  content: ReactNode;
}

function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip) return null;
  return (
    <div className="chart-tip" style={{ left: tip.x, top: tip.y }}>
      {tip.content}
    </div>
  );
}

const PAD = { top: 12, right: 12, bottom: 26, left: 64 };

/** Column path with a 4px rounded data-end and a square baseline. */
function columnPath(x: number, y: number, w: number, base: number) {
  const h = base - y;
  if (h <= 0) return "";
  const r = Math.min(4, w / 2, h);
  return `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${base}Z`;
}

// ------------------------------------------------------------------ area (time series)

export function AreaChart({
  points,
  height = 220,
  formatValue = (v) => `${formatBytes(v)}/s`,
  formatTick = (v) => formatTickBytes(v),
  formatX,
  bytes = true,
  emptyText = "暂无数据",
}: {
  points: [number, number][];
  height?: number;
  formatValue?: (v: number) => string;
  formatTick?: (v: number) => string;
  formatX: (x: number) => string;
  bytes?: boolean;
  emptyText?: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const innerW = Math.max(0, width - PAD.left - PAD.right);
  const innerH = height - PAD.top - PAD.bottom;

  const model = useMemo(() => {
    if (points.length < 2 || innerW <= 0) return null;
    const x0 = points[0][0];
    const x1 = points[points.length - 1][0];
    const maxY = Math.max(...points.map((p) => p[1]));
    const scale = bytes ? niceByteScale(maxY) : niceScale(maxY);
    const sx = (x: number) => PAD.left + ((x - x0) / Math.max(1, x1 - x0)) * innerW;
    const sy = (y: number) => PAD.top + innerH - (y / scale.max) * innerH;
    const line = points.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("");
    const area = `${line}L${sx(x1).toFixed(1)},${PAD.top + innerH}L${sx(x0).toFixed(1)},${PAD.top + innerH}Z`;
    const ticks: number[] = [];
    for (let v = 0; v <= scale.max + scale.step / 2; v += scale.step) ticks.push(v);
    const xTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => x0 + (x1 - x0) * f);
    return { sx, sy, line, area, ticks, xTicks };
  }, [points, innerW, innerH, bytes]);

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    if (!model) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left + PAD.left;
    let best = 0;
    let bestDist = Infinity;
    points.forEach((p, i) => {
      const d = Math.abs(model.sx(p[0]) - px);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    setHover(best);
  };

  const hovered = hover != null && model ? points[hover] : null;
  const tip: Tip | null =
    hovered && model
      ? {
          x: model.sx(hovered[0]),
          y: model.sy(hovered[1]),
          content: (
            <>
              <div className="chart-tip-title">{formatX(hovered[0])}</div>
              <div className="chart-tip-row">
                <b>{formatValue(hovered[1])}</b>
              </div>
            </>
          ),
        }
      : null;

  return (
    <div className="chart" ref={ref} style={{ height }}>
      {!model ? (
        <div className="empty" style={{ height }}>
          {emptyText}
        </div>
      ) : (
        <svg width={width} height={height} role="img">
          {model.ticks.map((t) => (
            <g key={t}>
              <line className={t === 0 ? "baseline" : "grid-line"} x1={PAD.left} x2={width - PAD.right} y1={model.sy(t)} y2={model.sy(t)} />
              <text className="tick" x={PAD.left - 10} y={model.sy(t) + 4} textAnchor="end">
                {formatTick(t)}
              </text>
            </g>
          ))}
          {model.xTicks.map((t, i) => (
            <text key={i} className="tick" x={model.sx(t)} y={height - 6} textAnchor={i === 0 ? "start" : i === 4 ? "end" : "middle"}>
              {formatX(t)}
            </text>
          ))}
          <path d={model.area} fill="var(--series-1-wash)" />
          <path d={model.line} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {hovered && (
            <>
              <line className="baseline" x1={model.sx(hovered[0])} x2={model.sx(hovered[0])} y1={PAD.top} y2={PAD.top + innerH} />
              <circle cx={model.sx(hovered[0])} cy={model.sy(hovered[1])} r={5} fill="var(--series-1)" stroke="var(--bg-card)" strokeWidth={2} />
            </>
          )}
          <rect
            x={PAD.left}
            y={PAD.top}
            width={innerW}
            height={innerH}
            fill="transparent"
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
          />
        </svg>
      )}
      <Tooltip tip={tip} />
    </div>
  );
}

// ------------------------------------------------------------------ columns

export interface Column {
  key: string;
  label: string;
  value: number;
  tip: ReactNode;
}

export function ColumnChart({
  columns,
  height = 240,
  bytes = false,
  labelEvery,
  padLeft = PAD.left,
}: {
  columns: Column[];
  height?: number;
  bytes?: boolean;
  labelEvery?: number;
  padLeft?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const pad = { ...PAD, left: padLeft };
  const innerW = Math.max(0, width - pad.left - pad.right);
  const innerH = height - pad.top - pad.bottom;
  const max = Math.max(0, ...columns.map((c) => c.value));
  const scale = bytes ? niceByteScale(max) : niceScale(max);
  const band = columns.length ? innerW / columns.length : 0;
  const barW = Math.max(2, Math.min(24, band - 2));
  const sy = (v: number) => pad.top + innerH - (v / scale.max) * innerH;
  const ticks: number[] = [];
  for (let v = 0; v <= scale.max + scale.step / 2; v += scale.step) ticks.push(v);
  const every = labelEvery ?? Math.max(1, Math.ceil(columns.length / Math.max(1, Math.floor(innerW / 56))));
  const base = pad.top + innerH;

  const hovered = hover != null ? columns[hover] : null;
  const tip: Tip | null = hovered
    ? { x: pad.left + band * hover! + band / 2, y: sy(hovered.value), content: hovered.tip }
    : null;

  return (
    <div className="chart" ref={ref} style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img">
          {ticks.map((t) => (
            <g key={t}>
              <line className={t === 0 ? "baseline" : "grid-line"} x1={pad.left} x2={width - pad.right} y1={sy(t)} y2={sy(t)} />
              {padLeft > 0 && (
                <text className="tick" x={pad.left - 10} y={sy(t) + 4} textAnchor="end">
                  {bytes ? formatTickBytes(t) : Number.isInteger(t) ? t.toLocaleString() : t.toFixed(1)}
                </text>
              )}
            </g>
          ))}
          {columns.map((c, i) => {
            const x = pad.left + band * i + (band - barW) / 2;
            return (
              <g key={c.key}>
                {hover === i && <rect x={pad.left + band * i} y={pad.top} width={band} height={innerH} fill="var(--bg-hover)" />}
                <path d={columnPath(x, sy(c.value), barW, base)} fill="var(--series-1)" opacity={hover == null || hover === i ? 1 : 0.55} />
                {i % every === 0 && (
                  <text className="tick" x={pad.left + band * i + band / 2} y={height - 6} textAnchor="middle">
                    {c.label}
                  </text>
                )}
                <rect
                  x={pad.left + band * i}
                  y={pad.top}
                  width={band}
                  height={innerH}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                />
              </g>
            );
          })}
        </svg>
      )}
      <Tooltip tip={tip} />
    </div>
  );
}

// ------------------------------------------------------------------ bar list

export function BarList({
  items,
  format,
  sub,
}: {
  items: { key: string; label: string; value: number }[];
  format: (v: number) => string;
  sub?: (key: string) => string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  if (!items.length) return <div className="empty">暂无数据</div>;
  return (
    <div className="barlist">
      {items.map((item) => (
        <div className="barlist-row" key={item.key} title={`${item.label}：${format(item.value)}`}>
          <span className="barlist-label">{item.label}</span>
          <span className="barlist-value">
            {format(item.value)}
            {sub && <span className="muted"> · {sub(item.key)}</span>}
          </span>
          <div className="barlist-track">
            <span style={{ width: `${Math.max(1.5, (item.value / max) * 100)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ stacked status bar

export function StackBar({ parts }: { parts: { key: string; value: number; color: string; label: string }[] }) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  if (!total) return <div className="stackbar" style={{ background: "var(--divider)" }} />;
  return (
    <div className="stackbar">
      {parts
        .filter((p) => p.value > 0)
        .map((p) => (
          <span key={p.key} title={`${p.label} ${p.value}`} style={{ width: `${(p.value / total) * 100}%`, background: p.color }} />
        ))}
    </div>
  );
}

// ------------------------------------------------------------------ sparkline

export function Sparkline({ values, height = 34 }: { values: number[]; height?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const path = useMemo(() => {
    if (values.length < 2 || width <= 0) return null;
    const max = Math.max(1, ...values);
    const sx = (i: number) => (i / (values.length - 1)) * width;
    const sy = (v: number) => 2 + (height - 4) - (v / max) * (height - 4);
    const line = values.map((v, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join("");
    return { line, area: `${line}L${width},${height}L0,${height}Z` };
  }, [values, width, height]);
  return (
    <div ref={ref} style={{ height, marginTop: 6 }}>
      {path && (
        <svg width={width} height={height} aria-hidden>
          <path d={path.area} fill="var(--series-1-wash)" />
          <path d={path.line} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        </svg>
      )}
    </div>
  );
}
