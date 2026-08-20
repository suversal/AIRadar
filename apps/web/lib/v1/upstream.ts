// v1 到内网 FastAPI 的取数。
//
// 不复用 lib/api.ts 的取数函数：那些为页面而写，上游挂掉时返回
// { items: [], error } 让页面照常渲染骨架。对 API 来说这是有害的——
// 客户端会把"上游 503"当成"今天没有内容"存进自己的库。v1 这里失败就抛，
// 由 handleV1 翻成 503，让调用方按退避重试。

import { getApiBaseUrl } from "@/lib/api";
import { notFound } from "./http";

/** 上游返回 404 时抛这个，路由可以 catch 后换成自己的文案。 */
export class UpstreamNotFound extends Error {}

/**
 * 上游返回了非 404 的错误状态。
 *
 * 带上 status 是为了让 handleV1 能分清两种完全不同的故障：上游 5xx 是
 * 瞬时的（客户端该退避重试），上游 4xx 说明我们发了个它不认的请求——那是
 * 我们自己的 bug，客户端重试一万次也不会好。都报成 503 会让客户端按
 * "退避后重试"的文档指引永远重试一个永久故障。
 */
export class UpstreamError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
  ) {
    super(`上游 ${path} 返回 ${status}`);
    this.name = "UpstreamError";
  }
}

export async function fetchUpstream<T>(
  path: string,
  options: { revalidate: number; notFoundDetail?: string },
): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    // v1 响应自身有 s-maxage，这层再缓存一次是为了扛住共享缓存穿透的瞬间并发。
    next: { revalidate: options.revalidate },
  });

  if (response.status === 404) {
    if (options.notFoundDetail) {
      throw notFound(options.notFoundDetail);
    }
    throw new UpstreamNotFound(path);
  }
  if (!response.ok) {
    throw new UpstreamError(response.status, path);
  }
  return (await response.json()) as T;
}

/** 上游单页上限（/api/public/* 的 limit 校验就是 200）。 */
export const UPSTREAM_PAGE_SIZE = 200;

/**
 * 沿倒序结果取"落在时间窗内的前缀"。
 *
 * 上游一律按 published_at DESC 排序，所以窗口内的条目必然是结果的前缀：
 * 一旦读到第一条早于 cutoff 的，后面不可能再有更新的，可以停。
 *
 * 为什么不把 hours 下推给后端：/api/public/* 只有天粒度的 days，
 * "过去 24 小时"和"今天"不是一回事——早上八点问，后者只有八小时内容。
 * Agent 最常问的就是过去 24 小时，这个窗口必须准。
 */
export async function collectWithinWindow<T>(
  loadPage: (offset: number, limit: number) => Promise<{ items: T[]; total: number }>,
  publishedAtOf: (item: T) => string | null,
  cutoffMs: number,
): Promise<T[]> {
  const collected: T[] = [];
  let offset = 0;
  let total = Number.POSITIVE_INFINITY;

  while (offset < total) {
    const page = await loadPage(offset, UPSTREAM_PAGE_SIZE);
    total = page.total;
    if (page.items.length === 0) {
      break;
    }
    for (const item of page.items) {
      const raw = publishedAtOf(item);
      // 没有时间戳的条目在 DESC 排序里位置不确定（Postgres 的 NULLS FIRST），
      // 既不收进窗口也不拿它当停止信号，跳过就好。
      if (!raw) continue;
      const parsed = Date.parse(raw);
      if (Number.isNaN(parsed)) continue;
      if (parsed < cutoffMs) {
        return collected;
      }
      collected.push(item);
    }
    offset += page.items.length;
  }

  return collected;
}
