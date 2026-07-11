import { StaticPage } from "@/components/static-page";

export const metadata = {
  title: "更新日志 · AI·RADAR",
};

const entries = [
  {
    date: "2026-07-11",
    title: "周报/月报数据修复、收藏功能与图标导航",
    items: [
      "周报/月报改为严格基于当期已发布日报聚合，评分过但从未入选任何一天日报的动态不再混入统计和看点",
      "周报/月报新增事件与统计快照，多来源事件角标终于能在周报/月报页面显示",
      "AI 主线综述从占位文案换成约 400 字的真实综述、按主题分段落展示",
      "「本期看点」改为点击后平滑滚动到对应主题区块，不再跳去某一篇文章详情",
      "精选页的事件计数会随分类筛选正确变化，此前筛选后仍显示全量数字",
      "上线收藏功能：点击收藏图标即可保存到本机浏览器，专属收藏页随时查看、可取消",
      "左侧菜单改用图标呈现",
      "日报选取改为不设固定条数上限，由信任来源或评分阈值共同决定，标题去重规则修复了带连字符模型名（如 GLM-5.2）被误判成站名后缀的问题",
    ],
  },
  {
    date: "2026-07-10",
    title: "琥珀信号视觉体系与主题页",
    items: [
      "全新 AI·RADAR 视觉识别：暖炭黑底、琥珀信号主色、等宽仪表读数",
      "主题页上线：公司与模型 / 技术方向 / 内容形态 三组主题可点击筛选",
      "分类标准统一为 全部/模型/产品/行业/论文/技巧 六类",
      "Agent 接入、关于、更新日志、反馈页面上线",
    ],
  },
  {
    date: "2026-07-09",
    title: "全量事件流与数据底座",
    items: [
      "「全部 AI 动态」接入真实全量事件 API，未入选精选的动态也可浏览",
      "周报/月报按真实日期区间聚合",
      "事件 ID 稳定化：收藏与分享链接不再因日报重建而失效",
      "抓取提速：27 个信源并行抓取，整轮约 25 秒",
      "英文精选文章的中文翻译稳定性修复",
    ],
  },
  {
    date: "2026-07-08",
    title: "首个可用版本",
    items: [
      "27 个高信噪比信源接入（官方博客 / arXiv / GitHub / 社区 / 中文媒体）",
      "AI 预筛、六维评分、每日 12 条精选日报",
      "精选、全部动态、日报、事件详情、搜索页面",
    ],
  },
];

export default function ChangelogPage() {
  return (
    <StaticPage
      activeNavId="changelog"
      title="更新日志"
      subtitle="产品能力的演进记录"
    >
      {entries.map((entry) => (
        <section key={entry.date} className="rounded-md border border-line bg-panel p-5">
          <div className="flex flex-wrap items-baseline gap-3">
            <span className="readout text-sm text-signal">{entry.date}</span>
            <h2 className="text-lg font-semibold text-ink">{entry.title}</h2>
          </div>
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm leading-6 text-ink-mid">
            {entry.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ))}
    </StaticPage>
  );
}
