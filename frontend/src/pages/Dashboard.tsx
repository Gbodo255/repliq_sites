import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FolderGit2, FileStack, ImageDown, Activity, Plus, ArrowUpRight, Globe } from "lucide-react";
import { api } from "@/lib/api";
import { formatBytes, ssimColor, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui";
import { StatusBadge } from "@/components/StatusBadge";
import type { DashboardStats } from "@/types";

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    let alive = true;
    const load = () =>
      api.dashboard().then((d) => alive && setStats(d)).catch((e) => alive && setErr(e.message));
    load();
    const t = setInterval(load, 4000); // keep live while jobs run
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const tiles = [
    { label: "Projets", value: stats?.projects_total ?? 0, icon: FolderGit2 },
    { label: "Pages analysées", value: stats?.pages_total ?? 0, icon: FileStack },
    { label: "Ressources", value: stats?.assets_total ?? 0, icon: ImageDown },
    { label: "En cours", value: stats?.projects_running ?? 0, icon: Activity },
  ];

  return (
    <div className="space-y-10">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-[34px] leading-none tracking-tight text-ink">Tableau de bord</h1>
          <p className="mt-2 text-[15px] text-muted">Vos réplications, en un coup d'œil.</p>
        </div>
        <Button onClick={() => navigate("/app/new")}>
          <Plus className="h-4 w-4" /> Nouvelle réplication
        </Button>
      </div>

      {err && (
        <div className="rounded-2xl border border-destructive/40 bg-destructive/[0.04] p-4 text-sm text-destructive">
          Impossible de joindre le serveur ({err}).
        </div>
      )}

      {/* Stat tiles */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-2xl border border-border bg-white p-5">
            <div className="flex items-center justify-between">
              <span className="text-[13px] text-faint">{t.label}</span>
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-panel text-muted">
                <t.icon className="h-4 w-4" />
              </span>
            </div>
            <div className="font-display mt-4 text-[38px] leading-none tabular-nums text-ink">{t.value}</div>
          </div>
        ))}
      </div>

      {/* Recent projects */}
      <div>
        <div className="mb-4 flex items-end justify-between">
          <h2 className="text-[18px] font-semibold tracking-tight text-ink">Projets récents</h2>
          {stats && <span className="text-[13px] text-faint">{formatBytes(stats.assets_bytes)} stockés</span>}
        </div>

        {stats && stats.recent.length === 0 && (
          <div className="rounded-2xl border border-dashed border-border-strong bg-panel/40 py-16 text-center">
            <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-white text-muted">
              <Globe className="h-6 w-6" />
            </span>
            <p className="mt-4 text-[16px] font-semibold text-ink">Aucun projet pour l'instant</p>
            <p className="mt-1 text-sm text-muted">Collez une URL pour lancer votre première copie.</p>
            <Button className="mt-5" onClick={() => navigate("/app/new")}>
              <Plus className="h-4 w-4" /> Nouvelle réplication
            </Button>
          </div>
        )}

        <div className="space-y-2.5">
          {stats?.recent.map((p) => (
            <Link
              key={p.id}
              to={`/app/projects/${p.id}`}
              className="group flex items-center gap-4 rounded-2xl border border-border bg-white p-4 transition-colors hover:border-ink/25"
            >
              <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-panel text-muted">
                <Globe className="h-5 w-5" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-[15px] font-semibold text-ink">{p.name}</span>
                  <StatusBadge status={p.status} />
                </div>
                <div className="truncate text-[13px] text-muted">{p.url}</div>
              </div>
              <div className="hidden items-center gap-7 sm:flex">
                {[
                  { v: p.pages_count, l: "pages" },
                  { v: p.assets_count, l: "ressources" },
                ].map((m) => (
                  <div key={m.l} className="text-center">
                    <div className="font-display text-[20px] leading-none tabular-nums text-ink">{m.v}</div>
                    <div className="mt-1 text-[11px] text-faint">{m.l}</div>
                  </div>
                ))}
                <div className="text-center">
                  <div className={`font-display text-[20px] leading-none tabular-nums ${ssimColor(p.avg_ssim)}`}>
                    {p.avg_ssim != null ? `${Math.round(p.avg_ssim * 100)}%` : "—"}
                  </div>
                  <div className="mt-1 text-[11px] text-faint">fidélité</div>
                </div>
              </div>
              <div className="hidden w-14 text-right text-[12px] text-faint md:block">{timeAgo(p.updated_at)}</div>
              <ArrowUpRight className="h-4 w-4 shrink-0 text-faint transition-colors group-hover:text-ink" />
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
