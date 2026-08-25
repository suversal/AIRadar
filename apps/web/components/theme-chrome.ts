import {
  DEFAULT_COLOR_PALETTE,
  isColorPalette,
  PALETTE_CANVAS_COLORS,
  type ColorPalette,
} from "./theme-config";

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

export function themeChromeColor(
  theme: ResolvedTheme,
  pathname: string,
  palette: ColorPalette = DEFAULT_COLOR_PALETTE,
) {
  if (palette !== "original") {
    return PALETTE_CANVAS_COLORS[palette][theme];
  }
  if (isEditorialPath(pathname)) {
    return theme === "light" ? EDITORIAL_LIGHT_CHROME_COLOR : EDITORIAL_DARK_CHROME_COLOR;
  }
  return theme === "light" ? DEFAULT_LIGHT_CHROME_COLOR : DEFAULT_DARK_CHROME_COLOR;
}

export function syncThemeChrome(theme: ResolvedTheme) {
  const root = document.documentElement;
  const pathname = window.location.pathname;
  const editorial = isEditorialPath(pathname);
  const paletteAttribute = root.getAttribute("data-palette");
  const palette = isColorPalette(paletteAttribute) ? paletteAttribute : DEFAULT_COLOR_PALETTE;
  const color = themeChromeColor(theme, pathname, palette);
  const existing = Array.from(
    document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'),
  );
  const previousMeta =
    (document.getElementById(THEME_COLOR_META_ID) as HTMLMetaElement | null) ?? existing[0];

  for (const duplicate of existing) {
    if (duplicate !== previousMeta) duplicate.remove();
  }

  // Mobile Safari can keep using the old browser-chrome color when only the
  // content attribute is mutated. Replacing the node makes it resample the
  // active theme immediately instead of waiting for a page refresh.
  const nextMeta = document.createElement("meta");
  nextMeta.id = THEME_COLOR_META_ID;
  nextMeta.name = "theme-color";
  nextMeta.removeAttribute("media");
  nextMeta.content = color;
  if (previousMeta?.isConnected) {
    previousMeta.replaceWith(nextMeta);
  } else {
    document.head.append(nextMeta);
  }

  root.style.backgroundColor = color;
  if (document.body) {
    document.body.style.backgroundColor = color;
  }
  if (editorial) {
    root.style.setProperty("--color-canvas", color);
  } else {
    root.style.removeProperty("--color-canvas");
  }
  root.style.colorScheme = theme;
}
