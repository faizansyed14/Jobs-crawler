import { useEffect, useMemo, useRef, useState } from "react";
import type { CrawlProgress, CrawlResult, LocationMeta } from "../api";
import { WorldGlobe } from "./WorldGlobe";

type Props = {
  running: boolean;
  progress: CrawlProgress | null;
  result: CrawlResult | null;
  allLocations: LocationMeta[];
};

function pct(progress: CrawlProgress | null): number {
  if (!progress?.max_pages || !progress.locations_total) return 0;
  const total = progress.max_pages * progress.locations_total;
  const current =
    Math.max(0, progress.location_index - 1) * progress.max_pages +
    Math.max(0, progress.page);
  return Math.min(100, Math.round((current / total) * 100));
}

function useCountUp(value: number, durationMs = 550): number {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const from = fromRef.current;
    const to = value;
    if (from === to) return;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(Math.round(from + (to - from) * eased));
      if (t < 1) {
        rafRef.current = requestAnimationFrame(step);
      } else {
        fromRef.current = to;
      }
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return display;
}

const PHASE_LABEL: Record<string, string> = {
  queued: "Queued",
  warming_up: "Warming up",
  waiting: "Polite delay",
  location: "Location",
  fetching: "Fetching API",
  parsing: "Parsing",
  retry: "Retry / backoff",
  done: "Done",
  error: "Error",
  idle: "Idle",
};

export function LiveActivity({ running, progress, result, allLocations }: Props) {
  const percent = running ? pct(progress) : result ? 100 : 0;
  const waiting = progress?.phase === "waiting" || progress?.phase === "retry";
  const remaining = progress?.delay_remaining;

  const jobsFound = useCountUp(progress?.jobs_found ?? result?.jobs_found ?? 0);
  const jobsNew = useCountUp(progress?.jobs_new ?? result?.jobs_new ?? 0);

  const byKey = useMemo(
    () => new Map(allLocations.map((l) => [l.key, l])),
    [allLocations]
  );
  const runKeys = progress?.locations ?? [];
  const globeLocations = useMemo(
    () =>
      runKeys
        .map((k) => byKey.get(k))
        .filter((l): l is LocationMeta => Boolean(l)),
    [runKeys, byKey]
  );
  const visitedKeys = useMemo(() => {
    if (!running) return runKeys;
    const idx = progress?.location_index ?? 0;
    return runKeys.slice(0, Math.max(0, idx - 1));
  }, [runKeys, progress?.location_index, running]);

  const maxPagesLabel = progress?.max_pages == null ? "∞" : String(progress.max_pages);

  return (
    <section className="card live-card" aria-live="polite">
      <div className="card-head">
        <div>
          <h2>Live crawl feed</h2>
          <p>Everything happening behind the scenes — delays are intentional.</p>
        </div>
        <span className={`status-pill ${running ? "live" : "idle"}`}>
          {running ? "Running" : "Idle"}
        </span>
      </div>

      <WorldGlobe
        locations={globeLocations}
        activeKey={running ? (progress?.location ?? null) : null}
        visitedKeys={visitedKeys}
        running={running}
      />

      {waiting && remaining != null && remaining > 0 && (
        <div className="delay-banner">
          <div className="delay-countdown mono">{Math.ceil(remaining)}s</div>
          <div>
            <strong>{progress?.delay_reason || "Polite delay"}</strong>
            <p>
              Pausing on purpose so we do not burst their servers — lowers CAPTCHA /
              block risk. This is normal.
            </p>
          </div>
        </div>
      )}

      <div
        className="progress-track"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>

      <div className="metric-grid">
        <div className="metric">
          <span className="metric-label">Page</span>
          <span className="metric-value mono">
            {progress?.page ?? 0}
            <span className="metric-suffix">/ {maxPagesLabel}</span>
          </span>
        </div>
        <div className="metric">
          <span className="metric-label">Location</span>
          <span className="metric-value">
            {progress?.location ?? "—"}
            <span className="metric-suffix">
              {progress
                ? `${progress.location_index}/${progress.locations_total}`
                : ""}
            </span>
          </span>
        </div>
        <div className="metric">
          <span className="metric-label">Jobs found</span>
          <span className="metric-value mono count-up">{jobsFound}</span>
        </div>
        <div className="metric">
          <span className="metric-label">New inserts</span>
          <span className="metric-value mono count-up">{jobsNew}</span>
        </div>
      </div>

      <div className="now-block">
        <span className="phase">
          {PHASE_LABEL[progress?.phase ?? (result ? "done" : "idle")] ??
            progress?.phase}
        </span>
        <div>
          <p className="now-msg">
            {progress?.message ??
              (result
                ? `Finished · ${result.pages_crawled} pages · ${result.stop_reason}`
                : "No active crawl — start one to watch the queue.")}
          </p>
          {progress?.why && <p className="now-why">{progress.why}</p>}
        </div>
      </div>
    </section>
  );
}
