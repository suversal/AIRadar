"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type ScheduleConfig = {
  enabled: boolean;
  interval_minutes: number;
  last_triggered_at: string | null;
};

function formatTime(value: string | null) {
  if (!value) {
    return "从未";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

function nextRunEstimate(config: ScheduleConfig) {
  if (!config.enabled) {
    return "已关闭";
  }
  if (!config.last_triggered_at) {
    return "下次轮询时立即触发";
  }
  const last = new Date(config.last_triggered_at);
  if (Number.isNaN(last.getTime())) {
    return "未知";
  }
  const next = new Date(last.getTime() + config.interval_minutes * 60_000);
  return formatTime(next.toISOString());
}

export function SchedulePanel({ initialConfig }: { initialConfig: ScheduleConfig | null }) {
  const router = useRouter();
  const [config, setConfig] = useState<ScheduleConfig>(
    initialConfig ?? { enabled: false, interval_minutes: 120, last_triggered_at: null },
  );
  const [intervalInput, setIntervalInput] = useState(String(config.interval_minutes));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  if (!initialConfig) {
    return (
      <div className="rounded-md border border-line bg-panel p-5 text-sm text-ink-dim">
        定时任务需要数据库模式（设置 DATABASE_URL）才能使用。
      </div>
    );
  }

  async function save(nextEnabled: boolean) {
    const parsedInterval = Number(intervalInput);
    if (!Number.isFinite(parsedInterval) || parsedInterval < 5 || parsedInterval > 1440) {
      setMessage("间隔需在 5~1440 分钟之间。");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const response = await fetch("/api/admin-proxy/schedule", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: nextEnabled, interval_minutes: parsedInterval }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail ?? "保存失败");
      }
      setConfig(payload);
      setMessage(nextEnabled ? "定时任务已开启。" : "定时任务已关闭。");
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-md border border-line bg-panel p-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-base font-semibold text-ink">定时任务</h2>
        <span className="text-xs text-ink-dim">
          由后端服务内置调度，不依赖操作系统定时任务；关闭时不会自动触发抓取。
        </span>
      </div>
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <label className="flex items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={config.enabled}
            onChange={(event) => void save(event.target.checked)}
            disabled={saving}
          />
          开启自动刷新
        </label>
        <label className="flex flex-col gap-1 text-xs text-ink-dim">
          间隔（分钟）
          <input
            type="number"
            min={5}
            max={1440}
            value={intervalInput}
            onChange={(event) => setIntervalInput(event.target.value)}
            className="w-28 rounded-md border border-line bg-canvas px-2 py-1 text-sm text-ink"
          />
        </label>
        <button
          type="button"
          onClick={() => void save(config.enabled)}
          disabled={saving}
          className="rounded-md border border-signal bg-signal px-3 py-2 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60"
        >
          {saving ? "保存中..." : "保存间隔"}
        </button>
      </div>
      <p className="mt-3 text-xs text-ink-dim" aria-live="polite">
        上次触发：{formatTime(config.last_triggered_at)} · 预计下次：{nextRunEstimate(config)}
      </p>
      {message ? <p className="mt-1 text-sm text-ink-mid">{message}</p> : null}
    </section>
  );
}
