import { cn } from "@/lib/utils";

/** Original Replicator mark: three stacked layers (the captured copies) with the
    top one in accent. */
export default function Logo({ className, withWord = true }: { className?: string; withWord?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-ink">
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <polygon points="12,4 20,8 12,12 4,8" fill="#2337ff" />
          <polygon points="12,9 20,13 12,17 4,13" fill="#ffffff" opacity="0.92" />
          <polygon points="12,14 20,18 12,22 4,18" fill="#ffffff" opacity="0.55" />
        </svg>
      </span>
      {withWord && (
        <span className="text-[19px] font-semibold tracking-tight text-ink">Replicator</span>
      )}
    </span>
  );
}
