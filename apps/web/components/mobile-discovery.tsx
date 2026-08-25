"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { ChevronRight, Search } from "lucide-react";

type HiddenField = {
  name: string;
  value: string;
};

type FilterOption = {
  href: string;
  label: string;
  selected: boolean;
};

export function MobileSearchForm({
  action,
  defaultValue,
  hiddenFields,
  placeholder,
  trailingControl,
}: {
  action: string;
  defaultValue: string;
  hiddenFields: HiddenField[];
  placeholder: string;
  trailingControl?: ReactNode;
}) {
  return (
    <form action={action} aria-label="搜索内容" className="mt-2.5 flex gap-2 md:hidden">
      {hiddenFields.map((field) => (
        <input key={field.name} name={field.name} type="hidden" value={field.value} />
      ))}
      <div className="relative min-w-0 flex-1">
        <button
          aria-label="提交搜索"
          className="absolute inset-y-0 left-0 z-10 flex w-11 items-center justify-center text-ink-dim hover:text-signal"
          type="submit"
        >
          <Search aria-hidden className="h-4.5 w-4.5" strokeWidth={1.75} />
        </button>
        <input
          className="min-h-11 w-full border border-line bg-canvas py-2 pl-11 pr-3 text-sm text-ink outline-none placeholder:text-ink-dim focus:border-signal/60"
          defaultValue={defaultValue}
          name="q"
          placeholder={placeholder}
          type="search"
        />
      </div>
      {trailingControl}
    </form>
  );
}

export function MobileCategoryNav({
  label,
  options,
}: {
  label: string;
  options: FilterOption[];
}) {
  const activeOptionRef = useRef<HTMLAnchorElement>(null);
  const selectedHref = options.find((option) => option.selected)?.href;

  useEffect(() => {
    activeOptionRef.current?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [selectedHref]);

  return (
    <div className="relative mt-1.5 md:hidden">
      <nav
        aria-label={label}
        className="flex gap-1 overflow-x-auto pr-8 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {options.map((option) => (
          <a
            key={option.href}
            aria-current={option.selected ? "true" : undefined}
            ref={option.selected ? activeOptionRef : undefined}
            className={`flex min-h-10 shrink-0 items-center border-b px-2 py-1 text-sm font-medium ${
              option.selected
                ? "border-signal text-signal"
                : "border-transparent text-ink-mid hover:border-line-strong hover:text-ink"
            }`}
            href={option.href}
          >
            {option.label}
          </a>
        ))}
      </nav>
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 right-0 flex w-10 items-center justify-end bg-gradient-to-l from-canvas via-canvas/95 to-transparent text-ink-dim"
      >
        <ChevronRight className="h-4 w-4" strokeWidth={1.75} />
      </span>
    </div>
  );
}
