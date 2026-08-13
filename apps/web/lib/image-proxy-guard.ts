/** /api/image-proxy 的准入判断：目标必须是公网上的真实图床。
 *
 *  这个接口原先只校验了协议，`url` 参数可以指向任何地址，等于对外提供了一个
 *  开放代理：谁都能拿它白嫖我们的出口带宽，也能拿它探内网和云厂商的元数据服务
 *  （169.254.169.254）。背景见 docs/2026-08-13-hardening-plan.md。 */

import { lookup } from "node:dns/promises";

/** 数据里实际出现过的图床。用途是"分级"而不是"准入"：
 *  默认只记日志不拦截，因为新信源随时会带来新图床，硬白名单会造成
 *  静默的"图片全白"事故。等日志攒够、确认名单齐了，再用
 *  IMAGE_PROXY_ENFORCE_HOSTS=1 切成强制模式。
 *
 *  匹配规则是"域名或其子域"，所以写 `ithome.com` 就覆盖 `img.ithome.com`。 */
const KNOWN_IMAGE_HOSTS = [
  "aihot.virxact.com",
  "anthropic.com",
  "geekbang.org",
  "githubusercontent.com",
  "ifanr.com",
  "infoq.cn",
  "infoq.com",
  "ithome.com",
  "latent.space",
  "qpic.cn", // 微信图床 mmbiz.qpic.cn
  "sinaimg.cn",
  "telesco.pe", // Telegram cdn*.telesco.pe
  "twimg.com",
  "zhimg.com",
  "36kr.com",
];

export function isKnownImageHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/\.$/, "");
  return KNOWN_IMAGE_HOSTS.some(
    (known) => host === known || host.endsWith(`.${known}`),
  );
}

export function shouldEnforceKnownHosts(): boolean {
  return process.env.IMAGE_PROXY_ENFORCE_HOSTS === "1";
}

function ipv4IsPrivate(ip: string): boolean {
  const parts = ip.split(".").map(Number);
  if (parts.length !== 4 || parts.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) {
    return true; // 解析不出来就当作不可信
  }
  const [a, b] = parts;
  return (
    a === 0 || // 0.0.0.0/8 本网络
    a === 10 || // 10/8 私有
    a === 127 || // 环回
    (a === 100 && b >= 64 && b <= 127) || // 100.64/10 运营商级 NAT
    (a === 169 && b === 254) || // 链路本地，含云元数据 169.254.169.254
    (a === 172 && b >= 16 && b <= 31) || // 172.16/12 私有
    (a === 192 && b === 168) || // 192.168/16 私有
    (a === 192 && b === 0) || // 192.0.0/24 + 192.0.2/24
    (a === 198 && (b === 18 || b === 19)) || // 基准测试网段
    a >= 224 // 组播与保留
  );
}

/** 把 IPv6 展开成 8 组 16 位整数。
 *
 *  必须真的解析，不能靠字符串前缀匹配：同一个地址有多种写法，
 *  而且 WHATWG URL 会做规范化——`::ffff:127.0.0.1` 进 new URL() 之后
 *  变成 `::ffff:7f00:1`，按字面量匹配 "::ffff:" + 点分十进制会直接漏掉。
 *  这是本地用例跑出来的，别改回字符串匹配。 */
function expandIpv6(addr: string): number[] | null {
  let text = addr;
  // 结尾可能是内嵌的点分 IPv4（::ffff:1.2.3.4），先换成两组十六进制
  const dotted = text.match(/(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (dotted) {
    const bytes = dotted.slice(1).map(Number);
    if (bytes.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) {
      return null;
    }
    const hi = ((bytes[0] << 8) | bytes[1]).toString(16);
    const lo = ((bytes[2] << 8) | bytes[3]).toString(16);
    text = `${text.slice(0, dotted.index)}${hi}:${lo}`;
  }
  const halves = text.split("::");
  if (halves.length > 2) {
    return null;
  }
  const parse = (part: string) =>
    part === "" ? [] : part.split(":").map((g) => parseInt(g, 16));
  const head = parse(halves[0]);
  const tail = halves.length === 2 ? parse(halves[1]) : [];
  const groups =
    halves.length === 2
      ? [...head, ...Array(8 - head.length - tail.length).fill(0), ...tail]
      : head;
  if (groups.length !== 8 || groups.some((g) => !Number.isInteger(g) || g < 0 || g > 0xffff)) {
    return null;
  }
  return groups;
}

function ipv6IsPrivate(ip: string): boolean {
  const groups = expandIpv6(ip.toLowerCase().split("%")[0]);
  if (!groups) {
    return true; // 解析不出来就当作不可信
  }
  const leadingZero = groups.slice(0, 5).every((g) => g === 0);
  // ::（未指定）与 ::1（环回）
  if (leadingZero && groups[5] === 0 && groups[6] === 0 && groups[7] <= 1) {
    return true;
  }
  // ::ffff:a.b.c.d（IPv4 映射）与 ::a.b.c.d（已废弃的 IPv4 兼容），按 IPv4 规则判
  if (leadingZero && (groups[5] === 0xffff || groups[5] === 0)) {
    const v4 = [groups[6] >> 8, groups[6] & 0xff, groups[7] >> 8, groups[7] & 0xff].join(".");
    return ipv4IsPrivate(v4);
  }
  if ((groups[0] & 0xfe00) === 0xfc00) {
    return true; // fc00::/7 唯一本地地址
  }
  if ((groups[0] & 0xffc0) === 0xfe80) {
    return true; // fe80::/10 链路本地
  }
  if ((groups[0] & 0xff00) === 0xff00) {
    return true; // ff00::/8 组播
  }
  return false;
}

export function isPrivateAddress(ip: string, family: number): boolean {
  return family === 4 ? ipv4IsPrivate(ip) : ipv6IsPrivate(ip);
}

export type GuardResult = { ok: true } | { ok: false; reason: string };

/** 解析主机名并确认它的每一个地址都在公网上。
 *
 *  ⚠ 这里存在一个无法根除的 TOCTOU 窗口：我们校验的是这一刻的解析结果，
 *    随后 fetch 会自己再解析一次，理论上攻击者可以用极短 TTL 的 DNS 记录
 *    让两次解析拿到不同的地址（DNS rebinding）。要彻底封死得自己按 IP 建连
 *    并手动带 Host 头 + TLS SNI，代价远大于收益：这个接口的响应被限制成
 *    image/*，拿不回内网服务的正文。这里挡的是"随手拿它当扫描器"那一档。 */
export async function assertPublicHost(url: URL): Promise<GuardResult> {
  const hostname = url.hostname;
  if (!hostname) {
    return { ok: false, reason: "empty hostname" };
  }
  // 带凭据的 URL 一律拒绝：正常图床链接不会有，出现即可疑
  if (url.username || url.password) {
    return { ok: false, reason: "credentials in url" };
  }
  const bare = hostname.replace(/^\[|\]$/g, "");
  if (bare === "localhost" || bare.endsWith(".localhost") || bare.endsWith(".internal")) {
    return { ok: false, reason: `blocked hostname: ${hostname}` };
  }

  // 字面量 IP：不用查 DNS，直接判
  if (/^\d+\.\d+\.\d+\.\d+$/.test(bare)) {
    return ipv4IsPrivate(bare)
      ? { ok: false, reason: `private address: ${bare}` }
      : { ok: true };
  }
  if (bare.includes(":")) {
    return ipv6IsPrivate(bare)
      ? { ok: false, reason: `private address: ${bare}` }
      : { ok: true };
  }

  let addresses: Array<{ address: string; family: number }>;
  try {
    addresses = await lookup(bare, { all: true });
  } catch {
    return { ok: false, reason: `dns lookup failed: ${bare}` };
  }
  if (addresses.length === 0) {
    return { ok: false, reason: `no address for ${bare}` };
  }
  // 任意一条解析到内网就拒绝：多 A 记录里混一条 127.0.0.1 是常见绕过手法
  for (const { address, family } of addresses) {
    if (isPrivateAddress(address, family)) {
      return { ok: false, reason: `private address: ${bare} -> ${address}` };
    }
  }
  return { ok: true };
}
