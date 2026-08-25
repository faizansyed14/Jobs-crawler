import { useEffect, useRef } from "react";
import type { JobItem, LocationMeta, PortalMeta } from "../api";

type Props = {
  jobs: JobItem[];
  total: number;
  loaded: number;
  hasMore: boolean;
  loadingMore: boolean;
  portals: PortalMeta[];
  filterPortal: string;
  locations: LocationMeta[];
  filterLocation: string;
  onFilterPortal: (value: string) => void;
  onFilterLocation: (value: string) => void;
  onExport: () => void;
  onClear: () => void;
  clearing?: boolean;
  onLoadMore: () => void;
};

function portalLabel(
  portals: PortalMeta[],
  key: string | null | undefined
): string {
  if (!key) return "—";
  return portals.find((p) => p.key === key)?.label ?? key;
}

export function JobsPanel({
  jobs,
  total,
  loaded,
  hasMore,
  loadingMore,
  portals,
  filterPortal,
  locations,
  filterLocation,
  onFilterPortal,
  onFilterLocation,
  onExport,
  onClear,
  clearing = false,
  onLoadMore,
}: Props) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const onLoadMoreRef = useRef(onLoadMore);
  const hasMoreRef = useRef(hasMore);
  const loadingMoreRef = useRef(loadingMore);

  useEffect(() => {
    onLoadMoreRef.current = onLoadMore;
    hasMoreRef.current = hasMore;
    loadingMoreRef.current = loadingMore;
  });

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        if (!hasMoreRef.current || loadingMoreRef.current) return;
        onLoadMoreRef.current();
      },
      { rootMargin: "240px" }
    );
    obs.observe(node);
    return () => obs.disconnect();
  }, []);

  return (
    <section className="card">
      <div className="card-head row">
        <div>
          <h2>Job inventory</h2>
          <p>
            Showing {loaded.toLocaleString()} of {total.toLocaleString()} · scroll
            loads next 50 (up to full set)
          </p>
        </div>
        <div className="toolbar">
          <select
            value={filterPortal}
            onChange={(e) => onFilterPortal(e.target.value)}
            aria-label="Filter by portal"
          >
            <option value="all">All portals</option>
            {portals.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
          <select
            value={filterLocation}
            onChange={(e) => onFilterLocation(e.target.value)}
            aria-label="Filter by crawl location"
          >
            <option value="">All locations</option>
            {locations.map((loc) => (
              <option key={loc.key} value={loc.key}>
                {loc.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn ghost"
            disabled={!total}
            onClick={onExport}
          >
            Export Excel
          </button>
          <button
            type="button"
            className="btn ghost danger"
            disabled={!total || clearing}
            onClick={onClear}
          >
            {clearing ? "Clearing…" : "Clear jobs"}
          </button>
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Portal</th>
              <th>Title</th>
              <th>Company</th>
              <th>Location</th>
              <th>Salary</th>
              <th>Posted</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={`${job.source_portal ?? "x"}:${job.job_id}`}>
                <td>
                  <span className="portal-tag">
                    {portalLabel(portals, job.source_portal)}
                  </span>
                </td>
                <td className="title-cell">{job.title}</td>
                <td>{job.company_name}</td>
                <td>{job.location || job.search_location || "—"}</td>
                <td className="mono muted">{job.salary || "—"}</td>
                <td className="mono muted">
                  {new Date(job.posted_at).toLocaleString()}
                </td>
                <td>
                  <div className="row-actions">
                    <a href={job.url} target="_blank" rel="noreferrer">
                      Open
                    </a>
                    <button
                      type="button"
                      className="btn tiny"
                      onClick={() => void navigator.clipboard.writeText(job.url)}
                    >
                      Copy
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!jobs.length && (
              <tr>
                <td colSpan={7} className="empty">
                  No jobs stored yet. Start a crawl to populate inventory.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div ref={sentinelRef} className="scroll-sentinel">
        {loadingMore && <span className="muted">Loading more jobs…</span>}
        {!loadingMore && hasMore && (
          <button type="button" className="btn ghost" onClick={onLoadMore}>
            Load next 50
          </button>
        )}
        {!hasMore && jobs.length > 0 && (
          <span className="muted">All {total.toLocaleString()} records loaded</span>
        )}
      </div>
    </section>
  );
}
