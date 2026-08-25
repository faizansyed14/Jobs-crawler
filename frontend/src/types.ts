export type JobItem = {
  job_id: string;
  title: string;
  company_name: string;
  url: string;
  salary?: string | null;
  posted_at: string;
  search_location?: string | null;
  industry?: string | null;
  source_portal?: string | null;
};