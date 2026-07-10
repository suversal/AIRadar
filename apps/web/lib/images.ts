/** 外链文章图统一走服务端代理，绕开各家 CDN 防盗链（详见
 *  app/api/image-proxy/route.ts）。站内相对路径与 data: URI 原样返回。 */
export function proxiedImageUrl(url: string | undefined): string {
  if (!url) {
    return "";
  }
  if (!/^https?:\/\//i.test(url)) {
    return url;
  }
  return `/api/image-proxy?url=${encodeURIComponent(url)}`;
}
