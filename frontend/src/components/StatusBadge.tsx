import { Badge } from "@/components/ui";
import type { JobStatus } from "@/types";

const MAP: Record<JobStatus, { label: string; variant: "success" | "warn" | "error" | "default" | "muted" }> = {
  completed: { label: "Terminé", variant: "success" },
  running: { label: "En cours", variant: "default" },
  queued: { label: "En file", variant: "muted" },
  failed: { label: "Échec", variant: "error" },
  cancelled: { label: "Annulé", variant: "warn" },
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
