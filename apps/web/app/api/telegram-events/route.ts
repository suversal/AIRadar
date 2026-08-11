import { getTelegramEvents } from "@/lib/api";

/** Server-side proxy used by the Telegram feed's infinite-scroll client. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const days = Number(url.searchParams.get("days") ?? "30") || 30;
  const limit = Number(url.searchParams.get("limit") ?? "50") || 50;
  const offset = Number(url.searchParams.get("offset") ?? "0") || 0;
  const channel = url.searchParams.get("channel") ?? undefined;

  const payload = await getTelegramEvents({ days, limit, offset, channel });
  return Response.json(payload);
}
