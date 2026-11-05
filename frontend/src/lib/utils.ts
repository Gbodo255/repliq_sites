export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function formatBytes(n: number): string {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${i === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}

export function timeAgo(tsSeconds: number): string {
  const diff = Date.now() / 1000 - tsSeconds;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function ssimColor(ssim: number | null): string {
  if (ssim == null) return "text-muted-foreground";
  if (ssim >= 0.9) return "text-emerald-500";
  if (ssim >= 0.75) return "text-amber-500";
  return "text-destructive";
}
