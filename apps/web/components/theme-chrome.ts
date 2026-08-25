export type ResolvedTheme = "dark" | "light";

export const THEME_COLOR_META_ID = "ai-radar-theme-color";
export const DEFAULT_DARK_CHROME_COLOR = "#1f1e1d";
export const DEFAULT_LIGHT_CHROME_COLOR = "#f3efe4";
export const EDITORIAL_DARK_CHROME_COLOR = "#181815";
export const EDITORIAL_LIGHT_CHROME_COLOR = "#eee9dc";

export const EDITORIAL_THEME_PATHS = [
  "/about",
  "/agent",
  "/latest",
  "/all",
  "/bookmarks",
  "/changelog",
  "/daily",
  "/event",
  "/feedback",
  "/monthly",
  "/telegram",
  "/topics",
  "/weekly",
  "/x",
] as const;

export function isEditorialPath(pathname: string) {
  return EDITORIAL_THEME_PATHS.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );
}

export function themeChromeColor(theme: ResolvedTheme, pathname: string) {
  if (isEditorialPath(pathname)) {
    return theme === "light" ? EDITORIAL_LIGHT_CHROME_COLOR : EDITORIAL_DARK_CHROME_COLOR;
  }
  return theme === "light" ? DEFAULT_LIGHT_CHROME_COLOR : DEFAULT_DARK_CHROME_COLOR;
}

export function syncThemeChrome(theme: ResolvedTheme) {
  const root = document.documentElement;
  const pathname = window.location.pathname;
  const editorial = isEditorialPath(pathname);
  const color = themeChromeColor(theme, pathname);
  const existing = Array.from(
    document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'),
  );
  let meta = document.getElementById(THEME_COLOR_META_ID) as HTMLMetaElement | null;

  if (!meta) {
    meta = existing[0] ?? document.createElement("meta");
    meta.id = THEME_COLOR_META_ID;
    meta.name = "theme-color";
    if (!meta.isConnected) document.head.append(meta);
  }

  for (const duplicate of existing) {
    if (duplicate !== meta) duplicate.remove();
  }

  meta.removeAttribute("media");
  meta.content = color;
  root.style.backgroundColor = color;
  if (editorial) {
    root.style.setProperty("--color-canvas", color);
  } else {
    root.style.removeProperty("--color-canvas");
  }
  root.style.colorScheme = theme;
}
