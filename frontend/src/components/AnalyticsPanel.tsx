import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type JobAnalytics,
  type LocationMeta,
  type PortalMeta,
} from "../api";
import { CITY_COLORS, LineChart, type ChartSeries } from "./LineChart";

type Granularity = "day" | "week" | "month";
type ViewMode = "total" | "city";

type Props = {
  portals: PortalMeta[];
  locations: LocationMeta[];
  refreshKey: number;
};

const GRANULARITY_LABEL: Record<Granularity, string> = {
  day: "Daily",
  week: "Weekly",
  month: "Monthly",
};

function cityLabel(key: string, locations: LocationMeta[]): string {
  return locations.find((l) => l.key === key)?.label ?? key.replace(/_/g, " ");
}

function toSeries(
  data: JobAnalytics,
  mode: ViewMode,
  locations: LocationMeta[]
): ChartSeries[] {
  if (mode === "total") {
    return [
      {
        id: "total",
        label: "All postings",
        color: "#2563eb",
        points: data.timeline.map((p) => ({ x: p.period, y: p.count })),
      },
    ];
  }

  return data.by_city.map((row, i) => ({
    id: row.city,
    label: cityLabel(row.city, locations),
    color: CITY_COLORS[i % CITY_COLORS.length],
    points: row.timeline.map((p) => ({ x: p.period, y: p.count })),
  }));
}

export function AnalyticsPanel({ portals, locations, refreshKey }: Props) {
  const [granularity, setGranularity] = useState<Granularity>("day");
  const [viewMode, setViewMode] = useState<ViewMode>("total");
  const [portal, setPortal] = useState("all");
  const [location, setLocation] = useState("");
  const [data, setData] = useState<JobAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.analytics({
        granularity,
        portal: portal === "all" ? undefined : portal,
        location: location || undefined,
      });
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [granularity, portal, location]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    const id = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(id);
  }, [load]);

  const chartSeries = useMemo(
    () => (data ? toSeries(data, viewMode, locations) : []),
    [data, viewMode, locations]
  );

  const topCity = data?.city_totals[0];

  return (
    <section className="analytics-stack">
      <div className="card analytics-card">
        <div className="card-head">
          <div>
            <h2>Posting analytics</h2>
            <p>Live stats from your job database — grouped by when jobs were posted.</p>
          </div>
          <button
            type="button"
            className="btn ghost tiny"
            disabled={loading}
            onClick={() => void load()}
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        <div className="analytics-toolbar">
          <div className="seg-control" role="tablist" aria-label="Time granularity">
            {(["day", "week", "month"] as Granularity[]).map((g) => (
              <button
                key={g}
                type="button"
                role="tab"
                aria-selected={granularity === g}
                className={granularity === g ? "seg active" : "seg"}
                onClick={() => setGranularity(g)}
              >
                {GRANULARITY_LABEL[g]}
              </button>
            ))}
          </div>

          <div className="seg-control" role="tablist" aria-label="Chart view">
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === "total"}
              className={viewMode === "total" ? "seg active" : "seg"}
              onClick={() => setViewMode("total")}
            >
              Total trend
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === "city"}
              className={viewMode === "city" ? "seg active" : "seg"}
              onClick={() => setViewMode("city")}
              disabled={Boolean(location)}
            >
              By city
            </button>
          </div>

          <div className="analytics-filters">
            <label>
              Portal
              <select value={portal} onChange={(e) => setPortal(e.target.value)}>
                <option value="all">All portals</option>
                {portals.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              City
              <select value={location} onChange={(e) => setLocation(e.target.value)}>
                <option value="">All cities</option>
                {locations.map((l) => (
                  <option key={l.key} value={l.key}>
                    {l.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {error && <div className="banner error">{error}</div>}

        <div className="metric-grid analytics-metrics">
          <div className="metric">
            <span className="metric-label">In range</span>
            <span className="metric-value mono">{data?.total_in_range ?? "—"}</span>
          </div>
          <div className="metric">
            <span className="metric-label">All time</span>
            <span className="metric-value mono">{data?.total_all_time ?? "—"}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Avg / period</span>
            <span className="metric-value mono">{data?.average_per_period ?? "—"}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Peak period</span>
            <span className="metric-value mono">{data?.peak_period_count ?? "—"}</span>
          </div>
        </div>

        <LineChart
          series={chartSeries}
          emptyLabel={
            loading
              ? "Loading chart…"
              : "No postings in this range — run a crawl first."
          }
        />
      </div>

      <div className="analytics-grid">
        <div className="card">
          <div className="card-head compact">
            <h3>By city</h3>
            {topCity && (
              <span className="muted">
                Top: {cityLabel(topCity.city, locations)} ({topCity.count})
              </span>
            )}
          </div>
          <ul className="analytics-list">
            {(data?.city_totals ?? []).slice(0, 12).map((row) => {
              const max = data?.city_totals[0]?.count ?? 1;
              const pct = Math.round((row.count / max) * 100);
              return (
                <li key={row.city}>
                  <div className="analytics-list-row">
                    <span>{cityLabel(row.city, locations)}</span>
                    <strong className="mono">{row.count}</strong>
                  </div>
                  <div className="analytics-bar-track">
                    <div className="analytics-bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                </li>
              );
            })}
            {!loading && !data?.city_totals.length && (
              <li className="muted">No city breakdown yet.</li>
            )}
          </ul>
        </div>

        <div className="card">
          <div className="card-head compact">
            <h3>By portal</h3>
          </div>
          <ul className="analytics-list">
            {(data?.by_portal ?? []).map((row) => {
              const max = data?.by_portal[0]?.count ?? 1;
              const pct = Math.round((row.count / max) * 100);
              const label =
                portals.find((p) => p.key === row.portal)?.label ?? row.portal;
              return (
                <li key={row.portal}>
                  <div className="analytics-list-row">
                    <span>{label}</span>
                    <strong className="mono">{row.count}</strong>
                  </div>
                  <div className="analytics-bar-track">
                    <div
                      className="analytics-bar-fill portal"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </li>
              );
            })}
            {!loading && !data?.by_portal.length && (
              <li className="muted">No portal breakdown yet.</li>
            )}
          </ul>
        </div>
      </div>
    </section>
  );
}
