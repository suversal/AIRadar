import { FEED_LIMIT, respondWithItemsFeed } from "@/lib/feed/load";

// 与 lib/taxonomy 的 DISPLAY_CATEGORIES 一致。写死一份是为了让未知分类
// 直接 404，而不是转成一个空 feed——空 feed 会被订阅者当成"这个分类今天
// 没内容"，而不是"你订阅的地址拼错了"。
const CATEGORY_LABELS: Record<string, string> = {
  model: "模型",
  product: "产品",
  industry: "行业",
  research: "论文",
  tutorial: "技巧",
};

/** 分类订阅：/feed/category/{model|product|industry|research|tutorial}.xml */
export async function GET(
  request: Request,
  context: { params: Promise<{ slug: string }> },
) {
  const { slug } = await context.params;
  // 路由段带着 .xml 后缀进来（是地址的一部分，不是查询参数）
  const category = slug.replace(/\.xml$/, "");
  // Object.hasOwn：直接取值会命中 Object.prototype，/feed/category/__proto__.xml
  // 因此绕过 404 守卫，产出一个标题为 "[object Object]" 的 feed，
  // 还会把 category=__proto__ 原样发给上游。
  const label = Object.hasOwn(CATEGORY_LABELS, category)
    ? CATEGORY_LABELS[category]
    : undefined;

  if (!label) {
    return new Response(
      `没有这个分类：${category}。可用分类：${Object.keys(CATEGORY_LABELS).join("、")}。`,
      { status: 404, headers: { "Cache-Control": "no-store" } },
    );
  }

  return respondWithItemsFeed(
    request,
    {
      title: `AI·RADAR 精选 · ${label}`,
      description: `AI·RADAR 精选中归入「${label}」分类的条目，含中文摘要与推荐理由。`,
      selfPath: `/feed/category/${category}.xml`,
      sitePath: `/latest?category=${category}`,
    },
    `/api/public/latest?limit=${FEED_LIMIT}&category=${encodeURIComponent(category)}`,
  );
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
