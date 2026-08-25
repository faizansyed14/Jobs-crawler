import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type CrawlProgress,
  type CrawlResult,
  type IndustryMeta,
  type JobItem,
  type LocationMeta,
  type PacingMeta,
  type PortalMeta,
} from "./api";
import { AnalyticsPanel } from "./components/AnalyticsPanel";
import { AutoCrawlModal } from "./components/AutoCrawlModal";
import { CrawlControls } from "./components/CrawlControls";
import { JobsPanel } from "./components/JobsPanel";
import { LiveActivity } from "./components/LiveActivity";

const PAGE_SIZE = 50;

export default function App() {
  const [portals, setPortals] = useState<PortalMeta[]>([]);
  const [portal, setPortal] = useState("naukrigulf");
  const [locations, setLocations] = useState<LocationMeta[]>([]);
  const [industries, setIndustries] = useState<IndustryMeta[]>([]);
  const [pacing, setPacing] = useState<PacingMeta | null>(null);
  const [selectedLocations, setSelectedLocations] = useState<string[]>(["dubai"]);
  const [industry, setIndustry] = useState("it");
  const [maxPages, setMaxPages] = useState(2);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<CrawlProgress | null>(null);
  const [result, setResult] = useState<CrawlResult | null>(null);
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterLocation, setFilterLocation] = useState("");
  const [filterPortal, setFilterPortal] = useState("all");
  const [inventoryLocations, setInventoryLocations] = useState<LocationMeta[]>([]);
  const [allLocations, setAllLocations] = useState<LocationMeta[]>([]);
  const [eta, setEta] = useState<number | null>(null);
  const [nav, setNav] = useState<"crawl" | "jobs" | "analytics">("crawl");
  const [autoModalOpen, setAutoModalOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [analyticsRefreshKey, setAnalyticsRefreshKey] = useState(0);
  const loadingRef = useRef(false);
  const offsetRef = useRef(0);

  useEffect(() => {
    void api
      .pacing()
      .then(setPacing)
      .catch((err: Error) => setError(err.message));
    void api
      .portals()
      .then(setPortals)
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([api.locations(portal), api.industries(portal)])
      .then(([locs, inds]) => {
        if (cancelled) return;
        setLocations(locs);
        setIndustries(inds);
        const preferredLoc =
          locs.find((l) => l.key === "dubai")?.key ?? locs[0]?.key ?? "";
        setSelectedLocations(preferredLoc ? [preferredLoc] : []);
        const preferredInd =
          inds.find((i) => i.key === "it")?.key ?? inds[0]?.key ?? "";
        setIndustry(preferredInd);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [portal]);

  useEffect(() => {
    if (!portals.length) return;
    let cancelled = false;
    void Promise.all(portals.map((p) => api.locations(p.key)))
      .then((lists) => {
        if (cancelled) return;
        const byKey = new Map<string, LocationMeta>();
        for (const list of lists) {
          for (const loc of list) {
            if (!byKey.has(loc.key)) byKey.set(loc.key, loc);
          }
        }
        setAllLocations([...byKey.values()]);
      })
      .catch(() => {
        /* globe just shows fewer points — non-critical */
      });
    return () => {
      cancelled = true;
    };
  }, [portals]);

  useEffect(() => {
    let cancelled = false;
    setFilterLocation("");

    async function loadInventoryLocations() {
      try {
        if (!filterPortal || filterPortal === "all") {
          const keys =
            portals.length > 0
              ? portals.map((p) => p.key)
              : ["naukrigulf", "gulftalent"];
          const lists = await Promise.all(keys.map((key) => api.locations(key)));
          if (cancelled) return;
          const byKey = new Map<string, LocationMeta>();
          for (const list of lists) {
            for (const loc of list) {
              if (!byKey.has(loc.key)) byKey.set(loc.key, loc);
            }
          }
          setInventoryLocations(
            [...byKey.values()].sort((a, b) => a.label.localeCompare(b.label))
          );
          return;
        }
        const locs = await api.locations(filterPortal);
        if (!cancelled) setInventoryLocations(locs);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }

    void loadInventoryLocations();
    return () => {
      cancelled = true;
    };
  }, [filterPortal, portals]);

  const resetAndLoadJobs = useCallback(async () => {
    loadingRef.current = true;
    setLoadingMore(true);
    offsetRef.current = 0;
    try {
      const data = await api.jobs({
        portal: filterPortal === "all" ? undefined : filterPortal,
        location: filterLocation || undefined,
        limit: PAGE_SIZE,
        offset: 0,
      });
      setJobs(data.items);
      setTotal(data.total);
      setHasMore(data.has_more);
      offsetRef.current = data.items.length;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      loadingRef.current = false;
      setLoadingMore(false);
    }
  }, [filterLocation, filterPortal]);

  const loadMoreJobs = useCallback(async () => {
    if (loadingRef.current || !hasMore) return;
    loadingRef.current = true;
    setLoadingMore(true);
    try {
      const data = await api.jobs({
        portal: filterPortal === "all" ? undefined : filterPortal,
        location: filterLocation || undefined,
        limit: PAGE_SIZE,
        offset: offsetRef.current,
      });
      setJobs((prev) => {
        const seen = new Set(
          prev.map((j) => `${j.source_portal ?? ""}:${j.job_id}`)
        );
        const merged = [...prev];
        for (const item of data.items) {
          const key = `${item.source_portal ?? ""}:${item.job_id}`;
          if (!seen.has(key)) merged.push(item);
        }
        return merged;
      });
      setTotal(data.total);
      setHasMore(data.has_more);
      offsetRef.current += data.items.length;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      loadingRef.current = false;
      setLoadingMore(false);
    }
  }, [filterLocation, filterPortal, hasMore]);

  useEffect(() => {
    void resetAndLoadJobs();
  }, [resetAndLoadJobs]);

  useEffect(() => {
    const tick = () => {
      void api.crawlStatus().then((status) => {
        setRunning(status.running);
        setProgress(status.progress);
        if (status.last_result) setResult(status.last_result);
        if (!status.running && status.last_result) {
          void resetAndLoadJobs();
          setAnalyticsRefreshKey((k) => k + 1);
        }
        if (status.error) setError(status.error);
      });
    };
    tick();
    const id = window.setInterval(tick, running ? 500 : 4000);
    return () => window.clearInterval(id);
  }, [running, resetAndLoadJobs]);

  useEffect(() => {
    if (!running) setCancelling(false);
  }, [running]);

  function toggleLocation(key: string) {
    setSelectedLocations((prev) =>
      prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]
    );
  }

  function selectCountry(country: string) {
    const keys = locations.filter((l) => l.country === country).map((l) => l.key);
    setSelectedLocations((prev) => {
      const allSelected = keys.every((k) => prev.includes(k));
      if (allSelected) return prev.filter((k) => !keys.includes(k));
      return [...new Set([...prev, ...keys])];
    });
  }

  async function launchCrawl(payload: {
    portal: string;
    locations: string[];
    industry: string | null;
    industries?: string[];
    max_pages: number | null;
  }) {
    if (!payload.locations.length) {
      setError("Select at least one location");
      return;
    }
    if (payload.industries && payload.industries.length === 0) {
      setError("Select at least one industry");
      return;
    }
    setError(null);
    setResult(null);
    setRunning(true);
    setNav("crawl");
    try {
      const res = await api.startCrawl(payload);
      setEta(res.estimated_minutes ?? null);
    } catch (err) {
      setRunning(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function startCrawl() {
    await launchCrawl({
      portal,
      locations: selectedLocations,
      industry: industry || null,
      max_pages: maxPages,
    });
  }

  async function startAutoCrawl(payload: {
    portal: string;
    locations: string[];
    industry: string | null;
    industries: string[];
    max_pages: number | null;
  }) {
    setAutoModalOpen(false);
    await launchCrawl(payload);
  }

  async function cancelCrawl() {
    setCancelling(true);
    try {
      await api.cancelCrawl();
    } catch (err) {
      setCancelling(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const portalLabel = portals.find((p) => p.key === portal)?.label ?? portal;

  return (
    <div className="shell">
      <div className="bg-layer" aria-hidden="true" />
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">JS</span>
          <div>
            <strong>Job Scraper</strong>
            <span>Gulf Job Crawler</span>
          </div>
        </div>
        <nav className="nav">
          <button
            type="button"
            className={nav === "crawl" ? "nav-item active" : "nav-item"}
            onClick={() => setNav("crawl")}
          >
            Operations
          </button>
          <button
            type="button"
            className={nav === "jobs" ? "nav-item active" : "nav-item"}
            onClick={() => setNav("jobs")}
          >
            Inventory
          </button>
          <button
            type="button"
            className={nav === "analytics" ? "nav-item active" : "nav-item"}
            onClick={() => setNav("analytics")}
          >
            Analytics
          </button>
        </nav>
        <div className="sidebar-foot">
          <span className="muted">{portalLabel} · polite queue</span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>
              {nav === "crawl"
                ? "Crawl operations"
                : nav === "jobs"
                ? "Job inventory"
                : "Posting analytics"}
            </h1>
            <p className="muted">
              {nav === "analytics"
                ? "Daily, weekly, and monthly trends from stored job postings"
                : `Multi-portal workspace · ${portalLabel} filters · live delays`}
            </p>
          </div>
          <div className="topbar-actions">
            {nav === "crawl" && !running && (
              <button
                type="button"
                className="btn primary glow"
                onClick={() => setAutoModalOpen(true)}
              >
                🌍 Auto Crawl — All Cities
              </button>
            )}
            {nav === "crawl" && running && (
              <button
                type="button"
                className="btn ghost danger"
                disabled={cancelling}
                onClick={() => void cancelCrawl()}
              >
                {cancelling ? "Cancelling…" : "✕ Cancel crawl"}
              </button>
            )}
            <div className={`pulse ${running ? "on" : ""}`}>
              <span className="dot" />
              {running ? "Active job" : "System idle"}
            </div>
          </div>
        </header>

        {error && (
          <div className="banner error" role="alert">
            {error}
            <button type="button" className="btn tiny" onClick={() => setError(null)}>
              Dismiss
            </button>
          </div>
        )}

        {nav === "crawl" ? (
          <div className="stack">
            <LiveActivity
              running={running}
              progress={progress}
              result={result}
              allLocations={allLocations}
            />
            <CrawlControls
              portals={portals}
              portal={portal}
              locations={locations}
              industries={industries}
              pacing={pacing}
              selectedLocations={selectedLocations}
              industry={industry}
              maxPages={maxPages}
              running={running}
              estimatedMinutes={eta}
              onPortal={setPortal}
              onToggleLocation={toggleLocation}
              onSelectCountry={selectCountry}
              onIndustry={setIndustry}
              onMaxPages={setMaxPages}
              onStart={() => void startCrawl()}
            />
          </div>
        ) : nav === "jobs" ? (
          <JobsPanel
            jobs={jobs}
            total={total}
            loaded={jobs.length}
            hasMore={hasMore}
            loadingMore={loadingMore}
            clearing={clearing}
            portals={portals}
            filterPortal={filterPortal}
            locations={inventoryLocations}
            filterLocation={filterLocation}
            onFilterPortal={setFilterPortal}
            onFilterLocation={setFilterLocation}
            onLoadMore={() => void loadMoreJobs()}
            onExport={() => {
              window.open(
                api.exportExcelUrl({
                  portal: filterPortal === "all" ? undefined : filterPortal,
                  location: filterLocation || undefined,
                }),
                "_blank"
              );
            }}
            onClear={() => {
              const scope =
                filterPortal === "all"
                  ? "all portals"
                  : portals.find((p) => p.key === filterPortal)?.label ??
                    filterPortal;
              if (
                !window.confirm(
                  `Delete all stored jobs for ${scope}? This cannot be undone.`
                )
              ) {
                return;
              }
              setClearing(true);
              void api
                .clearJobs({
                  portal: filterPortal === "all" ? undefined : filterPortal,
                })
                .then(() => resetAndLoadJobs())
                .catch((err: unknown) =>
                  setError(err instanceof Error ? err.message : String(err))
                )
                .finally(() => setClearing(false));
            }}
          />
        ) : (
          <AnalyticsPanel
            portals={portals}
            locations={inventoryLocations}
            refreshKey={analyticsRefreshKey}
          />
        )}
      </main>

      <AutoCrawlModal
        open={autoModalOpen}
        portals={portals}
        portal={portal}
        locations={locations}
        industries={industries}
        industry={industry}
        running={running}
        onPortal={setPortal}
        onIndustry={setIndustry}
        onClose={() => setAutoModalOpen(false)}
        onStart={(payload) => void startAutoCrawl(payload)}
      />
    </div>
  );
}
