import { notFound } from "next/navigation";

import { getTweet } from "@/lib/api";
import { MobileNav } from "@/components/mobile-nav";
import { Sidebar } from "@/components/sidebar";
import { TweetCard } from "@/components/tweet-card";

// 单条推文详情：列表对长内容只出标题与摘要，全文在这里看。

export const metadata = {
  title: "推文详情",
};

export default async function TweetDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const tweet = await getTweet(id);
  if (!tweet) {
    notFound();
  }

  return (
    <main className="editorial-page min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[248px_1fr]">
        <Sidebar activeNavId="x" />
        <MobileNav activeNavId="x" />

        <section className="px-4 pb-8 pt-4 md:px-8 md:py-10 xl:px-12">
          <div className="mx-auto max-w-4xl">
            <a
              className="mb-3 inline-block text-sm font-medium text-signal hover:text-signal-bright"
              href="/x"
            >
              ← 返回推文列表
            </a>
            <TweetCard detail tweet={tweet} />
          </div>
        </section>
      </div>
    </main>
  );
}
