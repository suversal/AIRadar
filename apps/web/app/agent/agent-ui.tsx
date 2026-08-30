import { ArrowUpRight, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { CopyButton } from "@/components/copy-button";

export function ResourceLink({
  href,
  icon: Icon,
  title,
  desc,
  external = false,
}: {
  href: string;
  icon: LucideIcon;
  title: ReactNode;
  desc: string;
  external?: boolean;
}) {
  return (
    <a
      href={href}
      target={external ? "_blank" : undefined}
      rel={external ? "noreferrer" : undefined}
      className="flex items-center gap-3 rounded-md border border-line bg-canvas px-3.5 py-3 transition-colors hover:border-signal/50"
    >
      <Icon className="h-[17px] w-[17px] shrink-0 text-signal" aria-hidden />
      <span className="min-w-0 grow">
        <span className="block text-sm text-ink">{title}</span>
        <span className="mt-0.5 block text-[13px] leading-5 text-ink-dim">{desc}</span>
      </span>
      <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-ink-dim" aria-hidden />
    </a>
  );
}

export function Code({ label, code }: { label: string; code: string }) {
  return (
    <div className="rounded-md border border-line bg-canvas">
      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-1.5">
        <span className="text-xs text-ink-dim">{label}</span>
        <CopyButton text={code} />
      </div>
      <pre
        tabIndex={0}
        className="readout overflow-x-auto px-3 py-3 text-xs leading-6 text-ink focus:outline-none focus:ring-2 focus:ring-signal/40"
      >
        {code}
      </pre>
    </div>
  );
}

export function PanelHead({ title, lead }: { title: string; lead: string }) {
  return (
    <div>
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      <p className="mt-1.5 text-[15px] leading-6 text-ink-mid">{lead}</p>
    </div>
  );
}

export function Note({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-md border-l-4 border-signal bg-signal/10 p-4 text-sm leading-6 text-ink-mid">
      <p className="font-semibold text-signal-bright">{title}</p>
      <div className="mt-1.5 space-y-1.5">{children}</div>
    </div>
  );
}

export function Endpoint({ path, children }: { path: string; children: ReactNode }) {
  return (
    <div className="border-b border-line py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="readout rounded border border-signal/40 px-1.5 py-0.5 text-[10px] font-semibold text-signal">
          GET
        </span>
        <code className="readout min-w-0 break-all text-[13px] text-ink">{path}</code>
      </div>
      <p className="mt-1 text-[13px] leading-5 text-ink-dim">{children}</p>
    </div>
  );
}
