// Runs synchronously before the rest of <body> paints, so a visitor who
// already chose "light" (or whose system is light and preference is
// "system"/unset) never sees a flash of the dark theme first. Mirrors the
// resolution logic in theme-toggle.tsx - keep the two in sync.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    var pref = localStorage.getItem("ai-radar-theme");
    var light = pref === "light" || (pref !== "dark" && window.matchMedia("(prefers-color-scheme: light)").matches);
    if (light) {
      document.documentElement.setAttribute("data-theme", "light");
    }
  } catch (e) {}
})();
`;

export function ThemeInitScript() {
  return <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />;
}
