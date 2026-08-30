"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Moon, Monitor, Sun } from "lucide-react";
import {
  COLOR_PALETTES,
  DEFAULT_COLOR_PALETTE,
  isColorPalette,
  PALETTE_STORAGE_KEY,
  THEME_STORAGE_KEY,
  type ColorPalette,
  type ThemePreference,
} from "./theme-config";
import { syncThemeChrome, type ResolvedTheme } from "./theme-chrome";

const OPTIONS: { value: ThemePreference; icon: typeof Moon; label: string }[] = [
  { value: "dark", icon: Moon, label: "夜间" },
  { value: "system", icon: Monitor, label: "跟随系统" },
  { value: "light", icon: Sun, label: "日间" },
];

const TRANSITION_MS = 350;
const THEME_SETTINGS_CHANGE_EVENT = "ai-radar:theme-settings-change";

type ThemeSettingsChange = {
  preference?: ThemePreference;
  palette?: ColorPalette;
};

function broadcastThemeSettings(detail: ThemeSettingsChange) {
  window.dispatchEvent(
    new CustomEvent<ThemeSettingsChange>(THEME_SETTINGS_CHANGE_EVENT, { detail }),
  );
}

function systemPrefersLight() {
  return window.matchMedia("(prefers-color-scheme: light)").matches;
}

function applyResolvedTheme(preference: ThemePreference, { withTransition = false } = {}) {
  const root = document.documentElement;
  // scoped to a class instead of a permanent global transition, and only
  // added for an actual switch - not the initial mount sync, which just
  // re-confirms whatever the blocking init script already painted and
  // must stay instant (fading "into" the already-correct theme on first
  // load would look like a flash of the wrong one)
  if (withTransition) {
    root.classList.add("theme-transition");
    window.setTimeout(() => root.classList.remove("theme-transition"), TRANSITION_MS);
  }
  const resolved: ResolvedTheme =
    preference === "system" ? (systemPrefersLight() ? "light" : "dark") : preference;
  if (resolved === "light") {
    root.setAttribute("data-theme", "light");
  } else {
    root.removeAttribute("data-theme");
  }
  syncThemeChrome(resolved);
}

function applyColorPalette(palette: ColorPalette, { withTransition = false } = {}) {
  const root = document.documentElement;
  if (withTransition) {
    root.classList.add("theme-transition");
    window.setTimeout(() => root.classList.remove("theme-transition"), TRANSITION_MS);
  }
  // Keep every selection explicit. An absent attribute now means the default
  // instrument palette, while `original` must remain distinguishable so the
  // browser chrome can return to the classic canvas color immediately.
  root.setAttribute("data-palette", palette);
  const resolved: ResolvedTheme = root.getAttribute("data-theme") === "light" ? "light" : "dark";
  syncThemeChrome(resolved);
}

export function ThemeToggle() {
  // defaults to "system" so a first-time visitor (or one who already chose
  // "system") sees the toggle in the same state the blocking init script
  // already resolved - only corrected on mount if localStorage says otherwise
  const [preference, setPreference] = useState<ThemePreference>("system");
  const [palette, setPalette] = useState<ColorPalette>(DEFAULT_COLOR_PALETTE);
  const themeMounted = useRef(false);
  const paletteMounted = useRef(false);
  const initialPalette = useRef<ColorPalette | null>(null);
  const [expanded, setExpanded] = useState<"mode" | "palette" | null>(null);
  const settingsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "dark" || stored === "system" || stored === "light") {
      setPreference(stored);
    }
    const storedPalette = localStorage.getItem(PALETTE_STORAGE_KEY);
    if (isColorPalette(storedPalette)) {
      initialPalette.current = storedPalette;
      setPalette(storedPalette);
    } else {
      initialPalette.current = DEFAULT_COLOR_PALETTE;
    }
  }, []);

  useEffect(() => {
    function onThemeSettingsChange(event: Event) {
      const detail = (event as CustomEvent<ThemeSettingsChange>).detail;
      if (detail.preference) setPreference(detail.preference);
      if (detail.palette) setPalette(detail.palette);
    }

    window.addEventListener(THEME_SETTINGS_CHANGE_EVENT, onThemeSettingsChange);
    return () => window.removeEventListener(THEME_SETTINGS_CHANGE_EVENT, onThemeSettingsChange);
  }, []);

  useEffect(() => {
    applyResolvedTheme(preference, { withTransition: themeMounted.current });
    themeMounted.current = true;
    if (preference !== "system") {
      return;
    }
    const mql = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => applyResolvedTheme("system", { withTransition: true });
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [preference]);

  useEffect(() => {
    const firstPaintPalette = initialPalette.current ?? palette;
    applyColorPalette(paletteMounted.current ? palette : firstPaintPalette, {
      withTransition: paletteMounted.current && palette !== firstPaintPalette,
    });
    paletteMounted.current = true;
  }, [palette]);

  useEffect(() => {
    if (expanded === null) return;

    function onPointerDown(event: PointerEvent) {
      if (!settingsRef.current?.contains(event.target as Node)) setExpanded(null);
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setExpanded(null);
    }

    document.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [expanded]);

  function choose(next: ThemePreference) {
    setPreference(next);
    setExpanded(null);
    localStorage.setItem(THEME_STORAGE_KEY, next);
    broadcastThemeSettings({ preference: next });
  }

  function choosePalette(next: ColorPalette) {
    setPalette(next);
    setExpanded(null);
    localStorage.setItem(PALETTE_STORAGE_KEY, next);
    broadcastThemeSettings({ palette: next });
  }

  return (
    <div
      ref={settingsRef}
      className="theme-toggle fixed z-20 hidden items-center gap-1 rounded-full border border-line-strong bg-panel/85 p-1 backdrop-blur-md lg:flex"
      style={{ bottom: "100px", left: "124px", transform: "translateX(-50%)" }}
    >
      <div
        aria-label="明暗主题"
        className={`desktop-theme-options flex items-center ${expanded === "mode" ? "gap-1" : "gap-0"}`}
        role={expanded === "mode" ? "radiogroup" : undefined}
      >
        {OPTIONS.map(({ value, icon: Icon, label }, index) => {
          const active = preference === value;
          const visible = expanded === "mode" || active;
          const motionDelay = (expanded === "mode" ? index : OPTIONS.length - 1 - index) * 30;
          return (
            <button
              key={value}
              type="button"
              role={expanded === "mode" ? "radio" : undefined}
              aria-checked={expanded === "mode" ? active : undefined}
              aria-hidden={!visible}
              aria-label={
                expanded === "mode"
                  ? label
                  : `当前明暗主题：${
                      OPTIONS.find((option) => option.value === preference)?.label ?? "跟随系统"
                    }，展开外观设置`
              }
              title={label}
              tabIndex={visible ? 0 : -1}
              onClick={() => {
                if (expanded !== "mode") {
                  setExpanded("mode");
                  return;
                }
                choose(value);
              }}
              style={{ transitionDelay: `${motionDelay}ms, ${motionDelay}ms, ${motionDelay}ms, 0ms, 0ms` }}
              className={`desktop-theme-option flex h-9 shrink-0 items-center justify-center overflow-hidden rounded-full ${
                visible ? "w-9 scale-100 opacity-100" : "pointer-events-none w-0 scale-90 opacity-0"
              } ${active ? "bg-signal text-canvas" : "text-ink-mid hover:bg-panel-soft hover:text-ink"}
              `}
            >
              <Icon aria-hidden className="h-4 w-4" strokeWidth={2} />
            </button>
          );
        })}
      </div>

      <span aria-hidden className="h-5 w-px shrink-0 bg-line" />

      <div
        aria-label="主题色"
        className={`desktop-theme-options flex items-center ${expanded === "palette" ? "gap-1" : "gap-0"}`}
        role={expanded === "palette" ? "radiogroup" : undefined}
      >
        {COLOR_PALETTES.map(({ value, label, swatch }, index) => {
          const active = palette === value;
          const visible = expanded === "palette" || active;
          const motionDelay =
            (expanded === "palette" ? index : COLOR_PALETTES.length - 1 - index) * 30;
          return (
            <button
              key={value}
              type="button"
              role={expanded === "palette" ? "radio" : undefined}
              aria-checked={expanded === "palette" ? active : undefined}
              aria-hidden={!visible}
              aria-label={
                expanded === "palette"
                  ? label
                  : `当前主题色：${
                      COLOR_PALETTES.find((option) => option.value === palette)?.label ?? "信号绿"
                    }，展开外观设置`
              }
              title={label}
              tabIndex={visible ? 0 : -1}
              onClick={() => {
                if (expanded !== "palette") {
                  setExpanded("palette");
                  return;
                }
                choosePalette(value);
              }}
              style={{ transitionDelay: `${motionDelay}ms, ${motionDelay}ms, ${motionDelay}ms, 0ms, 0ms` }}
              className={`desktop-theme-option flex h-9 shrink-0 items-center justify-center overflow-hidden rounded-full ${
                visible ? "w-9 scale-100 opacity-100" : "pointer-events-none w-0 scale-90 opacity-0"
              } ${active ? "bg-panel-soft" : "hover:bg-panel-soft"}`}
            >
              <span
                aria-hidden
                className="h-4 w-4 rounded-full border border-line-strong"
                style={{ backgroundColor: swatch }}
              />
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function MobileThemeSettings() {
  const [preference, setPreference] = useState<ThemePreference>("system");
  const [palette, setPalette] = useState<ColorPalette>(DEFAULT_COLOR_PALETTE);
  const [expanded, setExpanded] = useState<"mode" | "palette" | null>(null);
  const settingsRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    if (storedTheme === "dark" || storedTheme === "system" || storedTheme === "light") {
      setPreference(storedTheme);
    }
    const storedPalette = localStorage.getItem(PALETTE_STORAGE_KEY);
    if (isColorPalette(storedPalette)) setPalette(storedPalette);

    function onThemeSettingsChange(event: Event) {
      const detail = (event as CustomEvent<ThemeSettingsChange>).detail;
      if (detail.preference) setPreference(detail.preference);
      if (detail.palette) setPalette(detail.palette);
    }

    window.addEventListener(THEME_SETTINGS_CHANGE_EVENT, onThemeSettingsChange);
    return () => window.removeEventListener(THEME_SETTINGS_CHANGE_EVENT, onThemeSettingsChange);
  }, []);

  useEffect(() => {
    if (expanded === null) return;

    function onPointerDown(event: PointerEvent) {
      if (!settingsRef.current?.contains(event.target as Node)) setExpanded(null);
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setExpanded(null);
    }

    document.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [expanded]);

  function choose(next: ThemePreference) {
    setPreference(next);
    setExpanded(null);
    localStorage.setItem(THEME_STORAGE_KEY, next);
    broadcastThemeSettings({ preference: next });
  }

  function choosePalette(next: ColorPalette) {
    setPalette(next);
    setExpanded(null);
    localStorage.setItem(PALETTE_STORAGE_KEY, next);
    broadcastThemeSettings({ palette: next });
  }

  const activeOption = OPTIONS.find((option) => option.value === preference) ?? OPTIONS[1];
  const activePalette =
    COLOR_PALETTES.find((option) => option.value === palette) ?? COLOR_PALETTES[0];

  return (
    <section ref={settingsRef} aria-label="外观设置" className="border-t border-line pt-3">
      <div className="px-1">
        <div className="flex items-baseline gap-2">
          <span className="readout text-[9px] font-semibold uppercase tracking-[0.16em] text-ink-dim">
            外观
          </span>
          <span className="text-[10px] text-ink-dim">
            {activeOption.label} · {activePalette.label}
          </span>
        </div>

        <div className="mt-2 flex w-fit max-w-full items-center gap-1 rounded-full border border-line bg-panel/70 p-1">
          <div
            aria-label="明暗主题"
            className={`drawer-theme-options flex items-center ${expanded === "mode" ? "gap-1" : "gap-0"}`}
            role={expanded === "mode" ? "radiogroup" : undefined}
          >
            {OPTIONS.map(({ value, icon: Icon, label }, index) => {
              const active = preference === value;
              const visible = expanded === "mode" || active;
              const motionDelay = (expanded === "mode" ? index : OPTIONS.length - 1 - index) * 30;
              return (
                <button
                  key={value}
                  type="button"
                  role={expanded === "mode" ? "radio" : undefined}
                  aria-checked={expanded === "mode" ? active : undefined}
                  aria-hidden={!visible}
                  aria-label={
                    expanded === "mode"
                      ? label
                      : `当前明暗主题：${activeOption.label}，展开明暗主题选项`
                  }
                  title={label}
                  tabIndex={visible ? 0 : -1}
                  onClick={() => {
                    if (expanded !== "mode") {
                      setExpanded("mode");
                      return;
                    }
                    choose(value);
                  }}
                  style={{ transitionDelay: `${motionDelay}ms, ${motionDelay}ms, ${motionDelay}ms, 0ms, 0ms` }}
                  className={`drawer-theme-option flex h-8 shrink-0 items-center justify-center overflow-hidden rounded-full ${
                    visible ? "w-8 scale-100 opacity-100" : "pointer-events-none w-0 scale-90 opacity-0"
                  } ${active ? "bg-signal text-canvas" : "text-ink-mid hover:bg-panel-soft hover:text-ink"}`}
                >
                  <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" strokeWidth={1.9} />
                </button>
              );
            })}
          </div>

          <span aria-hidden className="h-4 w-px shrink-0 bg-line" />

          <div
            aria-label="主题色"
            className={`drawer-theme-options flex items-center ${expanded === "palette" ? "gap-1" : "gap-0"}`}
            role={expanded === "palette" ? "radiogroup" : undefined}
          >
            {COLOR_PALETTES.map(({ value, label, swatch }, index) => {
              const active = palette === value;
              const visible = expanded === "palette" || active;
              const motionDelay =
                (expanded === "palette" ? index : COLOR_PALETTES.length - 1 - index) * 30;
              return (
                <button
                  key={value}
                  type="button"
                  role={expanded === "palette" ? "radio" : undefined}
                  aria-checked={expanded === "palette" ? active : undefined}
                  aria-hidden={!visible}
                  aria-label={
                    expanded === "palette"
                      ? label
                      : `当前主题色：${activePalette.label}，展开主题色选项`
                  }
                  title={label}
                  tabIndex={visible ? 0 : -1}
                  onClick={() => {
                    if (expanded !== "palette") {
                      setExpanded("palette");
                      return;
                    }
                    choosePalette(value);
                  }}
                  style={{ transitionDelay: `${motionDelay}ms, ${motionDelay}ms, ${motionDelay}ms, 0ms, 0ms` }}
                  className={`drawer-theme-option flex h-8 shrink-0 items-center justify-center overflow-hidden rounded-full ${
                    visible ? "w-8 scale-100 opacity-100" : "pointer-events-none w-0 scale-90 opacity-0"
                  } ${active ? "bg-panel-soft" : "hover:bg-panel-soft"}`}
                >
                  <span
                    aria-hidden
                    className="relative flex h-3.5 w-3.5 items-center justify-center rounded-full border border-line-strong"
                    style={{ backgroundColor: swatch }}
                  >
                    <Check
                      className={`h-2.5 w-2.5 text-white drop-shadow-sm ${active ? "opacity-100" : "opacity-0"}`}
                      strokeWidth={3}
                    />
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
