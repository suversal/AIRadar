"use client";

import { useEffect, useState } from "react";
import { ArrowUp } from "lucide-react";

export function ScrollToTopButton() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    function onScroll() {
      setVisible(window.scrollY > 400);
    }
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <button
      type="button"
      aria-label="回到顶部"
      tabIndex={visible ? 0 : -1}
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
      // globals.css has an unlayered `button { transition: color/background-color/
      // border-color/box-shadow/transform ... }` reset that beats any Tailwind
      // transition-*/duration-*/ease-* utility class here (unlayered CSS always
      // outranks the utility layer - same gotcha documented in globals.css for
      // the `a { text-decoration: none }` reset). Setting `transition` inline is
      // the only way to actually animate opacity on this button; without it the
      // global rule silently drops opacity from the transition list entirely,
      // so the fade snaps instantly instead of easing.
      style={{ transition: "opacity 700ms cubic-bezier(0.34,1.56,0.64,1), transform 700ms cubic-bezier(0.34,1.56,0.64,1)" }}
      className={`fixed bottom-6 right-5 z-20 flex h-11 w-11 items-center justify-center rounded-full border border-white/15 bg-panel/30 text-ink-mid shadow-[0_8px_24px_rgba(0,0,0,0.35)] backdrop-blur-md hover:border-signal/50 hover:bg-panel/60 hover:text-signal ${
        visible ? "translate-y-0 scale-100 opacity-100" : "pointer-events-none translate-y-4 scale-75 opacity-0"
      }`}
    >
      <ArrowUp aria-hidden className="h-5 w-5" strokeWidth={2} />
    </button>
  );
}
