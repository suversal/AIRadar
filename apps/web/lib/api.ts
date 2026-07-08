export type RadarSource = {
  name: string;
  url: string;
  tier: string;
};

export type OriginalImage = {
  url: string;
  alt?: string;
  caption?: string;
};

export type OriginalBlock =
  | {
      type: "paragraph";
      text: string;
    }
  | {
      type: "image";
      url: string;
      alt?: string;
      caption?: string;
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
  source_language?: string;
  one_line_summary?: string;
  summary?: string;
  reason?: string;
  action?: string;
  published_at?: string;
  original_url?: string;
  original_content?: string;
  original_markdown?: string;
  original_paragraphs?: string[];
  original_images?: OriginalImage[];
  original_blocks?: OriginalBlock[];
  translated_content?: string;
  translated_paragraphs?: string[];
  translated_blocks?: OriginalBlock[];
};

export type LatestReport = {
  report_date?: string | null;
  updated_at: string | null;
  article_count?: number;
  items: LatestEvent[];
  error?: string | null;
};

export type DailyReport = {
  report_date: string;
  title: string;
  summary: string;
  updated_at?: string | null;
  generated_at?: string | null;
  latest_published_at?: string | null;
  sections: Record<string, LatestEvent[]>;
  items: LatestEvent[];
  article_count: number;
};

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export function getApiBaseUrl() {
  return process.env.AI_RADAR_API_BASE_URL ?? DEFAULT_API_BASE_URL;
}

function emptyLatestReport(error: string): LatestReport {
  return {
    report_date: null,
    updated_at: null,
    article_count: 0,
    items: [],
    error,
  };
}

function latestLoadErrorMessage(error: unknown) {
  const detail = error instanceof Error ? error.message : "unknown error";
  return `API 服务暂时不可用，请确认后端 ${getApiBaseUrl()} 已启动。${detail}`;
}

export async function getLatestReport(): Promise<LatestReport> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/public/latest`, {
      cache: "no-store",
    });
    if (!response.ok) {
      return emptyLatestReport(`API 服务暂时不可用：latest 接口返回 ${response.status}。`);
    }
    const payload = (await response.json()) as LatestReport;
    return { ...payload, error: null };
  } catch (error) {
    return emptyLatestReport(latestLoadErrorMessage(error));
  }
}

export async function getDailyReport(reportDate: string): Promise<DailyReport> {
  const response = await fetch(
    `${getApiBaseUrl()}/api/public/daily/${encodeURIComponent(reportDate)}`,
    {
      cache: "no-store",
    },
  );
  if (!response.ok) {
    throw new Error(`Failed to load daily report: ${response.status}`);
  }
  return response.json();
}
