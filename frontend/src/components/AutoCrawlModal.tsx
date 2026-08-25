import { useEffect, useState } from "react";
import type { IndustryMeta, LocationMeta, PortalMeta } from "../api";

type Props = {
  open: boolean;
  portals: PortalMeta[];
  portal: string;
  locations: LocationMeta[];
  industries: IndustryMeta[];
  industry: string;
  running: boolean;
  onPortal: (value: string) => void;
  onIndustry: (value: string) => void;
  onClose: () => void;
  onStart: (payload: {
    portal: string;
    locations: string[];
    industry: string | null;
    industries: string[];
    max_pages: number | null;
  }) => void;
};

export function AutoCrawlModal({
  open,
  portals,
  portal,
  locations,
  industries,
  industry,
  running,
  onPortal,
  onIndustry,
  onClose,
  onStart,
}: Props) {
  const [selectedCities, setSelectedCities] = useState<string[]>([]);
  const [selectedIndustries, setSelectedIndustries] = useState<string[]>([]);
  const [uncapped, setUncapped] = useState(true);
  const [maxPages, setMaxPages] = useState(10);

  useEffect(() => {
    if (!open) return;
    setSelectedCities(locations.map((l) => l.key));
    // Default: keep current single-industry selection; user can Select all.
    const fallback = industry || industries[0]?.key || "it";
    setSelectedIndustries(
      industries.some((i) => i.key === fallback)
        ? [fallback]
        : industries.slice(0, 1).map((i) => i.key)
    );
  }, [open, locations, industries, industry]);

  if (!open) return null;

  const grouped = new Map<string, LocationMeta[]>();
  for (const loc of locations) {
    const list = grouped.get(loc.country) ?? [];
    list.push(loc);
    grouped.set(loc.country, list);
  }

  function toggleCity(key: string) {
    setSelectedCities((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  }

  function toggleCountry(country: string) {
    const keys = (grouped.get(country) ?? []).map((l) => l.key);
    setSelectedCities((prev) => {
      const allOn = keys.every((k) => prev.includes(k));
      if (allOn) return prev.filter((k) => !keys.includes(k));
      return [...new Set([...prev, ...keys])];
    });
  }

  function toggleIndustry(key: string) {
    setSelectedIndustries((prev) => {
      const next = prev.includes(key)
        ? prev.filter((k) => k !== key)
        : [...prev, key];
      if (next.length === 1) onIndustry(next[0]);
      return next;
    });
  }

  const allCities =
    locations.length > 0 && selectedCities.length === locations.length;
  const allIndustries =
    industries.length > 0 && selectedIndustries.length === industries.length;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal-card modal-card-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>Auto Crawl — cities + industries</h2>
            <p>
              Pick every city and every industry filter this portal exposes.
              Runs one-by-one until each city/industry naturally runs dry.
            </p>
          </div>
          <button type="button" className="btn ghost icon" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="modal-body">
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
          </div>

          <div className="uncapped-row">
            <label className="switch">
              <input
                type="checkbox"
                checked={uncapped}
                onChange={(e) => setUncapped(e.target.checked)}
              />
              <span className="switch-track">
                <span className="switch-thumb" />
              </span>
              <span>Uncapped — stop automatically (2 empty pages in a row)</span>
            </label>
            {!uncapped && (
              <label className="field inline">
                <span>Max pages / city</span>
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={maxPages}
                  onChange={(e) => setMaxPages(Number(e.target.value) || 1)}
                />
              </label>
            )}
          </div>

          <div className="field">
            <div className="field-label-row">
              <span className="field-label">
                Industries ({selectedIndustries.length}/{industries.length})
              </span>
              <button
                type="button"
                className="linkish"
                onClick={() => {
                  if (allIndustries) {
                    setSelectedIndustries([]);
                  } else {
                    const keys = industries.map((i) => i.key);
                    setSelectedIndustries(keys);
                    if (keys[0]) onIndustry(keys[0]);
                  }
                }}
              >
                {allIndustries ? "Clear all" : "Select all filters"}
              </button>
            </div>
            <div className="check-grid industry-check-grid scrollable-checks">
              {industries.map((ind) => {
                const on = selectedIndustries.includes(ind.key);
                return (
                  <label key={ind.key} className={on ? "check on" : "check"}>
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => toggleIndustry(ind.key)}
                    />
                    {ind.label}
                  </label>
                );
              })}
            </div>
          </div>

          <div className="field">
            <div className="field-label-row">
              <span className="field-label">
                Cities ({selectedCities.length}/{locations.length})
              </span>
              <button
                type="button"
                className="linkish"
                onClick={() =>
                  setSelectedCities(allCities ? [] : locations.map((l) => l.key))
                }
              >
                {allCities ? "Clear all" : "Select all"}
              </button>
            </div>
            <div className="country-list scrollable">
              {[...grouped.entries()].map(([country, locs]) => (
                <div key={country} className="country-group">
                  <button
                    type="button"
                    className="linkish"
                    onClick={() => toggleCountry(country)}
                  >
                    {country}
                  </button>
                  <div className="check-grid">
                    {locs.map((loc) => {
                      const on = selectedCities.includes(loc.key);
                      return (
                        <label key={loc.key} className={on ? "check on" : "check"}>
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() => toggleCity(loc.key)}
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
        </div>

        <div className="modal-foot">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={
              running || selectedCities.length === 0 || selectedIndustries.length === 0
            }
            onClick={() =>
              onStart({
                portal,
                locations: selectedCities,
                industry: selectedIndustries[0] ?? null,
                industries: selectedIndustries,
                max_pages: uncapped ? null : maxPages,
              })
            }
          >
            {running
              ? "Crawl in progress…"
              : `Start · ${selectedCities.length} ${
                  selectedCities.length === 1 ? "city" : "cities"
                } · ${selectedIndustries.length} ${
                  selectedIndustries.length === 1 ? "industry" : "industries"
                }`}
          </button>
        </div>
      </div>
    </div>
  );
}
