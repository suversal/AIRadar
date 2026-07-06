export type RadarSource = {
  name: string;
  url: string;
  tier: string;
};

export type LatestEvent = {
  event_id: string;
  title: string;
  category?: string;
  category_label?: string;
  tags?: string[];
  final_score?: number;
  source_count?: number;
  main_source?: RadarSource;
  one_line_summary?: string;
  summary?: string;
  reason?: string;
  action?: string;
  published_at?: string;
};

export type LatestReport = {
  updated_at: string | null;
  items: LatestEvent[];
};

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export function getApiBaseUrl() {
  return process.env.AI_RADAR_API_BASE_URL ?? DEFAULT_API_BASE_URL;
}

export async function getLatestReport(): Promise<LatestReport> {
  const response = await fetch(`${getApiBaseUrl()}/api/public/latest`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Failed to load latest report: ${response.status}`);
  }
  return response.json();
}
