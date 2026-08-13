// 站点对外地址。分享卡片、canonical、sitemap 都需要绝对 URL，
// 没有 metadataBase 时 Next 只能输出相对路径，社交平台抓不到图。
// 用环境变量兜底是为了本地开发和备用机器（腾讯云）也能生成正确链接。
//
// 单独放一个模块而不是从 layout.tsx 导出：Next 对 layout/page 这类
// 特殊文件的导出名有约定（metadata / viewport / default …），
// 混进普通导出容易在后续版本里踩坑。
export const siteUrl = process.env.SITE_URL ?? "https://radar.suversal.com";

export const siteTitle = "AI·RADAR — 为创作者和开发者准备的 AI 情报雷达";

export const siteDescription =
  "持续监听数十个高信噪比 AI 信源，用 AI 评分、聚类、去重，每天沉淀一期精选日报。为创作者和开发者准备的 AI 情报雷达。";
