export type RadarSource = {
  id?: string;
  name: string;
  url: string;
  tier: string;
  // Source category powers /all's 官方原文/媒体报道/社区讨论 filter.
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
      // "link" = 只有封面可展示、播放要跳原文（微信内嵌视频的直链带签名会过期，
      // 存下来必然变死链，所以不存）
      provider: "youtube" | "file" | "link";
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
  focus_category?: string | null;
  focus_category_label?: string;
  scoring_category?: string;
  scoring_category_label?: string;
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
  author?: string | null;
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
  // SourcePilot 契约: "published" = published_at 可信;"discovered" = 只有
  // 收录时间,展示必须写「收录于」,不得伪称原文发布时间。
  time_basis?: string;
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

export type DailyCategoryNote = {
  category: string;
  label: string;
  note: string;
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
  // AI 主线写自当天的多信源事件；分类简述写自各分类当天的全部条目。
  // summary_status 为 generated 才是真写出来的——其余取值（pending/
  // skipped/failed）下 mainline_* 是空串，页面整块不渲染。
  mainline_title?: string;
  mainline_body?: string;
  category_notes?: DailyCategoryNote[];
  summary_status?: string;
  summary_generated_at?: string | null;
};

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export function getApiBaseUrl() {
  return process.env.AI_RADAR_API_BASE_URL ?? DEFAULT_API_BASE_URL;
}

/** 取数的缓存档位。
 *
 *  这里原先一律是 `cache: "no-store"`，代价是每个访客请求都要打一次 API 再查一次库，
 *  而且会把页面钉成动态渲染、让 Next 发出 `no-store` 响应头，
 *  连 CDN 都不敢缓存 —— 等于把整站做成了一个人肉压测靶子。
 *  背景与实测数据见 docs/2026-08-13-hardening-plan.md。
 *
 *  开发环境保持不缓存：本地调数据时"改完立刻能看到"比省那点开销重要得多，
 *  当初写死 no-store 就是为了这个。线上要临时排查也可以用
 *  AI_RADAR_DISABLE_DATA_CACHE=1 一键退回旧行为。
 *
 *  注意这只是 Next 的数据层缓存。页面 HTML 那一层由 nginx 缓存
 *  （infra/nginx/radar-cf.conf），两层的 TTL 会叠加，改之前先看那边。 */
const DATA_CACHE_DISABLED =
  process.env.NODE_ENV !== "production" ||
  process.env.AI_RADAR_DISABLE_DATA_CACHE === "1";

function cacheFor(seconds: number): RequestInit {
  return DATA_CACHE_DISABLED ? { cache: "no-store" } : { next: { revalidate: seconds } };
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
  params: {
    limit?: number;
    offset?: number;
    category?: string;
    focus?: string;
    tag?: string;
    q?: string;
  } = {},
): Promise<LatestReport> {
  const search = new URLSearchParams();
  if (typeof params.limit === "number") {
    search.set("limit", String(params.limit));
  }
  if (typeof params.offset === "number") {
    search.set("offset", String(params.offset));
  }
  if (params.category) {
    search.set("category", params.category);
  }
  if (params.focus) {
    search.set("focus", params.focus);
  }
  if (params.tag) {
    search.set("tag", params.tag);
  }
  if (params.q) {
    search.set("q", params.q);
  }
  const query = search.toString();
  const path = query ? `/api/public/latest?${query}` : "/api/public/latest";
  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, cacheFor(60));
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
  params: {
    category?: string;
    focus?: string;
    tag?: string;
    q?: string;
    limit?: number;
  } = {},
): Promise<HotspotsPayload> {
  const search = new URLSearchParams();
  if (typeof params.limit === "number") {
    search.set("limit", String(params.limit));
  }
  if (params.category) {
    search.set("category", params.category);
  }
  if (params.focus) {
    search.set("focus", params.focus);
  }
  if (params.tag) {
    search.set("tag", params.tag);
  }
  if (params.q) {
    search.set("q", params.q);
  }
  const query = search.toString();
  const path = query ? `/api/public/hotspots?${query}` : "/api/public/hotspots";
  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, cacheFor(60));
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

export type TelegramChannel = {
  id: string;
  name: string;
  username: string;
  homepage: string;
};

export type TelegramEventsPayload = {
  updated_at: string | null;
  total: number;
  limit: number;
  offset: number;
  article_count: number;
  channels: TelegramChannel[];
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

function emptyTelegramEvents(error: string): TelegramEventsPayload {
  return {
    updated_at: null,
    total: 0,
    limit: 0,
    offset: 0,
    article_count: 0,
    channels: [],
    items: [],
    error,
  };
}

export async function getAllEvents(
  params: {
    days?: number;
    limit?: number;
    offset?: number;
    category?: string;
    focus?: string;
    source?: string;
    tag?: string;
    topic?: string;
    q?: string;
  } = {},
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
  if (params.category) {
    search.set("category", params.category);
  }
  if (params.focus) {
    search.set("focus", params.focus);
  }
  if (params.source) {
    search.set("source", params.source);
  }
  if (params.tag) {
    search.set("tag", params.tag);
  }
  if (params.q) {
    search.set("q", params.q);
  }
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/public/events?${search}`, cacheFor(60));
    if (!response.ok) {
      return emptyAllEvents(`API 服务暂时不可用：events 接口返回 ${response.status}。`);
    }
    const payload = (await response.json()) as AllEventsPayload;
    return { ...payload, error: null };
  } catch (error) {
    return emptyAllEvents(latestLoadErrorMessage(error));
  }
}

export async function getTelegramEvents(
  params: {
    days?: number;
    channel?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<TelegramEventsPayload> {
  const search = new URLSearchParams();
  search.set("days", String(params.days ?? 30));
  search.set("limit", String(params.limit ?? 50));
  if (params.channel) {
    search.set("channel", params.channel);
  }
  if (typeof params.offset === "number") {
    search.set("offset", String(params.offset));
  }
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/public/telegram?${search}`, cacheFor(60));
    if (!response.ok) {
      return emptyTelegramEvents(
        `API 服务暂时不可用：telegram 接口返回 ${response.status}。`,
      );
    }
    const payload = (await response.json()) as TelegramEventsPayload;
    return { ...payload, error: null };
  } catch (error) {
    return emptyTelegramEvents(latestLoadErrorMessage(error));
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
    const response = await fetch(`${getApiBaseUrl()}${path}`, cacheFor(300));
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
    const response = await fetch(`${getApiBaseUrl()}/api/public/topics`, cacheFor(600));
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
    const response = await fetch(`${getApiBaseUrl()}/api/public/reports/${mode}/archive`, cacheFor(600));
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
    const response = await fetch(`${getApiBaseUrl()}/api/public/reports/daily/archive`, cacheFor(600));
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
      cacheFor(300),
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
    cacheFor(300),
  );
  if (!response.ok) {
    throw new Error(`Failed to load daily report: ${response.status}`);
  }
  return response.json();
}

// ── X 推文（SourcePilot Phase 4）────────────────────────────────
// 数据是本地 x_tweets 镜像表（不进 LLM 管线），字段形状即 SP 契约 §5.4
// 的推文全貌。渲染约定（契约红线）：display_text 是 Markdown 且已织入配图，
// 渲染它时**不要**再渲染 media 数组；外链用 external_urls（已展开，别去
// 解析 t.co）。

export type TweetMedia = {
  type: "image" | "video" | "gif" | "audio";
  url: string;
  width?: number | null;
  height?: number | null;
};

export type XTweet = {
  tweet_id: string;
  conversation_id?: string | null;
  author_handle: string;
  author_name?: string | null;
  author_avatar?: string | null;
  author_verified?: boolean;
  author_followers?: number | null;
  text: string;
  lang?: string | null;
  created_at: string;
  likes: number;
  retweets: number;
  replies: number;
  quotes?: number;
  bookmarks?: number;
  views?: number | null;
  is_reply?: boolean;
  reply_to_handle?: string | null;
  is_quote?: boolean;
  quoted_handle?: string | null;
  quoted_text?: string | null;
  is_retweet?: boolean;
  retweeted_handle?: string | null;
  retweeted_text?: string | null;
  media?: TweetMedia[];
  external_urls?: string[];
  url: string;
  has_article?: boolean;
  article_title?: string | null;
  article_markdown?: string | null;
  article_summary?: string | null;
  article_ai_summary?: string | null;
  article_cover?: string | null;
  tweet_type: "original" | "reply" | "quote" | "repost";
  content_kind: "repost" | "article" | "longform" | "link" | "quote" | "brief";
  display_title?: string | null;
  display_text: string;
  // 命中的订阅话题标识（SP 契约 §5.5 事件追踪），订阅账号时间线来的为空数组
  topics?: string[];
  // AR 侧生成的中文翻译（方案 B），无译文或原文本就是中文时为 null
  translation?: XTweetTranslation | null;
};

export type TweetsPayload = {
  updated_at: string | null;
  total: number;
  limit: number;
  offset: number;
  item_count: number;
  // 库里出现过的话题标识（筛选 chips 的数据源）
  topics: string[];
  items: XTweet[];
  error: string | null;
};

function emptyTweets(error: string): TweetsPayload {
  return {
    updated_at: null,
    total: 0,
    limit: 0,
    offset: 0,
    item_count: 0,
    topics: [],
    items: [],
    error,
  };
}

export async function getTweets(
  params: {
    kind?: string;
    handle?: string;
    topic?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<TweetsPayload> {
  const search = new URLSearchParams();
  search.set("limit", String(params.limit ?? 50));
  if (typeof params.offset === "number") {
    search.set("offset", String(params.offset));
  }
  if (params.kind) {
    search.set("kind", params.kind);
  }
  if (params.handle) {
    search.set("handle", params.handle);
  }
  if (params.topic) {
    search.set("topic", params.topic);
  }
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/public/tweets?${search}`, cacheFor(60));
    if (!response.ok) {
      return emptyTweets(`API 服务暂时不可用：tweets 接口返回 ${response.status}。`);
    }
    const payload = (await response.json()) as Omit<TweetsPayload, "error">;
    return { ...payload, error: null };
  } catch (error) {
    return emptyTweets(latestLoadErrorMessage(error));
  }
}

export async function getTweet(tweetId: string): Promise<XTweet | null> {
  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/public/tweets/${encodeURIComponent(tweetId)}`,
      cacheFor(300),
    );
    if (!response.ok) {
      return null;
    }
    const payload = (await response.json()) as { item: XTweet };
    return payload.item;
  } catch {
    return null;
  }
}

export type XTweetTranslation = {
  display_text_zh: string;
  quoted_text_zh?: string | null;
};
