export type ResolvedTheme = "dark" | "light";

export const THEME_COLOR_META_ID = "ai-radar-theme-color";
export const DARK_THEME_CHROME_COLOR = "#262624";
export const LIGHT_THEME_CHROME_COLOR = "#faf7ee";

export function syncThemeChrome(theme: ResolvedTheme) {
  const root = document.documentElement;
  const color = theme === "light" ? LIGHT_THEME_CHROME_COLOR : DARK_THEME_CHROME_COLOR;
  const existing = Array.from(
    document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'),
  );
  let meta = document.getElementById(THEME_COLOR_META_ID) as HTMLMetaElement | null;

  if (!meta) {
    meta = existing[0] ?? document.createElement("meta");
    meta.id = THEME_COLOR_META_ID;
    meta.name = "theme-color";
    if (!meta.isConnected) {
      document.head.append(meta);
    }
  }

  for (const duplicate of existing) {
    if (duplicate !== meta) {
      duplicate.remove();
    }
  }

  meta.content = color;
  root.style.backgroundColor = color;
  root.style.colorScheme = theme;
}
