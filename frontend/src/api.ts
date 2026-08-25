const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

const DEFAULT_PACING = {
  min_delay_seconds: 4,
  max_delay_seconds: 30,
  location_gap_seconds: 5,
  max_pages_per_run: 20,
  note: "Sequential polite delays reduce CAPTCHA / rate-limit risk.",
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export type PortalMeta = {
  key: string;
  label: string;
};

export type LocationMeta = {
  key: string;
  label: string;
  country: string;
  api_value: string;
  lat: number;
  lng: number;
};

export type IndustryMeta = {
  key: string;
  label: string;
  cluster_ind: string;
};

export type JobItem = {
  job_id: string;
  title: string;
  company_name: string;
  location?: string | null;
  url: string;
  salary?: string | null;
  posted_at: string;
  search_location?: string | null;
  industry?: string | null;
  source_portal?: string | null;
};

export type CrawlResult = {
  portal: string;
  locations: string[];
  industry?: string | null;
  jobs_found: number;
  jobs_new: number;
  pages_crawled: number;
  stop_reason: string;
  extraction_method: string;
  success: boolean;
  error?: string | null;
};

export type CrawlEvent = {
  at: string;
  phase: string;
  message: string;
};

export type CrawlProgress = {
  phase: string;
  message: string;
  why?: string | null;
  location: string | null;
  location_index: number;
  locations_total: number;
  locations?: string[];
  industry?: string | null;
  page: number;
  max_pages: number | null;
  pages_crawled: number;
  jobs_found: number;
  jobs_new: number;
  delay_seconds: number | null;
  delay_remaining?: number | null;
  delay_reason?: string | null;
  updated_at: string;
  events?: CrawlEvent[];
};

export type CrawlStatus = {
  running: boolean;
  progress: CrawlProgress | null;
  last_result: CrawlResult | null;
  error: string | null;
};

export type PacingMeta = {
  min_delay_seconds: number;
  max_delay_seconds: number;
  location_gap_seconds: number;
  max_pages_per_run: number;
  note: string;
};

export type JobsPage = {
  total: number;
  items: JobItem[];
  limit: number;
  offset: number;
  has_more: boolean;
};

export type AnalyticsTimelinePoint = {
  period: string;
  count: number;
};

export type JobAnalytics = {
  granularity: "day" | "week" | "month";
  lookback: number;
  since: string;
  until: string;
  total_in_range: number;
  total_all_time: number;
  average_per_period: number;
  peak_period_count: number;
  timeline: AnalyticsTimelinePoint[];
  city_totals: { city: string; count: number }[];
  by_city: {
    city: string;
    total: number;
    timeline: AnalyticsTimelinePoint[];
  }[];
  by_portal: { portal: string; count: number }[];
};

export const api = {
  portals: () => request<PortalMeta[]>("/meta/portals"),
  locations: (portal = "naukrigulf") =>
    request<LocationMeta[]>(`/meta/locations?portal=${encodeURIComponent(portal)}`),
  industries: (portal = "naukrigulf") =>
    request<IndustryMeta[]>(`/meta/industries?portal=${encodeURIComponent(portal)}`),
  pacing: async (): Promise<PacingMeta> => {
    try {
      return await request<PacingMeta>("/meta/pacing");
    } catch {
      return DEFAULT_PACING;
    }
  },
  crawlStatus: () => request<CrawlStatus>("/crawl/status"),
  startCrawl: (body: {
    portal: string;
    locations: string[];
    industry: string | null;
    industries?: string[];
    max_pages?: number | null;
  }) =>
    request<{
      accepted: boolean;
      mode?: "auto" | "fixed";
      estimated_minutes?: number | null;
      max_pages?: number | null;
      note?: string;
      industries?: string[];
    }>("/crawl", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  jobs: (params: {
    portal?: string;
    location?: string;
    industry?: string;
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params.portal) q.set("portal", params.portal);
    if (params.location) q.set("location", params.location);
    if (params.industry) q.set("industry", params.industry);
    q.set("limit", String(params.limit ?? 50));
    q.set("offset", String(params.offset ?? 0));
    return request<JobsPage>(`/jobs?${q}`);
  },
  exportExcelUrl: (params: {
    portal?: string;
    location?: string;
    industry?: string;
  }) => {
    const q = new URLSearchParams();
    if (params.portal) q.set("portal", params.portal);
    if (params.location) q.set("location", params.location);
    if (params.industry) q.set("industry", params.industry);
    q.set("limit", "5000");
    return `${API_BASE}/jobs/export?${q}`;
  },
  cancelCrawl: () =>
    request<{ accepted: boolean; message: string }>("/crawl/cancel", {
      method: "POST",
    }),
  analytics: (params: {
    granularity?: "day" | "week" | "month";
    portal?: string;
    location?: string;
    industry?: string;
    lookback?: number;
  }) => {
    const q = new URLSearchParams();
    if (params.granularity) q.set("granularity", params.granularity);
    if (params.portal) q.set("portal", params.portal);
    if (params.location) q.set("location", params.location);
    if (params.industry) q.set("industry", params.industry);
    if (params.lookback != null) q.set("lookback", String(params.lookback));
    return request<JobAnalytics>(`/analytics/jobs?${q}`);
  },
  clearJobs: (params?: { portal?: string }) => {
    const q = new URLSearchParams();
    if (params?.portal) q.set("portal", params.portal);
    const suffix = q.toString() ? `?${q}` : "";
    return request<{ deleted: number; portal: string }>(`/jobs${suffix}`, {
      method: "DELETE",
    });
  },
};
