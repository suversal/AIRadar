"use client";

import { useEffect, useRef, useState } from "react";
import { Moon, Monitor, Sun } from "lucide-react";

type ThemePreference = "dark" | "system" | "light";

const STORAGE_KEY = "ai-radar-theme";

const OPTIONS: { value: ThemePreference; icon: typeof Moon; label: string }[] = [
  { value: "dark", icon: Moon, label: "夜间" },
  { value: "system", icon: Monitor, label: "跟随系统" },
  { value: "light", icon: Sun, label: "日间" },
];

const TRANSITION_MS = 350;

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
  const resolved = preference === "system" ? (systemPrefersLight() ? "light" : "dark") : preference;
  if (resolved === "light") {
    root.setAttribute("data-theme", "light");
  } else {
    root.removeAttribute("data-theme");
  }
}

export function ThemeToggle() {
  // defaults to "system" so a first-time visitor (or one who already chose
  // "system") sees the toggle in the same state the blocking init script
  // already resolved - only corrected on mount if localStorage says otherwise
  const [preference, setPreference] = useState<ThemePreference>("system");
  const mounted = useRef(false);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "dark" || stored === "system" || stored === "light") {
      setPreference(stored);
    }
  }, []);

  useEffect(() => {
    applyResolvedTheme(preference, { withTransition: mounted.current });
    mounted.current = true;
    if (preference !== "system") {
      return;
    }
    const mql = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => applyResolvedTheme("system", { withTransition: true });
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
