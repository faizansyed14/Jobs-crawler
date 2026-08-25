import { useMemo, useState } from "react";

export type ChartPoint = { x: string; y: number };

export type ChartSeries = {
  id: string;
  label: string;
  color: string;
  points: ChartPoint[];
};

type Props = {
  series: ChartSeries[];
  height?: number;
  emptyLabel?: string;
};

const PAD = { top: 18, right: 16, bottom: 36, left: 44 };

const CITY_COLORS = [
  "#2563eb",
  "#0f766e",
  "#c2410c",
  "#7c3aed",
  "#be123c",
  "#0369a1",
  "#a16207",
  "#475569",
];

function formatTick(label: string, total: number): string {
  if (total <= 14) return label;
  if (label.includes("-W")) return label.slice(5);
  if (label.length === 7) return label.slice(2);
  return label.slice(5);
}

export function LineChart({ series, height = 260, emptyLabel = "No data yet" }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 720;

  const plot = useMemo(() => {
    const innerW = width - PAD.left - PAD.right;
    const innerH = height - PAD.top - PAD.bottom;
    const allPoints = series.flatMap((s) => s.points);
    if (!allPoints.length) {
      return null;
    }

    const labels = series[0]?.points.map((p) => p.x) ?? [];
    const maxY = Math.max(1, ...allPoints.map((p) => p.y));
    const yTicks = 4;
    const xAt = (idx: number) =>
      PAD.left + (labels.length <= 1 ? innerW / 2 : (idx / (labels.length - 1)) * innerW);
    const yAt = (value: number) => PAD.top + innerH - (value / maxY) * innerH;

    const paths = series.map((s) => {
      const coords = s.points.map((p, idx) => {
        const x = xAt(idx);
        const y = yAt(p.y);
        return `${idx === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
      });
      return { ...s, d: coords.join(" ") };
    });

    const gridY = Array.from({ length: yTicks + 1 }, (_, i) => {
      const value = Math.round((maxY / yTicks) * i);
      return { value, y: yAt(value) };
    });

    return { labels, maxY, paths, gridY, xAt, yAt, innerW, innerH };
  }, [series, height]);

  if (!plot) {
    return (
      <div className="chart-empty" style={{ height }}>
        <span>{emptyLabel}</span>
      </div>
    );
  }

  const tickEvery = Math.max(1, Math.ceil(plot.labels.length / 8));
  const hoverIdx = hover;
  const hoverLabel = hoverIdx != null ? plot.labels[hoverIdx] : null;

  return (
    <div className="line-chart-wrap">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="line-chart"
        role="img"
        aria-label="Job posting trend chart"
        onMouseLeave={() => setHover(null)}
      >
        {plot.gridY.map((g) => (
          <g key={g.value}>
            <line
              x1={PAD.left}
              x2={width - PAD.right}
              y1={g.y}
              y2={g.y}
              className="chart-grid"
            />
            <text x={PAD.left - 8} y={g.y + 4} className="chart-axis-y" textAnchor="end">
              {g.value}
            </text>
          </g>
        ))}

        {plot.labels.map((label, idx) =>
          idx % tickEvery === 0 || idx === plot.labels.length - 1 ? (
            <text
              key={label + idx}
              x={plot.xAt(idx)}
              y={height - 8}
              className="chart-axis-x"
              textAnchor="middle"
            >
              {formatTick(label, plot.labels.length)}
            </text>
          ) : null
        )}

        {hoverIdx != null && (
          <line
            x1={plot.xAt(hoverIdx)}
            x2={plot.xAt(hoverIdx)}
            y1={PAD.top}
            y2={height - PAD.bottom}
            className="chart-hover-line"
          />
        )}

        {plot.paths.map((s) => (
          <path key={s.id} d={s.d} fill="none" stroke={s.color} strokeWidth={2.2} />
        ))}

        {plot.paths.map((s) =>
          s.points.map((p, idx) => (
            <circle
              key={`${s.id}-${idx}`}
              cx={plot.xAt(idx)}
              cy={plot.yAt(p.y)}
              r={hoverIdx === idx ? 4.5 : 3}
              fill={s.color}
              stroke="#fff"
              strokeWidth={1.5}
              opacity={hoverIdx == null || hoverIdx === idx ? 1 : 0.35}
              onMouseEnter={() => setHover(idx)}
            />
          ))
        )}
      </svg>

      {hoverLabel && hoverIdx != null && (
        <div
          className="chart-tooltip"
          style={{
            left: `${((plot.xAt(hoverIdx) / width) * 100).toFixed(1)}%`,
          }}
        >
          <strong>{hoverLabel}</strong>
          {series.map((s) => (
            <div key={s.id}>
              <span className="chart-tooltip-dot" style={{ background: s.color }} />
              {s.label}: {s.points[hoverIdx]?.y ?? 0}
            </div>
          ))}
        </div>
      )}

      {series.length > 1 && (
        <div className="chart-legend">
          {series.map((s, i) => (
            <span key={s.id}>
              <i style={{ background: s.color || CITY_COLORS[i % CITY_COLORS.length] }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export { CITY_COLORS };
