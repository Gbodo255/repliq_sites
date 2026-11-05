import { Badge } from "@/components/ui";
import type { JobStatus } from "@/types";

const MAP: Record<JobStatus, { label: string; variant: "success" | "warn" | "error" | "default" | "muted" }> = {
  completed: { label: "Completed", variant: "success" },
  running: { label: "Running", variant: "default" },
  queued: { label: "Queued", variant: "muted" },
  failed: { label: "Failed", variant: "error" },
  cancelled: { label: "Cancelled", variant: "warn" },
};

export function StatusBadge({ status }: { status: JobStatus }) {
  const cfg = MAP[status] ?? MAP.queued;
  return (
    <Badge variant={cfg.variant}>
      {status === "running" && (
        <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      )}
      {cfg.label}
    </Badge>
  );
}
