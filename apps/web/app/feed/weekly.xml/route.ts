import { renderPeriodFeed } from "@/lib/feed/period";

export function GET(request: Request) {
  return renderPeriodFeed(request, "weekly");
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
