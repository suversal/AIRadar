import type { ReactNode } from "react";
import { Mail } from "lucide-react";

import { StaticPage } from "@/components/static-page";

function GitHubLogo() {
  return (
    <svg aria-hidden className="h-5 w-5" viewBox="0 0 24 24">
      <path
        fill="currentColor"
        d="M12 .297a12 12 0 0 0-3.797 23.387c.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.387-1.333-1.756-1.333-1.756-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.762-1.605-2.665-.3-5.467-1.332-5.467-5.93 0-1.31.468-2.382 1.235-3.222-.123-.303-.535-1.523.117-3.176 0 0 1.008-.322 3.301 1.23A11.5 11.5 0 0 1 12 5.099c1.02.005 2.045.138 3.003.404 2.292-1.554 3.297-1.23 3.297-1.23.653 1.653.242 2.873.119 3.176.77.84 1.233 1.912 1.233 3.222 0 4.61-2.807 5.625-5.48 5.921.43.372.823 1.102.823 2.222 0 1.606-.015 2.896-.015 3.286 0 .319.216.694.825.576A12 12 0 0 0 12 .297Z"
      />
    </svg>
  );
}

function TelegramLogo() {
  return (
    <svg aria-hidden className="h-5 w-5" viewBox="0 0 24 24">
      <path
        fill="currentColor"
        d="M11.944 0A12 12 0 1 0 24 12 12.013 12.013 0 0 0 11.944 0Zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.96 6.502-1.357 8.627-.168.9-.499 1.201-.82 1.23-.696.064-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.479.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.324-.437.893-.663 3.498-1.524 5.831-2.529 6.998-3.014 3.332-1.386 4.024-1.627 4.476-1.635Z"
      />
    </svg>
  );
}

function XLogo() {
  return (
    <svg aria-hidden className="h-5 w-5" viewBox="0 0 24 24">
      <path
        fill="currentColor"
        d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231Zm-1.161 17.52h1.833L7.084 4.126H5.117Z"
      />
    </svg>
  );
}

function ContactLink({
  href,
  label,
  external = false,
  children,
}: {
  href: string;
  label: string;
  external?: boolean;
  children: ReactNode;
}) {
  return (
    <a
      aria-label={external ? `${label}（新窗口打开）` : label}
      className="inline-flex h-11 w-11 items-center justify-center border border-line bg-panel/45 text-ink-mid transition-colors hover:border-signal/60 hover:bg-signal/5 hover:text-signal focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal"
      href={href}
      rel={external ? "noreferrer" : undefined}
      target={external ? "_blank" : undefined}
      title={label}
    >
      {children}
    </a>
  );
}

export const metadata = {
  title: "关于",
  description: "AI·RADAR 是为创作者和开发者准备的 AI 情报雷达：监听数十个高信噪比信源，AI 评分聚类去重，每天一期精选日报。",
  alternates: { canonical: "/about" },
};

export default function AboutPage() {
  return (
    <StaticPage
      activeNavId="about"
      title="关于 AI·RADAR"
      subtitle="为创作者和开发者准备的 AI 情报雷达"
    >
      <section className="py-1">
        <p className="text-xs uppercase tracking-[0.3em] text-signal-dim">WHY AI·RADAR</p>
        <h2 className="editorial-rule-title mt-4 text-3xl font-medium leading-snug text-ink md:text-4xl">
          AI 圈子每天都在发生什么，
          <br />
          不该靠反复刷十几个信源才知道。
        </h2>
        <p className="mt-5 max-w-2xl text-sm leading-7 text-ink-mid">
          AI·RADAR 持续监听多个高信噪比信源——各大实验室官方博客、热门社区、X账号、微信公众号与中英文科技媒体。用 AI
          做相关性筛选、六维评分和同事件聚类，把同一件事在多个信源里的重复报道折叠成一条，
          每天沉淀为一期精选日报。
        </p>
        <nav aria-label="联系方式" className="mt-6 flex items-center gap-3">
          <ContactLink href="https://github.com/suversal/HotAI" label="GitHub" external>
            <GitHubLogo />
          </ContactLink>
          <ContactLink href="mailto:contact@suversal.com" label="发送邮件">
            <Mail aria-hidden className="h-5 w-5" strokeWidth={1.7} />
          </ContactLink>
          <ContactLink href="https://t.me/suversal" label="Telegram" external>
            <TelegramLogo />
          </ContactLink>
          <ContactLink href="https://x.com/suversal" label="X" external>
            <XLogo />
          </ContactLink>
        </nav>
      </section>

      <section className="border-l-2 border-signal py-1 pl-5 text-sm leading-7 text-ink-mid">
        <h2 className="text-base font-semibold text-signal-bright">评分与筛选口径</h2>
        <p className="mt-2">
          评分综合 AI 相关度、新颖性、影响力、信息密度、可操作性与创作者价值六个维度，
          并叠加信源权威度与时效衰减。只有跨过分类阈值的事件才会进入精选；其余动态全部保留在
          「全部 AI 动态」中可查，不会因为没入选就彻底消失。
        </p>
      </section>

      <section className="py-2">
        <h2 className="text-base font-semibold text-ink">数据口径</h2>
        <div className="mt-5 grid grid-cols-2 gap-y-6 sm:grid-cols-4 sm:divide-x sm:divide-line">
          {[
            { label: "抓取频率", value: "每 2 小时一轮" },
            { label: "精选标准", value: "评分过线即入选" },
            { label: "全量视野", value: "相关即收录，可查可搜" },
            { label: "主题体系", value: "公司模型 / 技术方向 / 内容形态" },
          ].map((stat) => (
            <div key={stat.label} className="px-3 py-4 text-center">
              <div className="readout text-sm font-semibold text-signal">{stat.value}</div>
              <div className="mt-1 text-xs text-ink-dim">{stat.label}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-panel/45 px-5 py-5 text-sm leading-7 text-ink-mid">
        <h2 className="text-base font-semibold text-signal-bright">免责声明</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5">
          <li>
            本站是聚合摘要与阅读索引：评分、分类、标签、中文摘要与翻译均由 AI
            自动生成，可能存在偏差或错误，不代表原作者或信源立场，仅供参考。
          </li>
          <li>
            原文版权归各来源方所有，本站不主张任何原创权利，每条内容都保留跳转阅读原文的入口。
          </li>
          <li>涉及融资、市场、行业数据等内容仅为信息摘录，不构成投资或其他决策建议。</li>
          <li>
            如果你是信源方，希望更正内容、下架收录或调整展示方式，欢迎通过
            <a className="mx-1 text-signal underline hover:text-signal-bright" href="/feedback">
              反馈页
            </a>
            联系我们。
          </li>
        </ul>
      </section>
    </StaticPage>
  );
}
