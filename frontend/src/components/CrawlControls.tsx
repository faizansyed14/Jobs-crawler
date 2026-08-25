import type { IndustryMeta, LocationMeta, PacingMeta, PortalMeta } from "../api";

type Props = {
  portals: PortalMeta[];
  portal: string;
  locations: LocationMeta[];
  industries: IndustryMeta[];
  pacing: PacingMeta | null;
  selectedLocations: string[];
  industry: string;
  maxPages: number;
  running: boolean;
  estimatedMinutes: number | null;
  onPortal: (value: string) => void;
  onToggleLocation: (key: string) => void;
  onSelectCountry: (country: string) => void;
  onIndustry: (value: string) => void;
  onMaxPages: (value: number) => void;
  onStart: () => void;
};

export function CrawlControls({
  portals,
  portal,
  locations,
  industries,
  pacing,
  selectedLocations,
  industry,
  maxPages,
  running,
  estimatedMinutes,
  onPortal,
  onToggleLocation,
  onSelectCountry,
  onIndustry,
  onMaxPages,
  onStart,
}: Props) {
  const grouped = new Map<string, LocationMeta[]>();
  for (const loc of locations) {
    const list = grouped.get(loc.country) ?? [];
    list.push(loc);
    grouped.set(loc.country, list);
  }

  const eta =
    estimatedMinutes ??
    (pacing
      ? Math.round(
          ((maxPages *
            Math.max(selectedLocations.length, 1) *
            (pacing.min_delay_seconds + 2)) /
            60) *
            10
        ) / 10
      : null);

  const portalLabel =
    portals.find((p) => p.key === portal)?.label ?? portal;

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h2>Crawl job</h2>
          <p>
            Pick a portal — filters and locations switch to match {portalLabel}.
          </p>
        </div>
      </div>

      <div className="form-grid">
        <label className="field">
          <span>Portal</span>
          <select
            value={portal}
            onChange={(e) => onPortal(e.target.value)}
            disabled={running}
          >
            {portals.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Industry</span>
          <select value={industry} onChange={(e) => onIndustry(e.target.value)}>
            {industries.map((ind) => (
              <option key={ind.key} value={ind.key}>
                {ind.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Max pages</span>
          <input
            type="number"
            min={1}
            max={100}
            value={maxPages}
            onChange={(e) => onMaxPages(Number(e.target.value) || 1)}
          />
        </label>
      </div>

      <div className="field">
        <span className="field-label">Locations ({portalLabel})</span>
        <div className="country-list">
          {[...grouped.entries()].map(([country, locs]) => (
            <div key={country} className="country-group">
              <button
                type="button"
                className="linkish"
                onClick={() => onSelectCountry(country)}
              >
                {country}
              </button>
              <div className="check-grid">
                {locs.map((loc) => {
                  const on = selectedLocations.includes(loc.key);
                  return (
                    <label key={loc.key} className={on ? "check on" : "check"}>
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => onToggleLocation(loc.key)}
                      />
                      {loc.label}
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      {pacing && (
        <p className="hint">
          Pace: ~{pacing.min_delay_seconds}–{pacing.max_delay_seconds}s between
          pages · {pacing.location_gap_seconds}s between cities
          {eta != null && <> · Est. ~{eta} min for this run</>}
        </p>
      )}

      <div className="actions">
        <button
          type="button"
          className="btn primary"
          disabled={running || !selectedLocations.length}
          onClick={onStart}
        >
          {running ? "Crawl in progress…" : `Start ${portalLabel} crawl`}
        </button>
      </div>
    </section>
  );
}
