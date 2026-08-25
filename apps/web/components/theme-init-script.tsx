import {
  DEFAULT_DARK_CHROME_COLOR,
  DEFAULT_LIGHT_CHROME_COLOR,
  EDITORIAL_DARK_CHROME_COLOR,
  EDITORIAL_LIGHT_CHROME_COLOR,
  EDITORIAL_THEME_PATHS,
  THEME_COLOR_META_ID,
} from "./theme-chrome";
import {
  COLOR_PALETTES,
  DEFAULT_COLOR_PALETTE,
  PALETTE_CANVAS_COLORS,
  PALETTE_STORAGE_KEY,
} from "./theme-config";

// Runs synchronously before the rest of <body> paints, so a visitor who
// already chose "light" (or whose system is light and preference is
// "system"/unset) never sees a flash of the dark theme first. Mirrors the
// resolution logic in theme-toggle.tsx - keep the two in sync.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    var pref = localStorage.getItem("ai-radar-theme");
    var storedPalette = localStorage.getItem(${JSON.stringify(PALETTE_STORAGE_KEY)});
    var palettes = ${JSON.stringify(COLOR_PALETTES.map((option) => option.value))};
    var palette = palettes.indexOf(storedPalette) !== -1
      ? storedPalette
      : ${JSON.stringify(DEFAULT_COLOR_PALETTE)};
    document.documentElement.setAttribute("data-palette", palette);
    var light = pref === "light" || (pref !== "dark" && window.matchMedia("(prefers-color-scheme: light)").matches);
    if (light) {
      document.documentElement.setAttribute("data-theme", "light");
    }
    var pathname = window.location.pathname;
    var editorialPaths = ${JSON.stringify(EDITORIAL_THEME_PATHS)};
    var editorial = editorialPaths.some(function (path) {
      return pathname === path || pathname.indexOf(path + "/") === 0;
    });
    var theme = light ? "light" : "dark";
    var paletteCanvasColors = ${JSON.stringify(PALETTE_CANVAS_COLORS)};
    var paletteCanvas = palette && paletteCanvasColors[palette];
    var color = paletteCanvas
      ? paletteCanvas[theme]
      : (light
        ? (editorial ? ${JSON.stringify(EDITORIAL_LIGHT_CHROME_COLOR)} : ${JSON.stringify(DEFAULT_LIGHT_CHROME_COLOR)})
        : (editorial ? ${JSON.stringify(EDITORIAL_DARK_CHROME_COLOR)} : ${JSON.stringify(DEFAULT_DARK_CHROME_COLOR)}));
    var metas = document.querySelectorAll('meta[name="theme-color"]');
    var meta = document.getElementById(${JSON.stringify(THEME_COLOR_META_ID)});
    if (!meta) {
      meta = metas[0] || document.createElement("meta");
      meta.id = ${JSON.stringify(THEME_COLOR_META_ID)};
      meta.setAttribute("name", "theme-color");
      if (!meta.isConnected) document.head.appendChild(meta);
    }
    for (var i = 0; i < metas.length; i += 1) {
      if (metas[i] !== meta) metas[i].remove();
    }
    meta.removeAttribute("media");
    meta.setAttribute("content", color);
    document.documentElement.style.backgroundColor = color;
    if (editorial) {
      document.documentElement.style.setProperty("--color-canvas", color);
    } else {
      document.documentElement.style.removeProperty("--color-canvas");
    }
    document.documentElement.style.colorScheme = theme;
  } catch (e) {}
})();
`;

export function ThemeInitScript() {
  return <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />;
}
