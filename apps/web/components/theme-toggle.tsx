"use client";

import { useEffect, useState } from "react";
import { Moon, Monitor, Sun } from "lucide-react";

type ThemePreference = "dark" | "system" | "light";

const STORAGE_KEY = "ai-radar-theme";

const OPTIONS: { value: ThemePreference; icon: typeof Moon; label: string }[] = [
  { value: "dark", icon: Moon, label: "夜间" },
  { value: "system", icon: Monitor, label: "跟随系统" },
  { value: "light", icon: Sun, label: "日间" },
];

function systemPrefersLight() {
  return window.matchMedia("(prefers-color-scheme: light)").matches;
}

function applyResolvedTheme(preference: ThemePreference) {
  const resolved = preference === "system" ? (systemPrefersLight() ? "light" : "dark") : preference;
  if (resolved === "light") {
    document.documentElement.setAttribute("data-theme", "light");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}

export function ThemeToggle() {
  // defaults to "system" so a first-time visitor (or one who already chose
  // "system") sees the toggle in the same state the blocking init script
  // already resolved - only corrected on mount if localStorage says otherwise
  const [preference, setPreference] = useState<ThemePreference>("system");

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "dark" || stored === "system" || stored === "light") {
      setPreference(stored);
    }
  }, []);

  useEffect(() => {
    applyResolvedTheme(preference);
    if (preference !== "system") {
      return;
    }
    const mql = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => applyResolvedTheme("system");
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [preference]);

  function choose(next: ThemePreference) {
    setPreference(next);
    localStorage.setItem(STORAGE_KEY, next);
  }

  return (
    <div
      role="radiogroup"
      aria-label="主题"
      className="fixed bottom-6 left-5 z-20 flex items-center gap-1 rounded-full border border-line-strong bg-panel/85 p-1 shadow-[0_8px_24px_rgba(0,0,0,0.3)] backdrop-blur-md"
    >
      {OPTIONS.map(({ value, icon: Icon, label }) => {
        const active = preference === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={label}
            title={label}
            onClick={() => choose(value)}
            className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
              active ? "bg-signal text-canvas" : "text-ink-mid hover:text-ink"
            }`}
          >
            <Icon aria-hidden className="h-4 w-4" strokeWidth={2} />
          </button>
        );
      })}
    </div>
  );
}
