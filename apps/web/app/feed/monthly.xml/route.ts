import { renderPeriodFeed } from "@/lib/feed/period";

export function GET(request: Request) {
  return renderPeriodFeed(request, "monthly");
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
