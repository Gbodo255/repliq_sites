import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  FolderGit2, FileStack, ImageDown, Activity, Plus, ArrowRight, Globe,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatBytes, ssimColor, timeAgo } from "@/lib/utils";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
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
    { label: "Projects", value: stats?.projects_total ?? 0, icon: FolderGit2 },
    { label: "Pages analysed", value: stats?.pages_total ?? 0, icon: FileStack },
    { label: "Assets downloaded", value: stats?.assets_total ?? 0, icon: ImageDown },
    { label: "Running now", value: stats?.projects_running ?? 0, icon: Activity },
  ];

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground mt-1">
            Replicate any website into a self-contained local project.
          </p>
        </div>
        <Button onClick={() => navigate("/new")}>
          <Plus className="h-4 w-4" /> New replication
        </Button>
      </div>

      {err && (
        <Card className="border-destructive/40">
          <CardContent className="pt-5 text-sm text-destructive">
            Could not reach the backend ({err}). Make sure the API server is running on port 8000.
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {tiles.map((t) => (
          <Card key={t.label}>
            <CardContent className="pt-5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{t.label}</span>
                <t.icon className="h-4 w-4 text-primary" />
              </div>
              <div className="mt-2 text-3xl font-bold tabular-nums">{t.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">Recent projects</h2>
          {stats && (
            <span className="text-sm text-muted-foreground">
              {formatBytes(stats.assets_bytes)} of assets stored
            </span>
          )}
        </div>

        {stats && stats.recent.length === 0 && (
          <Card>
            <CardContent className="py-12 text-center">
              <Globe className="mx-auto h-10 w-10 text-muted-foreground/50" />
              <p className="mt-3 font-medium">No projects yet</p>
              <p className="text-sm text-muted-foreground">Start by replicating your first site.</p>
              <Button className="mt-4" onClick={() => navigate("/new")}>
                <Plus className="h-4 w-4" /> New replication
              </Button>
            </CardContent>
          </Card>
        )}

        <div className="space-y-3">
          {stats?.recent.map((p) => (
            <Link key={p.id} to={`/projects/${p.id}`}>
              <Card className="hover:border-primary/50 transition-colors">
                <CardContent className="py-4 flex items-center gap-4">
                  <div className="grid h-10 w-10 place-items-center rounded-lg bg-secondary shrink-0">
                    <Globe className="h-5 w-5 text-primary" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium truncate">{p.name}</span>
                      <StatusBadge status={p.status} />
                    </div>
                    <div className="text-sm text-muted-foreground truncate">{p.url}</div>
                  </div>
                  <div className="hidden sm:flex items-center gap-6 text-sm">
                    <div className="text-center">
                      <div className="font-semibold tabular-nums">{p.pages_count}</div>
                      <div className="text-xs text-muted-foreground">pages</div>
                    </div>
                    <div className="text-center">
                      <div className="font-semibold tabular-nums">{p.assets_count}</div>
                      <div className="text-xs text-muted-foreground">assets</div>
                    </div>
                    <div className="text-center">
                      <div className={`font-semibold tabular-nums ${ssimColor(p.avg_ssim)}`}>
                        {p.avg_ssim != null ? `${Math.round(p.avg_ssim * 100)}%` : "—"}
                      </div>
                      <div className="text-xs text-muted-foreground">fidelity</div>
                    </div>
                  </div>
                  <div className="text-xs text-muted-foreground w-16 text-right">{timeAgo(p.updated_at)}</div>
                  <ArrowRight className="h-4 w-4 text-muted-foreground" />
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
