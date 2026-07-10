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
      <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-dim">
        定时任务不可用：需要数据库模式
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
    <div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
        <div className="min-w-0">
          <div>
            <h2 className="text-base font-semibold text-ink">自动同步</h2>
            <p className="mt-1 text-xs text-ink-dim">
              按固定间隔自动触发数据同步，使用当前环境默认抓取与日报条数配置
            </p>
          </div>
          <p className="mt-3 text-xs text-ink-dim" aria-live="polite">
            上次触发：{formatTime(config.last_triggered_at)} · 预计下次：
            {nextRunEstimate(config)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 lg:justify-end">
          <span
            className={
              config.enabled
                ? "rounded border border-green-400/30 bg-green-400/10 px-2 py-1 text-xs font-semibold text-green-300"
                : "rounded border border-line bg-panel px-2 py-1 text-xs font-semibold text-ink-dim"
            }
          >
            {config.enabled ? "已开启" : "已关闭"}
          </span>
          <label className="flex items-center gap-2 text-xs text-ink-dim">
            同步间隔
            <input
              inputMode="numeric"
              type="text"
              value={intervalInput}
              onChange={(event) => setIntervalInput(event.target.value)}
              className="readout w-20 rounded-md border border-line bg-canvas px-2 py-1 text-sm text-ink outline-none focus:border-signal/50"
            />
            分钟
          </label>
          <button
            type="button"
            onClick={() => void save(config.enabled)}
            disabled={saving}
            className="rounded-md border border-signal bg-signal px-3 py-1.5 text-xs font-semibold text-canvas hover:bg-signal-bright disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? "保存中..." : "保存间隔"}
          </button>
          <button
            type="button"
            onClick={() => void save(!config.enabled)}
            disabled={saving}
            className="rounded-md border border-signal bg-signal px-3 py-1.5 text-xs font-semibold text-canvas hover:bg-signal-bright disabled:cursor-not-allowed disabled:opacity-60"
          >
            {config.enabled ? "关闭自动同步" : "开启自动同步"}
          </button>
        </div>
      </div>
      {message ? <p className="mt-1 text-sm text-ink-mid">{message}</p> : null}
    </div>
  );
}
