/** 文章图片代理：中文媒体 CDN 防盗链分两派——infoq（无 Referer 放行）
 *  和 qbitai（白名单制，无 Referer 也 403）。浏览器无法伪造 Referer，
 *  所以服务端代取，请求带图片自身 origin 作 Referer（各家实测均放行）。 */

const BROWSER_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

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

  try {
    const upstream = await fetch(parsed.toString(), {
      headers: {
        "User-Agent": BROWSER_UA,
        Referer: `${parsed.origin}/`,
        Accept: "image/*,*/*;q=0.8",
      },
      signal: AbortSignal.timeout(15_000),
    });
    const contentType = upstream.headers.get("content-type") ?? "";
    if (!upstream.ok || !contentType.startsWith("image/")) {
      return new Response("upstream is not an image", { status: 502 });
    }
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "public, max-age=86400, immutable",
      },
    });
  } catch {
    return new Response("upstream fetch failed", { status: 502 });
  }
}
