// Client-side only: there is no reader account system (public visitors are
// anonymous, only the admin has a token), so bookmarks live in this
// browser's localStorage. Only the event_id is stored - content is always
// resolved live when the bookmarks page loads, same "frozen selection, live
// content" principle used everywhere else on the site.

const STORAGE_KEY = "airadar:bookmarks";

type BookmarkEntry = { eventId: string; bookmarkedAt: string };

function readAll(): BookmarkEntry[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(
      (entry): entry is BookmarkEntry =>
        Boolean(entry) && typeof entry.eventId === "string" && typeof entry.bookmarkedAt === "string",
    );
  } catch {
    return [];
  }
}

function writeAll(entries: BookmarkEntry[]) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
}

export function getBookmarkIds(): string[] {
  return readAll()
    .sort((a, b) => b.bookmarkedAt.localeCompare(a.bookmarkedAt))
    .map((entry) => entry.eventId);
}

export function isBookmarked(eventId: string): boolean {
  return readAll().some((entry) => entry.eventId === eventId);
}

export function addBookmark(eventId: string) {
  const entries = readAll();
  if (entries.some((entry) => entry.eventId === eventId)) {
    return;
  }
  writeAll([...entries, { eventId, bookmarkedAt: new Date().toISOString() }]);
}

export function removeBookmark(eventId: string) {
  writeAll(readAll().filter((entry) => entry.eventId !== eventId));
}

/** Toggles the bookmark and returns the new state. */
export function toggleBookmark(eventId: string): boolean {
  if (isBookmarked(eventId)) {
    removeBookmark(eventId);
    return false;
  }
  addBookmark(eventId);
  return true;
}
