import * as React from "react";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ Button */
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "accent" | "secondary" | "outline" | "ghost" | "destructive";
  size?: "sm" | "md" | "lg" | "icon";
};
const BTN_VARIANTS: Record<string, string> = {
  default: "btn-primary",
  accent: "btn-accent",
  secondary: "btn-outline",
  outline: "btn-outline",
  ghost: "btn-ghost",
  destructive:
    "bg-[#d23b3b] text-white hover:brightness-105 active:translate-y-px transition",
};
const BTN_SIZES: Record<string, string> = {
  sm: "h-9 px-3.5 text-[13px]",
  md: "h-11 px-5 text-[15px]",
  lg: "h-12 px-6 text-base",
  icon: "h-10 w-10 p-0",
};
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "btn focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2",
        BTN_VARIANTS[variant],
        BTN_SIZES[size],
        className
      )}
      {...props}
    />
  )
);
Button.displayName = "Button";

/* ----------------------------------------------------------------- Eyebrow */
export function Eyebrow({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <span className={cn("eyebrow inline-flex items-center gap-2", className)}>
      <span className="h-1.5 w-1.5 rounded-full bg-accent" />
      {children}
    </span>
  );
}

/* -------------------------------------------------------------------- Card */
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-2xl border bg-white", className)} {...props} />;
}
export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1 p-5", className)} {...props} />;
}
export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-[17px] font-semibold tracking-tight text-ink", className)} {...props} />;
}
export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted", className)} {...props} />;
}
export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5 pt-0", className)} {...props} />;
}

/* ------------------------------------------------------------------- Input */
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "flex h-11 w-full rounded-xl border border-border-strong bg-white px-3.5 text-[15px] text-ink",
        "placeholder:text-faint focus-visible:outline-none focus-visible:border-ink focus-visible:ring-2 focus-visible:ring-accent/25 disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("text-sm font-medium text-ink", className)} {...props} />;
}

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "flex h-11 w-full rounded-xl border border-border-strong bg-white px-3 text-[15px] text-ink",
        "focus-visible:outline-none focus-visible:border-ink focus-visible:ring-2 focus-visible:ring-accent/25",
        className
      )}
      {...props}
    >
      {children}
    </select>
  )
);
Select.displayName = "Select";

/* ------------------------------------------------------------------- Badge */
export function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: "default" | "outline" | "success" | "warn" | "error" | "muted" }) {
  const variants: Record<string, string> = {
    default: "bg-accent/10 text-accent",
    outline: "border border-border-strong text-ink",
    success: "bg-emerald-500/12 text-emerald-700",
    warn: "bg-amber-500/14 text-amber-700",
    error: "bg-[#d23b3b]/12 text-[#b02a2a]",
    muted: "bg-panel text-muted",
  };
  return (
    <span
      className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", variants[variant], className)}
      {...props}
    />
  );
}

/* ---------------------------------------------------------------- Progress */
export function Progress({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("h-2.5 w-full overflow-hidden rounded-full bg-panel-2", className)}>
      <div
        className="h-full rounded-full bg-accent transition-all duration-300"
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}

/* ---------------------------------------------------------------- Checkbox */
export function Checkbox({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="checkbox"
      className={cn("h-4 w-4 rounded border-border-strong accent-[var(--accent)]", className)}
      {...props}
    />
  );
}
