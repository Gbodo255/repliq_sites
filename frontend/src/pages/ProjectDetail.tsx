import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Download, ExternalLink, Trash2, XCircle, ArrowLeft, Monitor, Image as ImageIcon,
  FileCode2, Layers, Gauge, Terminal, Eye, AlertTriangle, RotateCw, Package, ShieldCheck, Plus, Loader2,
} from "lucide-react";
import { api } from "@/lib/api";
import { useJobProgress } from "@/hooks/useJobProgress";
import { cn, formatBytes, ssimColor } from "@/lib/utils";
import { Button, Card, CardContent, Progress, Badge } from "@/components/ui";
import { StatusBadge } from "@/components/StatusBadge";
import type { CompareRecord, OutputTarget, ProjectDetail as Detail } from "@/types";

const ALL_TARGETS: { id: OutputTarget; label: string; hint: string }[] = [
  { id: "static", label: "HTML / CSS / JS", hint: "Open index.html" },
  { id: "react", label: "React (Vite)", hint: "npm install && npm run dev" },
  { id: "nextjs", label: "Next.js", hint: "npm install && npm run dev" },
  { id: "wordpress_theme", label: "WordPress theme", hint: "Upload the theme zip in WordPress" },
  { id: "wordpress_headless", label: "WordPress headless (Next.js)", hint: "docker compose up + npm run dev" },
];

type TabId = "overview" | "progress" | "pages" | "assets" | "comparison" | "preview";

export default function ProjectDetail() {
  const { id = "" } = useParams();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [tab, setTab] = useState<TabId>("overview");
  const [error, setError] = useState<string | null>(null);

  const running = detail?.status === "running" || detail?.status === "queued";
  const { events, progress, phase, done } = useJobProgress(id, !!running);

  useEffect(() => {
    let alive = true;
    const load = () => api.getProject(id).then((d) => alive && setDetail(d)).catch((e) => alive && setError(e.message));
    load();
    const t = setInterval(() => {
      if (alive) load();
    }, 2000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [id]);

  // When a running job finishes, switch away from the progress tab.
  useEffect(() => {
    if (running) setTab("progress");
  }, [running]);
  useEffect(() => {
    if (done) api.getProject(id).then(setDetail).catch(() => {});
  }, [done, id]);

  if (error && !detail) {
    return (
      <div className="text-center py-16">
        <p className="text-destructive">{error}</p>
        <Link to="/" className="text-primary mt-4 inline-block">← Back to dashboard</Link>
      </div>
    );
  }
  if (!detail) return <div className="py-16 text-center text-muted-foreground">Loading…</div>;

  const TABS: { id: TabId; label: string; icon: typeof Gauge }[] = [
    { id: "overview", label: "Overview", icon: Gauge },
    ...(running ? [{ id: "progress" as TabId, label: "Live progress", icon: Terminal }] : []),
    { id: "pages", label: `Pages (${detail.pages_count})`, icon: FileCode2 },
    { id: "assets", label: `Assets (${detail.assets_count})`, icon: Layers },
    { id: "comparison", label: "Visual check", icon: ImageIcon },
    { id: "preview", label: "Preview", icon: Eye },
  ];

  async function cancel() {
    await api.cancel(id).catch(() => {});
  }
  async function rerun() {
    if (confirm("Replicate this site again with the same options? Current files will be regenerated.")) {
      await api.rerun(id).catch((e) => setError((e as Error).message));
      api.getProject(id).then(setDetail).catch(() => {});
    }
  }
  async function remove() {
    if (confirm("Delete this project and all its files?")) {
      await api.remove(id).catch(() => {});
      window.location.href = "/";
    }
  }

  return (
    <div className="space-y-6">
      <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Dashboard
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-2xl font-bold tracking-tight truncate">{detail.name}</h1>
            <StatusBadge status={detail.status} />
          </div>
          <a href={detail.url} target="_blank" rel="noreferrer"
             className="text-sm text-muted-foreground hover:text-primary inline-flex items-center gap-1 mt-1">
            {detail.url} <ExternalLink className="h-3 w-3" />
          </a>
        </div>
        <div className="flex items-center gap-2">
          {running ? (
            <Button variant="outline" size="sm" onClick={cancel}>
              <XCircle className="h-4 w-4" /> Cancel
            </Button>
          ) : (
            <>
              {detail.has_zip && (
                <a href={api.downloadUrl(id)}>
                  <Button size="sm"><Download className="h-4 w-4" /> ZIP</Button>
                </a>
              )}
              <Button size="sm" variant="outline" onClick={rerun} title="Replicate again">
                <RotateCw className="h-4 w-4" /> Re-run
              </Button>
              <a href={api.siteUrl(id)} target="_blank" rel="noreferrer">
                <Button size="sm" variant="outline"><ExternalLink className="h-4 w-4" /> Open</Button>
              </a>
            </>
          )}
          <Button size="icon" variant="ghost" onClick={remove} title="Delete">
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {detail.error && (
        <Card className="border-destructive/40">
          <CardContent className="pt-5 text-sm text-destructive flex gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" /> {detail.error}
          </CardContent>
        </Card>
      )}

      {running && (
        <Card>
          <CardContent className="pt-5 space-y-2">
            <div className="flex justify-between text-sm">
              <span className="font-medium capitalize">{phase || "starting"}…</span>
              <span className="tabular-nums text-muted-foreground">{Math.round(progress)}%</span>
            </div>
            <Progress value={progress} />
          </CardContent>
        </Card>
      )}

      {/* Tabs */}
      <div className="border-b flex gap-1 overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px whitespace-nowrap transition-colors",
              tab === t.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            <t.icon className="h-4 w-4" /> {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <Overview detail={detail} running={!!running} onChange={() => { api.getProject(id).then(setDetail).catch(() => {}); }} />
      )}
      {tab === "progress" && <LiveLog events={events} />}
      {tab === "pages" && <PagesTab detail={detail} />}
      {tab === "assets" && <AssetsTab detail={detail} />}
      {tab === "comparison" && <ComparisonTab id={id} comparisons={detail.comparisons} />}
      {tab === "preview" && <PreviewTab id={id} url={detail.url} />}
    </div>
  );
}

/* --------------------------------------------------------------- Overview */
function Overview({ detail, running, onChange }: { detail: Detail; running: boolean; onChange: () => void }) {
  const a = detail.analysis || {};
  const q = detail.quality && detail.quality.pages ? detail.quality : undefined;
  const stats = [
    { label: "Pages", value: detail.pages_count },
    { label: "Assets", value: detail.assets_count },
    { label: "Asset size", value: formatBytes(detail.assets_bytes) },
    { label: "Fidelity", value: q && q.overall_score != null ? `${Math.round(q.overall_score * 100)}% · ${q.grade}`
        : detail.avg_ssim != null ? `${Math.round(detail.avg_ssim * 100)}%` : "—",
      cls: ssimColor(q && q.overall_score != null ? q.overall_score : detail.avg_ssim) },
    { label: "Duration", value: `${detail.duration ?? 0}s` },
  ];
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {stats.map((s) => (
          <Card key={s.label}>
            <CardContent className="pt-5">
              <div className="text-sm text-muted-foreground">{s.label}</div>
              <div className={cn("mt-1 text-2xl font-bold tabular-nums", s.cls)}>{s.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <OutputsCard detail={detail} running={running} onChange={onChange} />

      {q && (
        <Card>
          <CardContent className="pt-5 flex flex-wrap gap-6 items-center text-sm">
            <div className="flex items-center gap-2">
              <ShieldCheck className={cn("h-5 w-5", q.external_refs_remaining === 0 ? "text-emerald-500" : "text-amber-500")} />
              <span className="font-medium">
                {q.external_refs_remaining === 0 ? "Zero external link or resource" : `${q.external_refs_remaining} external reference(s) remaining`}
              </span>
            </div>
            <span className="text-muted-foreground">{q.external_refs_removed} external reference(s) neutralised</span>
            <span className="text-muted-foreground">
              {q.pages.reduce((n, p) => n + p.fixes_applied, 0)} layout correction(s) applied
            </span>
            {q.assets_failed > 0 && <span className="text-amber-500">{q.assets_failed} asset(s) could not be downloaded</span>}
          </CardContent>
        </Card>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        <Card>
          <CardContent className="pt-5 space-y-4">
            <Section title="Detected technology">
              <div className="flex flex-wrap gap-2">
                {(a.frameworks?.length ? a.frameworks : ["Classic HTML / unknown"]).map((f) => (
                  <Badge key={f} variant="outline">{f}</Badge>
                ))}
              </div>
            </Section>
            <Section title="Components">
              <div className="flex flex-wrap gap-2">
                {(a.components?.length ? a.components : ["—"]).map((c) => (
                  <Badge key={c} variant="muted">{String(c).replace(/_/g, " ")}</Badge>
                ))}
              </div>
            </Section>
            <Section title="Interactions re-implemented">
              <div className="flex flex-wrap gap-2">
                {a.interactions && Object.keys(a.interactions).length
                  ? Object.entries(a.interactions).map(([k, v]) => (
                      <Badge key={k} variant="default">{k.replace(/_/g, " ")} · {v}</Badge>
                    ))
                  : <span className="text-sm text-muted-foreground">none detected</span>}
              </div>
            </Section>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-5 space-y-4">
            <Section title="Colour palette">
              <div className="flex flex-wrap gap-2">
                {(a.palette || []).slice(0, 14).map((c, i) => (
                  <div key={i} className="flex items-center gap-1.5 rounded-md border px-2 py-1">
                    <span className="h-4 w-4 rounded" style={{ background: c as string }} />
                    <span className="text-xs font-mono text-muted-foreground">{c as string}</span>
                  </div>
                ))}
                {!a.palette?.length && <span className="text-sm text-muted-foreground">—</span>}
              </div>
            </Section>
            <Section title="Fonts">
              <div className="flex flex-wrap gap-2">
                {(a.fonts || []).map((f) => <Badge key={f} variant="outline">{f}</Badge>)}
                {!a.fonts?.length && <span className="text-sm text-muted-foreground">—</span>}
              </div>
            </Section>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function OutputsCard({ detail, running, onChange }: { detail: Detail; running: boolean; onChange: () => void }) {
  const [busy, setBusy] = useState<OutputTarget | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const exports = detail.exports || [];
  const byTarget = new Map(exports.map((e) => [e.target, e]));
  async function generate(t: OutputTarget) {
    setBusy(t);
    setErr(null);
    try {
      await api.addOutputs(detail.id, [t]);
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  return (
    <Card>
      <CardContent className="pt-5 space-y-3">
        <Section title="Outputs">
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {ALL_TARGETS.map((t) => {
              const e = byTarget.get(t.id);
              const ready = !!(e && e.zip && !e.error);
              return (
                <div key={t.id} className="rounded-lg border p-3 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 font-medium text-sm">
                      <Package className="h-4 w-4 text-primary shrink-0" /> {t.label}
                    </div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {e && e.error ? <span className="text-destructive">{e.error}</span>
                        : ready && e ? `${formatBytes(e.size)} · ${t.hint}` : "Not generated yet"}
                    </div>
                  </div>
                  {ready ? (
                    <a href={api.downloadUrl(detail.id, t.id)}>
                      <Button size="sm"><Download className="h-4 w-4" /></Button>
                    </a>
                  ) : (
                    <Button size="sm" variant="outline" disabled={running || !detail.has_zip || busy !== null}
                      onClick={() => generate(t.id)} title="Generate this format">
                      {busy === t.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </Section>
        {err && <p className="text-sm text-destructive">{err}</p>}
      </CardContent>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">{title}</div>
      {children}
    </div>
  );
}

/* ---------------------------------------------------------------- LiveLog */
function LiveLog({ events }: { events: { phase: string; message: string; level: string; progress: number }[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollTo(0, ref.current.scrollHeight);
  }, [events.length]);
  const color: Record<string, string> = {
    error: "text-destructive", warn: "text-amber-500", success: "text-emerald-500", info: "text-foreground",
  };
  return (
    <Card>
      <CardContent className="pt-5">
        <div ref={ref} className="font-mono text-xs h-96 overflow-y-auto rounded-lg bg-secondary/50 p-4 space-y-1">
          {events.length === 0 && <div className="text-muted-foreground">Waiting for the engine…</div>}
          {events.map((e, i) => (
            <div key={i} className="flex gap-3">
              <span className="text-muted-foreground w-10 shrink-0 text-right">{Math.round(e.progress)}%</span>
              <span className="text-primary w-16 shrink-0">{e.phase}</span>
              <span className={color[e.level] || "text-foreground"}>{e.message}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/* ----------------------------------------------------------------- Pages */
function PagesTab({ detail }: { detail: Detail }) {
  return (
    <Card>
      <CardContent className="pt-5 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground border-b">
              <th className="pb-2 font-medium">Title</th>
              <th className="pb-2 font-medium">Local file</th>
              <th className="pb-2 font-medium">Source URL</th>
              <th className="pb-2 font-medium text-right">Size</th>
              <th className="pb-2 font-medium text-right">Fidelity</th>
              <th className="pb-2 font-medium text-right">Status</th>
            </tr>
          </thead>
          <tbody>
            {detail.pages.map((p, i) => (
              <tr key={i} className="border-b last:border-0">
                <td className="py-2 pr-3 font-medium">{p.title || "—"}</td>
                <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">{p.output_path || "—"}</td>
                <td className="py-2 pr-3 text-muted-foreground truncate max-w-[220px]">{p.url}</td>
                <td className="py-2 text-right tabular-nums">{formatBytes(p.html_bytes)}</td>
                <td className="py-2 text-right tabular-nums">
                  <PageScore detail={detail} path={p.output_path} />
                </td>
                <td className="py-2 text-right">
                  <Badge variant={p.status === "built" ? "success" : "error"}>{p.status}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function PageScore({ detail, path }: { detail: Detail; path: string }) {
  const qp = detail.quality && detail.quality.pages ? detail.quality.pages.find((x) => x.output_path === path) : undefined;
  if (!qp || qp.score == null) return <>—</>;
  return <span className={ssimColor(qp.score)}>{Math.round(qp.score * 100)}% · {qp.grade}</span>;
}

/* ----------------------------------------------------------------- Assets */
function AssetsTab({ detail }: { detail: Detail }) {
  const [filter, setFilter] = useState("all");
  const cats = useMemo(() => {
    const c: Record<string, number> = {};
    detail.assets.forEach((a) => (c[a.category] = (c[a.category] || 0) + 1));
    return c;
  }, [detail.assets]);
  const list = detail.assets.filter((a) => filter === "all" || a.category === filter);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <FilterChip active={filter === "all"} onClick={() => setFilter("all")}>all · {detail.assets.length}</FilterChip>
        {Object.entries(cats).map(([c, n]) => (
          <FilterChip key={c} active={filter === c} onClick={() => setFilter(c)}>{c} · {n}</FilterChip>
        ))}
      </div>
      <Card>
        <CardContent className="pt-5 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted-foreground border-b">
                <th className="pb-2 font-medium">Local path</th>
                <th className="pb-2 font-medium">Type</th>
                <th className="pb-2 font-medium text-right">Size</th>
                <th className="pb-2 font-medium text-right">Status</th>
              </tr>
            </thead>
            <tbody>
              {list.slice(0, 500).map((a, i) => (
                <tr key={i} className="border-b last:border-0">
                  <td className="py-2 pr-3 font-mono text-xs truncate max-w-[320px]">{a.local_path || a.url}</td>
                  <td className="py-2 pr-3"><Badge variant="muted">{a.category}</Badge></td>
                  <td className="py-2 text-right tabular-nums">{formatBytes(a.size)}</td>
                  <td className="py-2 text-right">
                    <Badge variant={a.status === "ok" ? "success" : a.status === "skipped" ? "warn" : "error"}>
                      {a.status}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.length > 500 && (
            <p className="text-xs text-muted-foreground mt-3">Showing first 500 of {list.length}.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors",
        active ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground hover:text-foreground"
      )}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------- Comparison */
function ComparisonTab({ id, comparisons }: { id: string; comparisons: CompareRecord[] }) {
  const [view, setView] = useState<"side" | "diff">("side");
  const pages = useMemo(() => Array.from(new Set(comparisons.map((c) => c.page_url))), [comparisons]);
  const [page, setPage] = useState(pages[0] || "");
  useEffect(() => {
    if (!page && pages[0]) setPage(pages[0]);
  }, [pages, page]);

  if (!comparisons.length) {
    return (
      <Card><CardContent className="py-12 text-center text-muted-foreground">
        No visual comparison available (quality check disabled or still running).
      </CardContent></Card>
    );
  }
  const items = comparisons.filter((c) => c.page_url === page);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <select
          className="h-9 rounded-md border bg-background px-3 text-sm max-w-full"
          value={page}
          onChange={(e) => setPage(e.target.value)}
        >
          {pages.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <div className="flex rounded-md border overflow-hidden">
          {(["side", "diff"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={cn("px-3 py-1.5 text-sm capitalize", view === v ? "bg-primary text-primary-foreground" : "hover:bg-secondary")}
            >
              {v === "side" ? "Side by side" : "Difference"}
            </button>
          ))}
        </div>
      </div>

      {items.map((c, i) => (
        <Card key={i}>
          <CardContent className="pt-5 space-y-3">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <Monitor className="h-4 w-4 text-primary" />
                <span className="font-medium capitalize">{c.viewport}</span>
                <span className="text-xs text-muted-foreground">{c.width}px</span>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <span className={cn("font-semibold tabular-nums", ssimColor(c.ssim))}>
                  SSIM {Math.round(c.ssim * 100)}%
                </span>
                <span className="text-muted-foreground tabular-nums">
                  {Math.round(c.diff_ratio * 100)}% differing
                </span>
              </div>
            </div>

            {c.issues.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {c.issues.map((iss, k) => (
                  <Badge key={k} variant="warn"><AlertTriangle className="h-3 w-3 mr-1" />{iss}</Badge>
                ))}
              </div>
            )}

            {view === "side" ? (
              <div className="grid grid-cols-2 gap-3">
                <Shot label="Original" src={api.screenshotUrl(id, c.original_png)} />
                <Shot label="Replicated" src={api.screenshotUrl(id, c.generated_png)} />
              </div>
            ) : (
              <Shot label="Difference (red = changed)" src={api.screenshotUrl(id, c.diff_png)} />
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function Shot({ label, src }: { label: string; src: string }) {
  return (
    <div>
      <div className="text-xs font-medium text-muted-foreground mb-1.5">{label}</div>
      <div className="rounded-lg border overflow-hidden bg-secondary/30 max-h-[520px] overflow-y-auto">
        <img src={src} alt={label} className="w-full block" />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Preview */
function PreviewTab({ id, url }: { id: string; url: string }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-sm text-muted-foreground">
          Live preview of the generated local copy. Open the original to compare.
        </p>
        <div className="flex gap-2">
          <a href={api.siteUrl(id)} target="_blank" rel="noreferrer">
            <Button size="sm" variant="outline"><ExternalLink className="h-4 w-4" /> Generated</Button>
          </a>
          <a href={url} target="_blank" rel="noreferrer">
            <Button size="sm" variant="outline"><ExternalLink className="h-4 w-4" /> Original</Button>
          </a>
        </div>
      </div>
      <div className="rounded-xl border overflow-hidden bg-card">
        <iframe src={api.siteUrl(id)} title="Generated site preview" className="w-full h-[70vh]" />
      </div>
    </div>
  );
}
