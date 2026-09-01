// v1 对外 API 的传输层约定：错误格式、条件请求、缓存与 CORS。
//
// 这一层存在的理由和 lib/v1/shape.ts 一样：/api/public/* 是内部 payload，
// 形状随后端演进；对外必须有一份自己说了算的合同。所有 v1 路由都从这里
// 拿响应构造器，任何一个绕过它自己 new Response 的地方，都会在错误格式、
// ETag 或 CORS 上和别人不一致。

import { createHash } from "node:crypto";
import { siteUrl } from "@/lib/site";
import { UpstreamError } from "./upstream";

/** 错误码。稳定契约的一部分：客户端按 code 分支，不要解析 detail 文案。 */
export type V1ErrorCode =
  | "invalid_parameter"
  | "unknown_parameter"
  | "duplicate_parameter"
  | "not_found"
  | "upstream_unavailable"
  | "internal_error";

const ERROR_TITLES: Record<V1ErrorCode, string> = {
  invalid_parameter: "参数不合法",
  unknown_parameter: "包含未声明的参数",
  duplicate_parameter: "参数重复",
  not_found: "资源不存在",
  upstream_unavailable: "上游数据源暂时不可用",
  internal_error: "服务内部错误",
};

/** 路由里抛它，handleV1 会翻成 Problem JSON。 */
export class V1Error extends Error {
  constructor(
    readonly status: number,
    readonly code: V1ErrorCode,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "V1Error";
  }
}

export function badRequest(code: V1ErrorCode, detail: string) {
  return new V1Error(400, code, detail);
}

export function notFound(detail: string) {
  return new V1Error(404, "not_found", detail);
}

const CORS_HEADERS: Record<string, string> = {
  // 匿名只读，公开数据，浏览器直连是正式支持路径。不带 credentials，
  // 所以 * 是安全的（配 credentials 时浏览器会自己拒绝 *）。
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "If-None-Match, Content-Type",
  // 不 expose 的话跨域 JS 读不到 ETag，条件请求就只剩服务端能用。
  "Access-Control-Expose-Headers": "ETag, X-Request-Id, Retry-After",
  "Access-Control-Max-Age": "86400",
};

/** 缓存分档（秒）。s-maxage 同时是给客户端的轮询节奏建议——
 *  比它更密只会拿到同一份共享缓存副本。 */
export const CACHE = {
  items: 60,
  hotTopics: 300,
  story: 300,
  dailyLatest: 300,
  /** 历史日报封版后不再变 */
  dailyArchived: 3600,
  dailyIndex: 600,
  /** 当前周/月仍会随日报更新；已封版期次可以长缓存 */
  periodLatest: 300,
  periodArchived: 3600,
  periodIndex: 600,
  topics: 600,
  feed: 900,
} as const;

function cacheHeaders(sMaxAge: number): Record<string, string> {
  return {
    // max-age=0 让浏览器每次都回来问，共享缓存（nginx / CF）按 s-maxage 扛量。
    "Cache-Control": `public, max-age=0, s-maxage=${sMaxAge}, stale-while-revalidate=${sMaxAge * 5}`,
  };
}

function requestId(): string {
  return crypto.randomUUID();
}

function weakEtag(body: string): string {
  return `W/"${createHash("sha1").update(body).digest("base64url")}"`;
}

/** If-None-Match 比对。客户端可以回传多个，也可能带 W/ 前缀。 */
function etagMatches(header: string | null, etag: string): boolean {
  if (!header) return false;
  if (header.trim() === "*") return true;
  const normalize = (value: string) => value.trim().replace(/^W\//, "");
  const target = normalize(etag);
  return header.split(",").some((candidate) => normalize(candidate) === target);
}

/**
 * 带 ETag 条件请求的文本响应。RSS、llms.txt、OpenAPI 都走它，
 * 这样"支持 304"是全站一条实现，而不是每个出口各写一遍。
 *
 * 同样的告诫：body 里不要放随时刻变化的内容，否则 ETag 每次都变。
 * RSS 的 lastBuildDate 因此取最新条目的时间，而不是 new Date()。
 */
export function conditionalText(
  request: Request,
  body: string,
  contentType: string,
  sMaxAge: number,
): Response {
  const etag = weakEtag(body);
  const headers: Record<string, string> = {
    ...CORS_HEADERS,
    ...cacheHeaders(sMaxAge),
    ETag: etag,
  };
  if (etagMatches(request.headers.get("if-none-match"), etag)) {
    return new Response(null, { status: 304, headers });
  }
  return new Response(body, {
    status: 200,
    headers: { ...headers, "Content-Type": contentType },
  });
}

export type V1Payload = Record<string, unknown>;

export type V1Success = {
  payload: V1Payload;
  sMaxAge: number;
};

/**
 * 路由 handler 的返回值：数据 + 该端点的缓存档位。
 *
 * ⚠️ payload 里绝不能放随请求时刻变化的字段（Date.now、随机 id）。
 * ETag 是 payload 的哈希，塞一个 generatedAt 进去，每次响应的 ETag 都不同，
 * If-None-Match 永远命中不了，条件请求和共享缓存一起失效——而且不报错，
 * 只是所有人的轮询都变成全量下载。响应生成时刻由 HTTP 的 Date 头表达。
 */
export function ok(payload: V1Payload, sMaxAge: number): V1Success {
  return { payload, sMaxAge };
}

function problemResponse(
  status: number,
  code: V1ErrorCode,
  detail: string,
  id: string,
): Response {
  const body = JSON.stringify({
    // RFC 9457 Problem Details。type 指向文档锚点，方便人排查。
    // 走 siteUrl 而不是写死域名：备用机与本地开发的 Problem type
    // 否则会指向线上域，排查时点过去看到的是另一台机器的文档。
    type: new URL(`/agent#error-${code}`, siteUrl).toString(),
    title: ERROR_TITLES[code],
    status,
    detail,
    code,
    requestId: id,
  });
  return new Response(body, {
    status,
    headers: {
      ...CORS_HEADERS,
      "Content-Type": "application/problem+json; charset=utf-8",
      // 错误不进共享缓存：参数改对了就该立刻好，不该被上一次的 400 挡住。
      "Cache-Control": "no-store",
      "X-Request-Id": id,
    },
  });
}

/**
 * 把一个 v1 handler 包成 Next.js route handler。
 *
 * 负责：Problem JSON 错误、ETag/304 条件请求、缓存头、CORS。
 * handler 只管取数和塑形，不碰响应头。
 */
export function handleV1<Context>(
  handler: (request: Request, context: Context) => Promise<V1Success>,
) {
  return async function GET(request: Request, context: Context): Promise<Response> {
    const id = requestId();
    try {
      const { payload, sMaxAge } = await handler(request, context);
      const body = JSON.stringify(payload);
      const etag = weakEtag(body);
      const headers: Record<string, string> = {
        ...CORS_HEADERS,
        ...cacheHeaders(sMaxAge),
        ETag: etag,
        "X-Request-Id": id,
      };

      if (etagMatches(request.headers.get("if-none-match"), etag)) {
        // 304 不能带 body，但必须带 ETag 和 Cache-Control，
        // 否则中间缓存下一轮不知道该拿什么比对。
        return new Response(null, { status: 304, headers });
      }

      return new Response(body, {
        status: 200,
        headers: { ...headers, "Content-Type": "application/json; charset=utf-8" },
      });
    } catch (error) {
      if (error instanceof V1Error) {
        return problemResponse(error.status, error.code, error.detail, id);
      }

      // 排障信息只进服务端日志。回给客户端的 detail 里回显 error.message，
      // 会把内网路径和上游状态码泄露出去（"上游 /api/public/... 返回 500"）。
      console.error(`[v1] request ${id} failed:`, error);

      // 上游 5xx / 网络故障是瞬时的，客户端该退避重试；上游 4xx 说明我们
      // 发了个它不认的请求，那是本层的 bug——报成 503 会让客户端照着
      // "退避后重试"的文档把一个永久故障重试到天荒地老。
      const transient =
        !(error instanceof UpstreamError) || error.status >= 500;

      return transient
        ? problemResponse(
            503,
            "upstream_unavailable",
            `数据源暂时不可用，请稍后重试。反馈时附上 requestId ${id}。`,
            id,
          )
        : problemResponse(
            500,
            "internal_error",
            `服务内部错误，重试不会改善。请把 requestId ${id} 提交到反馈页。`,
            id,
          );
    }
  };
}

/** 预检。所有 v1 路由导出同一个。 */
export function OPTIONS(): Response {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}
