export type RadarSource = {
  id?: string;
  name: string;
  url: string;
  tier: string;
  // official/research/community/media - drives /all's 一手信源/资讯/推文 filter
  category?: string;
};

export type OriginalImage = {
  url: string;
  alt?: string;
  caption?: string;
  fallback_url?: string;
  width?: number;
  height?: number;
  role?: "hero" | "content";
};

export type InlineContent = { text: string; html?: string };

export type ContentLink = {
  label: string;
  url: string;
  host: string;
};

export type OriginalBlock =
  | {
      type: "paragraph";
      text: string;
      html?: string;
      align?: "left" | "center" | "right" | "justify";
    }
  | {
      type: "heading";
      level: 1 | 2 | 3 | 4 | 5 | 6;
      text: string;
      html?: string;
      align?: "left" | "center" | "right" | "justify";
    }
  | {
      type: "image";
      url: string;
      alt?: string;
      caption?: string;
      fallback_url?: string;
      width?: number;
      height?: number;
      role?: "hero" | "content";
    }
  | {
      type: "video";
      provider: "youtube" | "file";
      url: string;
      title?: string;
      caption?: string;
      mime_type?: "video/mp4" | "video/webm" | "video/ogg";
      poster_url?: string;
      width?: number;
      height?: number;
      autoplay?: boolean;
      loop?: boolean;
      muted?: boolean;
    }
  | {
      type: "social_embed";
      provider: "x";
      url: string;
      author_name?: string;
      username?: string;
      avatar_url?: string;
      text?: string;
      published_at?: string;
      video_url?: string;
      video_mime_type?: "video/mp4";
      poster_url?: string;
      reply_count?: number;
      repost_count?: number;
      like_count?: number;
      view_count?: number;
    }
  | {
      type: "source_list";
      links: ContentLink[];
    }
  | {
      type: "quote";
      kind: "reply" | "update" | "quote";
      label?: string;
      author?: string;
      source_url?: string;
      children: OriginalBlock[];
    }
  | {
      type: "byline";
      author: { name: string; url?: string; avatar_url?: string };
      published_at?: string;
      source?: { name: string; url?: string };
    }
  | { type: "callout"; kind: "lead" | "note"; children: OriginalBlock[] }
  | { type: "list"; ordered: boolean; items: InlineContent[] }
  | { type: "code"; text: string; language?: string }
  | { type: "table"; headers: InlineContent[]; rows: InlineContent[][] }
  | { type: "divider" };

export type EventCoverageItem = {
  raw_article_id: string;
  title: string;
  source_name: string;
  source_url?: string;
  published_at?: string;
  is_main: boolean;
  // 站内跳转地址:主条是真实事件 ID,非主条是该文章自己的 a{id} 伪地址
  event_id: string;
};

export type LatestEvent = {
  event_id: string;
  title: string;
  category?: string;
  category_label?: string;
  tags?: string[];
  final_score?: number;
  // authoritative "is this article selected" signal from scoring_service's
  // per-category threshold - prefer this over re-deriving from final_score
  selected?: boolean;
  selection_origin?: string;
  selection_reason?: string | null;
  hidden?: boolean;
  source_count?: number;
  main_source?: RadarSource;
  coverage?: EventCoverageItem[];
  source_language?: string;
  one_line_summary?: string;
  summary?: string;
  reason?: string;
  action?: string;
  published_at?: string;
  last_seen_at?: string;
  original_url?: string;
  original_content?: string;
  original_markdown?: string;
  original_paragraphs?: string[];
  original_images?: OriginalImage[];
  original_blocks?: OriginalBlock[];
  translated_content?: string;
  translated_paragraphs?: string[];
  translated_blocks?: OriginalBlock[];
  // Includes "aihot_item_page_link_only" and
  // "telegram_rss_description" content provenance markers.
  content_origin?: string;
};

export type LatestReport = {
  report_date?: string | null;
  updated_at: string | null;
  article_count?: number;
  total?: number;
  limit?: number;
  offset?: number;
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

export async function getLatestReport(
  params: { limit?: number; offset?: number } = {},
): Promise<LatestReport> {
  const search = new URLSearchParams();
  if (typeof params.limit === "number") {
    search.set("limit", String(params.limit));
  }
  if (typeof params.offset === "number") {
    search.set("offset", String(params.offset));
  }
  const query = search.toString();
  const path = query ? `/api/public/latest?${query}` : "/api/public/latest";
  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
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

export type HotspotsPayload = {
  window_hours: number;
  item_count: number;
  items: LatestEvent[];
};

export async function getHotspots(
  params: { category?: string; q?: string } = {},
): Promise<HotspotsPayload> {
  const search = new URLSearchParams();
  if (params.category) {
    search.set("category", params.category);
  }
  if (params.q) {
    search.set("q", params.q);
  }
  const query = search.toString();
  const path = query ? `/api/public/hotspots?${query}` : "/api/public/hotspots";
  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      cache: "no-store",
    });
    if (!response.ok) {
      return { window_hours: 48, item_count: 0, items: [] };
    }
    return (await response.json()) as HotspotsPayload;
  } catch {
    return { window_hours: 48, item_count: 0, items: [] };
  }
}

export type AllEventsPayload = {
  report_dates: string[];
  updated_at: string | null;
  total: number;
  limit: number;
  offset: number;
  article_count: number;
  items: LatestEvent[];
  error?: string | null;
};

export type PeriodReport = {
  mode: "weekly" | "monthly";
  period_key?: string;
  generated?: boolean;
  mainline_title?: string;
  mainline_body?: string;
  theme_notes?: { label: string; note: string }[];
  summary_status?: string;
  range_start: string;
  range_end: string;
  report_dates: string[];
  updated_at: string | null;
  article_count: number;
  items: LatestEvent[];
  error?: string | null;
};

export type PeriodArchiveEntry = {
  period_key: string;
  range_start: string;
  range_end: string;
  mainline_title: string;
  article_count: number;
};

function emptyAllEvents(error: string): AllEventsPayload {
  return {
    report_dates: [],
    updated_at: null,
    total: 0,
    limit: 0,
    offset: 0,
    article_count: 0,
    items: [],
    error,
  };
}

export async function getAllEvents(
  params: { days?: number; limit?: number; offset?: number; topic?: string } = {},
): Promise<AllEventsPayload> {
  const search = new URLSearchParams();
  search.set("days", String(params.days ?? 30));
  search.set("limit", String(params.limit ?? 200));
  if (typeof params.offset === "number") {
    search.set("offset", String(params.offset));
  }
  if (params.topic) {
    search.set("topic", params.topic);
  }
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/public/events?${search}`, {
      cache: "no-store",
    });
    if (!response.ok) {
      return emptyAllEvents(`API 服务暂时不可用：events 接口返回 ${response.status}。`);
    }
    const payload = (await response.json()) as AllEventsPayload;
    return { ...payload, error: null };
  } catch (error) {
    return emptyAllEvents(latestLoadErrorMessage(error));
  }
}

function emptyPeriodReport(mode: "weekly" | "monthly", error: string): PeriodReport {
  return {
    mode,
    range_start: "",
    range_end: "",
    report_dates: [],
    updated_at: null,
    article_count: 0,
    items: [],
    error,
  };
}

export async function getPeriodReport(
  mode: "weekly" | "monthly",
  periodKey?: string,
): Promise<PeriodReport> {
  const path = periodKey
    ? `/api/public/reports/${mode}/${encodeURIComponent(periodKey)}`
    : `/api/public/reports/${mode}`;
  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      cache: "no-store",
    });
    if (!response.ok) {
      return emptyPeriodReport(mode, `API 服务暂时不可用：${mode} 接口返回 ${response.status}。`);
    }
    const payload = (await response.json()) as PeriodReport;
    return { ...payload, error: null };
  } catch (error) {
    return emptyPeriodReport(mode, latestLoadErrorMessage(error));
  }
}

export type TopicSummary = {
  id: string;
  name: string;
  count: number;
};

export type TopicGroup = {
  id: string;
  name: string;
  description: string;
  topics: TopicSummary[];
};

export type TopicsPayload = {
  groups: TopicGroup[];
  article_count: number;
  error?: string | null;
};

export async function getTopics(): Promise<TopicsPayload> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/public/topics`, {
      cache: "no-store",
    });
    if (!response.ok) {
      return {
        groups: [],
        article_count: 0,
        error: `API 服务暂时不可用：topics 接口返回 ${response.status}。`,
      };
    }
    const payload = (await response.json()) as TopicsPayload;
    return { ...payload, error: null };
  } catch (error) {
    return { groups: [], article_count: 0, error: latestLoadErrorMessage(error) };
  }
}

export async function getPeriodArchive(
  mode: "weekly" | "monthly",
): Promise<PeriodArchiveEntry[]> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/public/reports/${mode}/archive`, {
      cache: "no-store",
    });
    if (!response.ok) {
      return [];
    }
    return ((await response.json()).entries ?? []) as PeriodArchiveEntry[];
  } catch {
    return [];
  }
}

export async function getDailyArchive(): Promise<string[]> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/public/reports/daily/archive`, {
      cache: "no-store",
    });
    if (!response.ok) {
      return [];
    }
    return ((await response.json()).dates ?? []) as string[];
  } catch {
    return [];
  }
}

export async function getEventDetail(eventId: string): Promise<LatestEvent | null> {
  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/public/events/${encodeURIComponent(eventId)}`,
      { cache: "no-store" },
    );
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as LatestEvent;
  } catch {
    return null;
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
