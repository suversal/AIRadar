/** 查询参数里数值的收敛。
 *
 *  这些 route handler 原先写的是 `Number(x) || 50`，有两个问题：
 *
 *  1. `Number("abc")` 是 NaN、`Number("")` 是 0，`|| 50` 会把它们**静默**变成 50，
 *     `?limit=0` 也一样——看起来是"有兜底"，其实是把错误藏起来了。
 *  2. 超大值原样透传给后端。后端本身是有上限校验的（会返回 400），
 *     但 lib/api.ts 在响应非 2xx 时返回的是一个空 payload，
 *     于是 `?limit=1000` 的实际效果变成**页面正常渲染但一条内容都没有**。
 *     排查这种"没报错但没数据"的问题非常费劲。
 *
 *  所以在这一层就夹紧：越界的值收敛到合法区间，行为可预期，
 *  也不会把一个畸形参数变成一次后端 400。上限与
 *  apps/api/app/main.py 里各公开端点的校验保持一致。 */

export function clampInt(
  raw: string | null,
  { fallback, min, max }: { fallback: number; min: number; max: number },
): number {
  if (raw === null || raw.trim() === "") {
    return fallback;
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

/** 与后端 `limit must be between 1 and 200` 对齐 */
export const LIMIT_BOUNDS = { fallback: 50, min: 1, max: 200 } as const;
/** 与后端 `days must be between 1 and 90` 对齐 */
export const DAYS_BOUNDS = { fallback: 30, min: 1, max: 90 } as const;
/** 后端只要求非负；上限是这一层加的，翻到 10 万条之后没有任何真实用途 */
export const OFFSET_BOUNDS = { fallback: 0, min: 0, max: 100_000 } as const;
