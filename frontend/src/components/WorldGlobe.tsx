import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import Globe, { type GlobeMethods } from "react-globe.gl";
import type { LocationMeta } from "../api";

type CityStatus = "pending" | "active" | "done";

type CityPoint = {
  key: string;
  label: string;
  lat: number;
  lng: number;
  status: CityStatus;
};

type Props = {
  locations: LocationMeta[];
  activeKey: string | null;
  visitedKeys: string[];
  running: boolean;
};

const STATUS_COLOR: Record<CityStatus, string> = {
  pending: "rgba(148, 163, 184, 0.55)",
  active: "#38f2c8",
  done: "#4c8bf5",
};

const EARTH_TEXTURE = "https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg";
const BUMP_TEXTURE = "https://unpkg.com/three-globe/example/img/earth-topology.png";

function useElementWidth(): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(320);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width;
      if (w) setWidth(Math.round(w));
    });
    observer.observe(node);
    setWidth(Math.round(node.getBoundingClientRect().width));
    return () => observer.disconnect();
  }, []);

  return [ref, width];
}

export function WorldGlobe({ locations, activeKey, visitedKeys, running }: Props) {
  const [containerRef, width] = useElementWidth();
  const globeRef = useRef<GlobeMethods | undefined>(undefined);
  const [ready, setReady] = useState(false);
  const visited = useMemo(() => new Set(visitedKeys), [visitedKeys]);

  const points: CityPoint[] = useMemo(
    () =>
      locations
        .filter((loc) => loc.lat && loc.lng)
        .map((loc) => {
          let status: CityStatus = "pending";
          if (loc.key === activeKey) status = "active";
          else if (visited.has(loc.key)) status = "done";
          return {
            key: loc.key,
            label: loc.label,
            lat: loc.lat,
            lng: loc.lng,
            status,
          };
        }),
    [locations, activeKey, visited]
  );

  const activePoint = points.find((p) => p.status === "active") ?? null;

  // Crawling: lock camera on active city. Finished/idle: zoom out + spin again.
  useEffect(() => {
    const controls = globeRef.current?.controls();
    if (!controls) return;
    controls.autoRotate = !running;
    controls.autoRotateSpeed = running ? 0 : 1.1;
  }, [ready, running]);

  useEffect(() => {
    if (!ready || !globeRef.current) return;

    if (running && activePoint) {
      globeRef.current.pointOfView(
        { lat: activePoint.lat, lng: activePoint.lng, altitude: 0.9 },
        1200
      );
      return;
    }

    if (points.length === 0) return;

    if (points.length === 1) {
      const [only] = points;
      globeRef.current.pointOfView(
        { lat: only.lat, lng: only.lng, altitude: 1.4 },
        1200
      );
      return;
    }

    // Multiple cities, none active right now (queued / all done) — zoom out
    // to frame the whole selected set instead of sitting on one city.
    const avgLat = points.reduce((sum, p) => sum + p.lat, 0) / points.length;
    const avgLng = points.reduce((sum, p) => sum + p.lng, 0) / points.length;
    const spread = Math.max(
      ...points.map((p) => Math.hypot(p.lat - avgLat, p.lng - avgLng)),
      4
    );
    const altitude = Math.min(2.6, Math.max(1.6, spread / 12));
    globeRef.current.pointOfView({ lat: avgLat, lng: avgLng, altitude }, 1200);
  }, [ready, activePoint?.key, points.length, running]);

  const ringsData = activePoint ? [activePoint] : [];

  return (
    <div className="globe-panel" ref={containerRef}>
      <Globe
        ref={globeRef}
        width={width}
        height={340}
        backgroundColor="rgba(0,0,0,0)"
        globeImageUrl={EARTH_TEXTURE}
        bumpImageUrl={BUMP_TEXTURE}
        showAtmosphere
        atmosphereColor="#7dd3c8"
        atmosphereAltitude={0.16}
        onGlobeReady={() => setReady(true)}
        pointsData={points}
        pointLat="lat"
        pointLng="lng"
        pointColor={(d) => STATUS_COLOR[(d as CityPoint).status]}
        pointAltitude={(d) => ((d as CityPoint).status === "active" ? 0.04 : 0.01)}
        pointRadius={(d) => ((d as CityPoint).status === "active" ? 0.55 : 0.32)}
        pointLabel={(d) => {
          const point = d as CityPoint;
          const statusLabel =
            point.status === "active"
              ? "Crawling now"
              : point.status === "done"
              ? "Done"
              : "Queued";
          return `<div class="globe-tooltip"><strong>${point.label}</strong><br/>${statusLabel}</div>`;
        }}
        labelsData={points}
        labelLat="lat"
        labelLng="lng"
        labelText="label"
        labelSize={(d) => ((d as CityPoint).status === "active" ? 1.35 : 1.05)}
        labelColor={(d) =>
          (d as CityPoint).status === "pending"
            ? "rgba(255, 255, 255, 0.75)"
            : "#ffffff"
        }
        labelAltitude={(d) => ((d as CityPoint).status === "active" ? 0.045 : 0.012)}
        labelDotRadius={0}
        labelIncludeDot={false}
        labelResolution={3}
        ringsData={ringsData}
        ringLat="lat"
        ringLng="lng"
        ringColor={() => (t: number) => `rgba(56, 242, 200, ${1 - t})`}
        ringMaxRadius={5}
        ringPropagationSpeed={2.4}
        ringRepeatPeriod={900}
      />
      <div className="globe-legend">
        <span>
          <i className="dot pending" /> Queued
        </span>
        <span>
          <i className="dot active" /> Crawling
        </span>
        <span>
          <i className="dot done" /> Done
        </span>
      </div>
    </div>
  );
}
