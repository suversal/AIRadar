/** 文章图片代理：中文媒体 CDN 防盗链分两派——infoq（无 Referer 放行）
 *  和 qbitai（白名单制，无 Referer 也 403）。浏览器无法伪造 Referer，
 *  所以服务端代取，请求带图片自身 origin 作 Referer（各家实测均放行）。
 *
 *  ⚠ 这个接口对外接受任意 URL，本质是一个代理，必须自己管住准入与资源占用：
 *    - 目标地址必须在公网（见 lib/image-proxy-guard.ts），否则它就是内网扫描器；
 *    - 重定向手动跟，每一跳都重新校验，否则 302 一下就绕过去了；
 *    - 超时和体积都要封顶，否则一个慢上游就能把连接占住。
 *    背景见 docs/2026-08-13-hardening-plan.md 第 1.2 节。 */

import {
  assertPublicHost,
  isKnownImageHost,
  shouldEnforceKnownHosts,
} from "@/lib/image-proxy-guard";

const BROWSER_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

/** 上游取图的超时。原来是 15s——一个慢上游能把连接占住 15 秒，
 *  攻击者只要并发几百个这样的请求就能把 Node 的事件循环拖住。 */
const UPSTREAM_TIMEOUT_MS = 8_000;

/** 单张图的体积上限。正常文章配图都在 1MB 以内，8MB 已经很宽松。 */
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;

/** 手动跟随重定向的跳数上限。图床一般 0~1 跳。 */
const MAX_REDIRECTS = 3;

const IMAGE_TYPE_BY_EXTENSION: Record<string, string> = {
  ".avif": "image/avif",
  ".bmp": "image/bmp",
  ".gif": "image/gif",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
};

function inferredImageType(url: URL, contentType: string) {
  const normalizedType = contentType.split(";", 1)[0]?.trim().toLowerCase();
  if (normalizedType?.startsWith("image/")) {
    return normalizedType;
  }
  // Google Cloud Storage can serve valid WebP/JPEG/PNG objects as generic
  // octet-stream when their object metadata lacks a content type. Only
  // recover well-known image extensions; arbitrary binary responses remain
  // rejected instead of being reflected through this same-origin endpoint.
  if (normalizedType !== "application/octet-stream") {
    return null;
  }
  const pathname = url.pathname.toLowerCase();
  return Object.entries(IMAGE_TYPE_BY_EXTENSION).find(([extension]) =>
    pathname.endsWith(extension),
  )?.[1] ?? null;
}

/** 把上游响应体按字节数封顶后再转给客户端。
 *  只看 Content-Length 是不够的：分块传输可以不带这个头，
 *  或者带一个假的小值然后一直发。 */
function cappedBody(body: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  let received = 0;
  const reader = body.getReader();
  return new ReadableStream({
    async pull(controller) {
      const { done, value } = await reader.read();
      if (done) {
        controller.close();
        return;
      }
      received += value.byteLength;
      if (received > MAX_IMAGE_BYTES) {
        await reader.cancel();
        controller.error(new Error("image too large"));
        return;
      }
      controller.enqueue(value);
    },
    cancel(reason) {
      void reader.cancel(reason);
    },
  });
}

/** 逐跳校验的重定向跟随。fetch 自带的 redirect: "follow" 不会给我们
 *  中间那几跳的机会，而"先校验域名、再让它 302 到 127.0.0.1"是绕过 SSRF
 *  防护的标准手法。 */
async function fetchImage(start: URL, signal: AbortSignal) {
  let target = start;
  for (let hop = 0; hop <= MAX_REDIRECTS; hop += 1) {
    const guard = await assertPublicHost(target);
    if (!guard.ok) {
      return { error: guard.reason, status: 400 } as const;
    }
    if (shouldEnforceKnownHosts() && !isKnownImageHost(target.hostname)) {
      return { error: `host not allowed: ${target.hostname}`, status: 403 } as const;
    }
    if (!isKnownImageHost(target.hostname)) {
      // 强制模式打开之前，先靠日志把真实的图床名单攒齐
      console.warn(`[image-proxy] unknown host: ${target.hostname}`);
    }

    const response = await fetch(target.toString(), {
      redirect: "manual",
      headers: {
        "User-Agent": BROWSER_UA,
        Referer: `${target.origin}/`,
        Accept: "image/*,*/*;q=0.8",
      },
      signal,
    });

    if (response.status < 300 || response.status >= 400) {
      return { response, url: target } as const;
    }
    const location = response.headers.get("location");
    if (!location) {
      return { error: "redirect without location", status: 502 } as const;
    }
    void response.body?.cancel();
    try {
      target = new URL(location, target);
    } catch {
      return { error: "invalid redirect target", status: 502 } as const;
    }
    if (target.protocol !== "http:" && target.protocol !== "https:") {
      return { error: "unsupported redirect protocol", status: 400 } as const;
    }
  }
  return { error: "too many redirects", status: 502 } as const;
}

export async function GET(request: Request) {
  const target = new URL(request.url).searchParams.get("url");
  if (!target) {
    return new Response("missing url", { status: 400 });
  }
  let parsed: URL;
  try {
    parsed = new URL(target);
  } catch {
    return new Response("invalid url", { status: 400 });
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return new Response("unsupported protocol", { status: 400 });
  }

  const abort = AbortSignal.timeout(UPSTREAM_TIMEOUT_MS);
  try {
    const result = await fetchImage(parsed, abort);
    if ("error" in result) {
      return new Response(result.error, { status: result.status });
    }
    const { response: upstream, url: finalUrl } = result;
    const contentType = upstream.headers.get("content-type") ?? "";
    const responseImageType = inferredImageType(finalUrl, contentType);
    if (!upstream.ok || !responseImageType) {
      void upstream.body?.cancel();
      return new Response("upstream is not an image", { status: 502 });
    }
    const declaredLength = Number(upstream.headers.get("content-length") ?? "");
    if (Number.isFinite(declaredLength) && declaredLength > MAX_IMAGE_BYTES) {
      void upstream.body?.cancel();
      return new Response("image too large", { status: 502 });
    }
    if (!upstream.body) {
      return new Response("upstream is not an image", { status: 502 });
    }
    return new Response(cappedBody(upstream.body), {
      status: 200,
      headers: {
        "Content-Type": responseImageType,
        "Cache-Control": "public, max-age=86400, immutable",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return new Response("upstream fetch failed", { status: 502 });
  }
}
