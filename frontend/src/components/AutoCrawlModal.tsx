import { useEffect, useMemo, useState } from "react";
import type { IndustryMeta, LocationMeta, PortalMeta } from "../api";
import { api } from "../api";

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
    portals: string[];
    locations: string[];
    industry: string | null;
    industries: string[];
    all_industries: boolean;
    max_pages: number | null;
  }) => void;
};

export function AutoCrawlModal({
  open,
  portals,
  portal,
  locations: _singleLocations,
  industries: _singleIndustries,
  industry,
  running,
  onPortal,
  onIndustry,
  onClose,
  onStart,
}: Props) {
  const [selectedPortals, setSelectedPortals] = useState<string[]>([]);
  const [selectedCities, setSelectedCities] = useState<string[]>([]);
  const [selectedIndustries, setSelectedIndustries] = useState<string[]>([]);
  const [allIndustries, setAllIndustries] = useState(true);
  const [unionLocations, setUnionLocations] = useState<LocationMeta[]>([]);
  const [unionIndustries, setUnionIndustries] = useState<IndustryMeta[]>([]);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [uncapped, setUncapped] = useState(true);
  const [maxPages, setMaxPages] = useState(10);

  useEffect(() => {
    if (!open) return;
    const keys = portals.map((p) => p.key);
    setSelectedPortals(keys.length ? keys : portal ? [portal] : []);
    setAllIndustries(true);
    setUncapped(true);
  }, [open, portals, portal]);

  useEffect(() => {
    if (!open || selectedPortals.length === 0) return;
    let cancelled = false;
    setLoadingMeta(true);
    void Promise.all(
      selectedPortals.map(async (key) => {
        const [locs, inds] = await Promise.all([
          api.locations(key),
          api.industries(key),
        ]);
        return { key, locs, inds };
      })
    )
      .then((packs) => {
        if (cancelled) return;
        const locMap = new Map<string, LocationMeta>();
        const indMap = new Map<string, IndustryMeta>();
        for (const pack of packs) {
          for (const loc of pack.locs) {
            if (!locMap.has(loc.key)) locMap.set(loc.key, loc);
          }
          for (const ind of pack.inds) {
            if (!indMap.has(ind.key)) indMap.set(ind.key, ind);
          }
        }
        const locs = [...locMap.values()];
        const inds = [...indMap.values()];
        setUnionLocations(locs);
        setUnionIndustries(inds);
        setSelectedCities(locs.map((l) => l.key));
        setSelectedIndustries(inds.map((i) => i.key));
        if (inds[0]) onIndustry(inds[0].key);
      })
      .catch(() => {
        /* keep prior lists */
      })
      .finally(() => {
        if (!cancelled) setLoadingMeta(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, selectedPortals, onIndustry]);

  const locations = unionLocations;
  const industries = unionIndustries;

  const grouped = useMemo(() => {
    const map = new Map<string, LocationMeta[]>();
    for (const loc of locations) {
      const list = map.get(loc.country) ?? [];
      list.push(loc);
      map.set(loc.country, list);
    }
    return map;
  }, [locations]);

  if (!open) return null;

  function togglePortal(key: string) {
    setSelectedPortals((prev) => {
      const next = prev.includes(key)
        ? prev.filter((k) => k !== key)
        : [...prev, key];
      if (next.length === 1) onPortal(next[0]);
      return next;
    });
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
    setAllIndustries(false);
    setSelectedIndustries((prev) => {
      const next = prev.includes(key)
        ? prev.filter((k) => k !== key)
        : [...prev, key];
      if (next.length === 1) onIndustry(next[0]);
      return next;
    });
  }

  const allPortals =
    portals.length > 0 && selectedPortals.length === portals.length;
  const allCities =
    locations.length > 0 && selectedCities.length === locations.length;
  const allIndustriesSelected =
    industries.length > 0 && selectedIndustries.length === industries.length;

  const canStart =
    !running &&
    !loadingMeta &&
    selectedPortals.length > 0 &&
    selectedCities.length > 0 &&
    (allIndustries || selectedIndustries.length > 0);

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal-card modal-card-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>Auto Crawl — distributed sweep</h2>
            <p>
              Portals are interleaved (Naukri → GulfTalent → Bayt → …) so no
              single site gets the full load. Each step is one city + one
              industry on one portal.
            </p>
          </div>
          <button type="button" className="btn ghost icon" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="modal-body">
          <div className="field">
            <div className="field-label-row">
              <span className="field-label">
                Portals ({selectedPortals.length}/{portals.length})
              </span>
              <button
                type="button"
                className="linkish"
                onClick={() => {
                  if (allPortals) setSelectedPortals([]);
                  else {
                    const keys = portals.map((p) => p.key);
                    setSelectedPortals(keys);
                    if (keys[0]) onPortal(keys[0]);
                  }
                }}
              >
                {allPortals ? "Clear all" : "Select all portals"}
              </button>
            </div>
            <div className="check-grid">
              {portals.map((p) => {
                const on = selectedPortals.includes(p.key);
                return (
                  <label key={p.key} className={on ? "check on" : "check"}>
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={running}
                      onChange={() => togglePortal(p.key)}
                    />
                    {p.label}
                  </label>
                );
              })}
            </div>
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
              <span className="field-label">Industries</span>
              <button
                type="button"
                className="linkish"
                onClick={() => {
                  if (allIndustries || allIndustriesSelected) {
                    setAllIndustries(false);
                    setSelectedIndustries([]);
                  } else {
                    setAllIndustries(true);
                    setSelectedIndustries(industries.map((i) => i.key));
                  }
                }}
              >
                {allIndustries || allIndustriesSelected
                  ? "Clear all"
                  : "Select all filters"}
              </button>
            </div>
            <label className="switch" style={{ marginBottom: "0.6rem" }}>
              <input
                type="checkbox"
                checked={allIndustries}
                onChange={(e) => {
                  setAllIndustries(e.target.checked);
                  if (e.target.checked) {
                    setSelectedIndustries(industries.map((i) => i.key));
                  }
                }}
              />
              <span className="switch-track">
                <span className="switch-thumb" />
              </span>
              <span>
                All industries per portal (recommended for full sweep)
              </span>
            </label>
            {!allIndustries && (
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
            )}
            {allIndustries && (
              <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                Each portal crawls every industry filter it exposes
                {loadingMeta ? " · loading…" : ""}.
              </p>
            )}
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
            disabled={!canStart}
            onClick={() =>
              onStart({
                portal: selectedPortals[0] ?? portal,
                portals: selectedPortals,
                locations: selectedCities,
                industry: selectedIndustries[0] ?? industry ?? null,
                industries: allIndustries ? [] : selectedIndustries,
                all_industries: allIndustries,
                max_pages: uncapped ? null : maxPages,
              })
            }
          >
            {running
              ? "Crawl in progress…"
              : `Start · ${selectedPortals.length} ${
                  selectedPortals.length === 1 ? "portal" : "portals"
                } · ${selectedCities.length} ${
                  selectedCities.length === 1 ? "city" : "cities"
                } · ${
                  allIndustries
                    ? "all industries"
                    : `${selectedIndustries.length} industries`
                }`}
          </button>
        </div>
      </div>
    </div>
  );
}
