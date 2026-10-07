const UNITS = ["B", "KB", "MB", "GB", "TB"];

export function formatBytes(bytes: number | null | undefined, digits = 1): string {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  let scaled = value;
  let unit = 0;
  while (scaled >= 1024 && unit < UNITS.length - 1) {
    scaled /= 1024;
    unit += 1;
  }
  return `${scaled.toFixed(scaled >= 100 ? 0 : digits)} ${UNITS[unit]}`;
}

export function formatSpeed(bytesPerSecond: number | null | undefined): string {
  return `${formatBytes(bytesPerSecond)}/s`;
}

export function formatNumber(value: number | null | undefined): string {
  return (Number(value) || 0).toLocaleString("zh-CN");
}

export function formatDuration(seconds: number | null | undefined): string {
  let s = Math.max(0, Math.floor(Number(seconds) || 0));
  const d = Math.floor(s / 86400);
  s -= d * 86400;
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  if (d) return `${d} 天 ${h} 小时`;
  if (h) return `${h} 小时 ${m} 分`;
  if (m) return `${m} 分钟`;
  return `${s} 秒`;
}

const pad = (n: number) => String(n).padStart(2, "0");

export function formatTime(ts: number, withSeconds = true): string {
  const date = new Date(ts);
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return withSeconds ? `${time}:${pad(date.getSeconds())}` : time;
}

export function formatDateTime(unixSeconds: number): string {
  const date = new Date(unixSeconds * 1000);
  const now = new Date();
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  if (date.toDateString() === now.toDateString()) return `今天 ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return `昨天 ${time}`;
  return `${date.getMonth() + 1}-${pad(date.getDate())} ${time}`;
}

export function formatDateLabel(isoDate: string): string {
  const [, month, day] = isoDate.split("-");
  return `${Number(month)}/${Number(day)}`;
}

export function percent(part: number, whole: number): string {
  if (!whole) return "0%";
  const value = (part / whole) * 100;
  return `${value >= 99.95 || value < 10 ? value.toFixed(1) : value.toFixed(0)}%`;
}

export function basename(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

export function dirname(path: string): string {
  const index = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return index > 0 ? path.slice(0, index) : path;
}

/** Remaining time as M:SS or H:MM:SS; empty when unknown. */
export function formatEta(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0 || seconds > 99 * 3600) return "";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

/** Compact byte label for axis ticks: "2 MB" rather than "2.0 MB". */
export function formatTickBytes(bytes: number): string {
  return formatBytes(bytes).replace(/\.0 /, " ");
}

/** Nice round axis maximum and tick step for `max`. */
export function niceScale(max: number, ticks = 4): { max: number; step: number } {
  if (max <= 0) return { max: 1, step: 1 / ticks };
  const rough = max / ticks;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const residual = rough / magnitude;
  const nice = residual > 5 ? 10 : residual > 2 ? 5 : residual > 1 ? 2 : 1;
  const step = nice * magnitude;
  return { max: Math.ceil(max / step) * step, step };
}

/** Byte-aware nice scale so axis labels read 0 / 256 MB / 512 MB. */
export function niceByteScale(max: number, ticks = 4): { max: number; step: number } {
  if (max <= 0) return { max: 1024, step: 256 };
  let unit = 1;
  while (max / unit >= 1024 && unit < 1024 ** 4) unit *= 1024;
  const scaled = niceScale(max / unit, ticks);
  return { max: scaled.max * unit, step: scaled.step * unit };
}
