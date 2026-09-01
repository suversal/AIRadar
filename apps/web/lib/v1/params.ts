// v1 的查询参数校验。
//
// 原则是"越界报错，不静默放宽"：limit=500 返回 400，而不是悄悄给 100。
// 客户端拿到一页 100 条却以为自己要到了 500 条，是最难查的那类 bug——
// 它不报错，只是数据少了。
//
// 未声明的参数同样 400。代价是 ?utm_source= 这类会被拒，收益是 cache-buster
// 和拼错的参数名（?limits=10 被当成没传）都会在第一次调用就暴露出来。

import { badRequest } from "./http";

/**
 * 未声明参数与重复参数一律 400。
 *
 * 重复参数必须拦：URLSearchParams.get 只返回第一个，?limit=1&limit=100
 * 在服务端是 1、在客户端作者眼里是 100，两边永远对不上。
 */
export function assertKnownParams(url: URL, allowed: readonly string[]): void {
  const seen = new Set<string>();
  for (const key of url.searchParams.keys()) {
    if (!allowed.includes(key)) {
      throw badRequest(
        "unknown_parameter",
        `不支持的参数 "${key}"。该端点只接受：${allowed.join("、") || "（无参数）"}。请移除 cache-buster 与未声明参数。`,
      );
    }
    if (seen.has(key)) {
      throw badRequest(
        "duplicate_parameter",
        `参数 "${key}" 重复出现。每个参数只能传一次。`,
      );
    }
    seen.add(key);
  }
}

export function intParam(
  url: URL,
  name: string,
  options: { min: number; max: number; fallback: number },
): number {
  const raw = url.searchParams.get(name);
  if (raw === null || raw === "") {
    return options.fallback;
  }
  // Number("") 是 0、Number(" 1 ") 是 1，都不是想要的宽松；只认纯整数。
  if (!/^-?\d+$/.test(raw.trim())) {
    throw badRequest("invalid_parameter", `${name} 必须是整数，收到 "${raw}"。`);
  }
  const value = Number.parseInt(raw.trim(), 10);
  if (value < options.min || value > options.max) {
    throw badRequest(
      "invalid_parameter",
      `${name} 必须在 ${options.min} 到 ${options.max} 之间，收到 ${value}。接口不会自动改成边界值。`,
    );
  }
  return value;
}

export function enumParam<T extends string>(
  url: URL,
  name: string,
  values: readonly T[],
  fallback: T,
): T;
export function enumParam<T extends string>(
  url: URL,
  name: string,
  values: readonly T[],
  fallback: undefined,
): T | undefined;
export function enumParam<T extends string>(
  url: URL,
  name: string,
  values: readonly T[],
  fallback: T | undefined,
): T | undefined {
  const raw = url.searchParams.get(name);
  if (raw === null || raw === "") {
    return fallback;
  }
  if (!(values as readonly string[]).includes(raw)) {
    throw badRequest(
      "invalid_parameter",
      `${name} 只能是 ${values.join(" | ")}，收到 "${raw}"。`,
    );
  }
  return raw as T;
}

export function textParam(
  url: URL,
  name: string,
  options: { minLength: number; maxLength: number },
): string | undefined {
  const raw = url.searchParams.get(name);
  if (raw === null) {
    return undefined;
  }
  const value = raw.trim();
  if (value === "") {
    return undefined;
  }
  if (value.length < options.minLength || value.length > options.maxLength) {
    throw badRequest(
      "invalid_parameter",
      `${name} 长度必须在 ${options.minLength} 到 ${options.maxLength} 字之间，收到 ${value.length} 字。`,
    );
  }
  return value;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** 日历日（上海时区口径，与日报期次一致）。 */
export function assertIsoDate(value: string, name = "date"): string {
  if (!ISO_DATE.test(value)) {
    throw badRequest("invalid_parameter", `${name} 必须是 YYYY-MM-DD，收到 "${value}"。`);
  }
  // 正则拦不住 2026-02-31：Date 会把它滚到 3 月 3 日，回读就对不上了。
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    throw badRequest("invalid_parameter", `${name} 不是有效日期：${value}。`);
  }
  return value;
}

const WEEKLY_KEY = /^(\d{4})-W(\d{2})$/;
const MONTHLY_KEY = /^(\d{4})-(\d{2})$/;

/** ISO 周期 key。周报用 YYYY-Www，月报用 YYYY-MM。 */
export function assertPeriodKey(value: string, kind: "weekly" | "monthly"): string {
  if (kind === "monthly") {
    const match = MONTHLY_KEY.exec(value);
    const month = match ? Number.parseInt(match[2], 10) : 0;
    if (!match || month < 1 || month > 12) {
      throw badRequest("invalid_parameter", `key 必须是有效的 YYYY-MM，收到 "${value}"。`);
    }
    return value;
  }

  const match = WEEKLY_KEY.exec(value);
  const week = match ? Number.parseInt(match[2], 10) : 0;
  if (!match || week < 1 || week > 53) {
    throw badRequest("invalid_parameter", `key 必须是有效的 YYYY-Www，收到 "${value}"。`);
  }

  // ISO 年最后一周一定包含 12 月 28 日。算出那天的周数，拦住没有 W53 的年份。
  const year = Number.parseInt(match[1], 10);
  const dec28 = new Date(Date.UTC(year, 11, 28));
  const day = dec28.getUTCDay() || 7;
  dec28.setUTCDate(dec28.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(dec28.getUTCFullYear(), 0, 1));
  const lastWeek = Math.ceil(((dec28.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7);
  if (week > lastWeek) {
    throw badRequest("invalid_parameter", `${year} 年没有第 ${week} 个 ISO 周。`);
  }
  return value;
}
