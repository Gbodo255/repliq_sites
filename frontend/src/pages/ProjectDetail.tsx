import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Download, ExternalLink, Trash2, XCircle, ArrowLeft, Monitor, Image as ImageIcon,
  FileCode2, Layers, Gauge, Terminal, Eye, AlertTriangle, RotateCw, Package, ShieldCheck, Plus, Loader2,
} from "lucide-react";
import { api } from "@/lib/api";
import { useJobProgress } from "@/hooks/useJobProgress";
import { cn, formatBytes, ssimColor } from "@/lib/utils";
import { Button, Progress, Badge } from "@/components/ui";
import { StatusBadge } from "@/components/StatusBadge";
import type { CompareRecord, OutputTarget, ProjectDetail as Detail } from "@/types";

const ALL_TARGETS: { id: OutputTarget; label: string; hint: string }[] = [
  { id: "static", label: "HTML / CSS / JS", hint: "Ouvrir index.html" },
  { id: "react", label: "React (Vite)", hint: "npm install && npm run dev" },
  { id: "nextjs", label: "Next.js", hint: "npm install && npm run dev" },
  { id: "wordpress_theme", label: "Thème WordPress", hint: "Téléverser le thème dans WordPress" },
  { id: "wordpress_headless", label: "WordPress headless (Next.js)", hint: "docker compose up + npm run dev" },
  { id: "figma", label: "Figma (plugin)", hint: "Calques éditables — plugin fourni dans le ZIP" },
];

type TabId = "overview" | "progress" | "pages" | "assets" | "comparison" | "preview";

function Panel({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("rounded-2xl border border-border bg-white", className)}>{children}</div>;
}

export default function ProjectDetail() {
  const { id = "" } = useParams();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [tab, setTab] = useState<TabId>("overview");
  const [error, setError] = useState<string | null>(null);

  const running = detail?.status === "running" || detail?.status === "queued";
  const { events, progress, phase, done } = useJobProgress(id, !!running);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api.getProject(id)
        .then((d) => { if (alive) { setDetail(d); setError(null); } })
        .catch((e) => {
          if (!alive) return;
          const msg = (e as Error).message || "";
          if (/not found|404/i.test(msg)) setDetail(null);
          setError(msg);
        });
    load();
    const t = setInterval(() => { if (alive) load(); }, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [id]);

  useEffect(() => { if (running) setTab("progress"); }, [running]);
  // When the job ends, leave the (now hidden) progress tab for the overview.
  useEffect(() => { if (!running && tab === "progress") setTab("overview"); }, [running, tab]);
  useEffect(() => { if (done) api.getProject(id).then(setDetail).catch(() => {}); }, [done, id]);

  if (error && !detail) {
    return (
      <div className="mx-auto max-w-xl py-20 text-center">
        <p className="font-medium text-destructive">
          {/not found|404/i.test(error) ? "Ce projet n'existe plus sur le serveur." : error}
        </p>
        {/not found|404/i.test(error) && (
          <p className="mt-2 text-sm text-muted">
            Le serveur a redémarré pendant le traitement (sur un hébergement gratuit, cela arrive en cas de
            manque de mémoire ou d'inactivité) et ses fichiers ont été réinitialisés. Relancez la réplication,
            idéalement avec moins de pages ou en mode Page unique.
          </p>
        )}
        <Link to="/app" className="mt-5 inline-block font-medium text-accent">← Retour au tableau de bord</Link>
      </div>
    );
  }
  if (!detail) return <div className="py-20 text-center text-muted">Chargement…</div>;

  const TABS: { id: TabId; label: string; icon: typeof Gauge }[] = [
    { id: "overview", label: "Vue d'ensemble", icon: Gauge },
    ...(running ? [{ id: "progress" as TabId, label: "Progression", icon: Terminal }] : []),
    { id: "pages", label: `Pages (${detail.pages_count})`, icon: FileCode2 },
    { id: "assets", label: `Ressources (${detail.assets_count})`, icon: Layers },
    { id: "comparison", label: "Contrôle visuel", icon: ImageIcon },
    { id: "preview", label: "Aperçu", icon: Eye },
  ];

  async function cancel() { await api.cancel(id).catch(() => {}); }
  async function rerun() {
    if (confirm("Relancer la réplication de ce site avec les mêmes options ? Les fichiers actuels seront régénérés.")) {
      await api.rerun(id).catch((e) => setError((e as Error).message));
      api.getProject(id).then(setDetail).catch(() => {});
    }
  }
  async function remove() {
    if (confirm("Supprimer ce projet et tous ses fichiers ?")) {
      await api.remove(id).catch(() => {});
      window.location.href = "/app";
    }
  }

  return (
    <div className="space-y-6">
      <Link to="/app" className="inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Tableau de bord
      </Link>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="font-display truncate text-[28px] leading-none tracking-tight text-ink">{detail.name}</h1>
            <StatusBadge status={detail.status} />
          </div>
          <a href={detail.url} target="_blank" rel="noreferrer"
             className="mt-2 inline-flex items-center gap-1 text-[13px] text-muted hover:text-accent">
            {detail.url} <ExternalLink className="h-3 w-3" />
          </a>
        </div>
        <div className="flex items-center gap-2">
          {running ? (
            <Button variant="outline" size="sm" onClick={cancel}>
              <XCircle className="h-4 w-4" /> Annuler
            </Button>
          ) : (
            <>
              {detail.has_zip && (
                <a href={api.downloadUrl(id)}>
                  <Button size="sm"><Download className="h-4 w-4" /> ZIP</Button>
                </a>
              )}
              <Button size="sm" variant="outline" onClick={rerun} title="Relancer">
                <RotateCw className="h-4 w-4" /> Relancer
              </Button>
              <a href={api.siteUrl(id)} target="_blank" rel="noreferrer">
                <Button size="sm" variant="outline"><ExternalLink className="h-4 w-4" /> Ouvrir</Button>
              </a>
            </>
          )}
          <Button size="icon" variant="ghost" onClick={remove} title="Supprimer">
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {detail.error && (
        <div className="flex gap-2 rounded-2xl border border-destructive/40 bg-destructive/[0.04] p-4 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {detail.error}
        </div>
      )}

      {running && (
        <Panel className="space-y-2 p-5">
          <div className="flex justify-between text-sm">
            <span className="font-medium capitalize text-ink">{phase || "démarrage"}…</span>
            <span className="font-display tabular-nums text-muted">{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} />
        </Panel>
      )}

      {/* Tabs */}
      <div className="flex gap-1 overflow-x-auto border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "-mb-px flex items-center gap-2 whitespace-nowrap border-b-2 px-4 py-2.5 text-[14px] font-medium transition-colors",
              tab === t.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"
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
    { label: "Ressources", value: detail.assets_count },
    { label: "Poids", value: formatBytes(detail.assets_bytes) },
    { label: "Fidélité", value: q && q.overall_score != null ? `${Math.round(q.overall_score * 100)}% · ${q.grade}`
        : detail.avg_ssim != null ? `${Math.round(detail.avg_ssim * 100)}%` : "—",
      cls: ssimColor(q && q.overall_score != null ? q.overall_score : detail.avg_ssim) },
    { label: "Durée", value: `${detail.duration ?? 0}s` },
  ];
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        {stats.map((s) => (
          <Panel key={s.label} className="p-5">
            <div className="text-[13px] text-faint">{s.label}</div>
            <div className={cn("font-display mt-2 text-[26px] leading-none tabular-nums text-ink", s.cls)}>{s.value}</div>
          </Panel>
        ))}
      </div>

      <OutputsCard detail={detail} running={running} onChange={onChange} />

      {q && (
        <Panel className="flex flex-wrap items-center gap-x-6 gap-y-2 p-5 text-sm">
          <div className="flex items-center gap-2">
            <ShieldCheck className={cn("h-5 w-5", q.external_refs_remaining === 0 ? "text-emerald-500" : "text-amber-500")} />
            <span className="font-medium text-ink">
              {q.external_refs_remaining === 0 ? "Zéro lien ni ressource externe" : `${q.external_refs_remaining} référence(s) externe(s) restante(s)`}
            </span>
          </div>
          <span className="text-muted">{q.external_refs_removed} référence(s) externe(s) neutralisée(s)</span>
          <span className="text-muted">{q.pages.reduce((n, p) => n + p.fixes_applied, 0)} correction(s) de mise en page</span>
          {q.assets_failed > 0 && <span className="text-amber-600">{q.assets_failed} ressource(s) non téléchargée(s)</span>}
        </Panel>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Panel className="space-y-4 p-5">
          <Section title="Technologie détectée">
            <div className="flex flex-wrap gap-2">
              {(a.frameworks?.length ? a.frameworks : ["HTML classique / inconnu"]).map((f) => (
                <Badge key={f} variant="outline">{f}</Badge>
              ))}
            </div>
          </Section>
          <Section title="Composants">
            <div className="flex flex-wrap gap-2">
              {(a.components?.length ? a.components : ["—"]).map((c) => (
                <Badge key={c} variant="muted">{String(c).replace(/_/g, " ")}</Badge>
              ))}
            </div>
          </Section>
          <Section title="Interactions reproduites">
            <div className="flex flex-wrap gap-2">
              {a.interactions && Object.keys(a.interactions).length
                ? Object.entries(a.interactions).map(([k, v]) => (
                    <Badge key={k} variant="default">{k.replace(/_/g, " ")} · {v}</Badge>
                  ))
                : <span className="text-sm text-muted">aucune détectée</span>}
            </div>
          </Section>
        </Panel>

        <Panel className="space-y-4 p-5">
          <Section title="Palette">
            <div className="flex flex-wrap gap-2">
              {(a.palette || []).slice(0, 14).map((c, i) => (
                <div key={i} className="flex items-center gap-1.5 rounded-lg border border-border px-2 py-1">
                  <span className="h-4 w-4 rounded" style={{ background: c as string }} />
                  <span className="mono text-xs text-muted">{c as string}</span>
                </div>
              ))}
              {!a.palette?.length && <span className="text-sm text-muted">—</span>}
            </div>
          </Section>
          <Section title="Polices">
            <div className="flex flex-wrap gap-2">
              {(a.fonts || []).map((f) => <Badge key={f} variant="outline">{f}</Badge>)}
              {!a.fonts?.length && <span className="text-sm text-muted">—</span>}
            </div>
          </Section>
        </Panel>
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
    <Panel className="space-y-3 p-5">
      <Section title="Formats d'export">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ALL_TARGETS.map((t) => {
            const e = byTarget.get(t.id);
            const ready = !!(e && e.zip && !e.error);
            return (
              <div key={t.id} className="flex items-start justify-between gap-3 rounded-xl border border-border p-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-medium text-ink">
                    <Package className="h-4 w-4 shrink-0 text-accent" /> {t.label}
                  </div>
                  <div className="mt-0.5 text-xs text-muted">
                    {e && e.error ? <span className="text-destructive">{e.error}</span>
                      : ready && e ? `${formatBytes(e.size)} · ${t.hint}` : "Pas encore généré"}
                  </div>
                </div>
                {ready ? (
                  <a href={api.downloadUrl(detail.id, t.id)}>
                    <Button size="sm"><Download className="h-4 w-4" /></Button>
                  </a>
                ) : (
                  <Button size="sm" variant="outline" disabled={running || !detail.has_zip || busy !== null}
                    onClick={() => generate(t.id)} title="Générer ce format">
                    {busy === t.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      </Section>
      {err && <p className="text-sm text-destructive">{err}</p>}
    </Panel>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2.5 text-[13px] font-semibold text-ink">{title}</div>
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
    error: "text-destructive", warn: "text-amber-600", success: "text-emerald-600", info: "text-ink",
  };
  return (
    <Panel className="p-5">
      <div ref={ref} className="mono h-96 space-y-1 overflow-y-auto rounded-xl bg-panel p-4 text-xs">
        {events.length === 0 && <div className="text-muted">En attente du moteur…</div>}
        {events.map((e, i) => (
          <div key={i} className="flex gap-3">
            <span className="w-10 shrink-0 text-right text-faint">{Math.round(e.progress)}%</span>
            <span className="w-16 shrink-0 text-accent">{e.phase}</span>
            <span className={color[e.level] || "text-ink"}>{e.message}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

/* ----------------------------------------------------------------- Pages */
function PagesTab({ detail }: { detail: Detail }) {
  return (
    <Panel className="overflow-x-auto p-5">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-faint">
            <th className="pb-2 font-medium">Titre</th>
            <th className="pb-2 font-medium">Fichier local</th>
            <th className="pb-2 font-medium">URL source</th>
            <th className="pb-2 text-right font-medium">Poids</th>
            <th className="pb-2 text-right font-medium">Fidélité</th>
            <th className="pb-2 text-right font-medium">Statut</th>
          </tr>
        </thead>
        <tbody>
          {detail.pages.map((p, i) => (
            <tr key={i} className="border-b border-border last:border-0">
              <td className="py-2 pr-3 font-medium text-ink">{p.title || "—"}</td>
              <td className="mono py-2 pr-3 text-xs text-muted">{p.output_path || "—"}</td>
              <td className="max-w-[220px] truncate py-2 pr-3 text-muted">{p.url}</td>
              <td className="py-2 text-right tabular-nums">{formatBytes(p.html_bytes)}</td>
              <td className="py-2 text-right tabular-nums"><PageScore detail={detail} path={p.output_path} /></td>
              <td className="py-2 text-right">
                <Badge variant={p.status === "built" ? "success" : "error"}>{p.status === "built" ? "construite" : p.status}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
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
        <FilterChip active={filter === "all"} onClick={() => setFilter("all")}>tout · {detail.assets.length}</FilterChip>
        {Object.entries(cats).map(([c, n]) => (
          <FilterChip key={c} active={filter === c} onClick={() => setFilter(c)}>{c} · {n}</FilterChip>
        ))}
      </div>
      <Panel className="overflow-x-auto p-5">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-faint">
              <th className="pb-2 font-medium">Chemin local</th>
              <th className="pb-2 font-medium">Type</th>
              <th className="pb-2 text-right font-medium">Poids</th>
              <th className="pb-2 text-right font-medium">Statut</th>
            </tr>
          </thead>
          <tbody>
            {list.slice(0, 500).map((a, i) => (
              <tr key={i} className="border-b border-border last:border-0">
                <td className="mono max-w-[320px] truncate py-2 pr-3 text-xs text-ink">{a.local_path || a.url}</td>
                <td className="py-2 pr-3"><Badge variant="muted">{a.category}</Badge></td>
                <td className="py-2 text-right tabular-nums">{formatBytes(a.size)}</td>
                <td className="py-2 text-right">
                  <Badge variant={a.status === "ok" ? "success" : a.status === "skipped" ? "warn" : "error"}>{a.status}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.length > 500 && <p className="mt-3 text-xs text-muted">500 premières sur {list.length}.</p>}
      </Panel>
    </div>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors",
        active ? "bg-ink text-white" : "bg-panel text-muted hover:text-ink"
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
  useEffect(() => { if (!page && pages[0]) setPage(pages[0]); }, [pages, page]);

  if (!comparisons.length) {
    return (
      <Panel className="py-12 text-center text-muted">
        Aucune comparaison visuelle disponible (contrôle qualité désactivé ou en cours).
      </Panel>
    );
  }
  const items = comparisons.filter((c) => c.page_url === page);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <select
          className="h-10 max-w-full rounded-xl border border-border-strong bg-white px-3 text-sm text-ink focus-visible:border-ink focus-visible:outline-none"
          value={page}
          onChange={(e) => setPage(e.target.value)}
        >
          {pages.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <div className="flex overflow-hidden rounded-xl border border-border-strong">
          {(["side", "diff"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={cn("px-3.5 py-2 text-sm", view === v ? "bg-ink text-white" : "text-muted hover:bg-panel")}
            >
              {v === "side" ? "Côte à côte" : "Différence"}
            </button>
          ))}
        </div>
      </div>

      {items.map((c, i) => (
        <Panel key={i} className="space-y-3 p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Monitor className="h-4 w-4 text-accent" />
              <span className="font-medium capitalize text-ink">{c.viewport}</span>
              <span className="text-xs text-faint">{c.width}px</span>
            </div>
            <div className="flex items-center gap-3 text-sm">
              <span className={cn("font-display font-semibold tabular-nums", ssimColor(c.ssim))}>
                SSIM {Math.round(c.ssim * 100)}%
              </span>
              <span className="tabular-nums text-muted">{Math.round(c.diff_ratio * 100)}% différent</span>
            </div>
          </div>

          {c.issues.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {c.issues.map((iss, k) => (
                <Badge key={k} variant="warn"><AlertTriangle className="mr-1 h-3 w-3" />{iss}</Badge>
              ))}
            </div>
          )}

          {view === "side" ? (
            <div className="grid grid-cols-2 gap-3">
              <Shot label="Original" src={api.screenshotUrl(id, c.original_png)} />
              <Shot label="Copie" src={api.screenshotUrl(id, c.generated_png)} />
            </div>
          ) : (
            <Shot label="Différence (rouge = modifié)" src={api.screenshotUrl(id, c.diff_png)} />
          )}
        </Panel>
      ))}
    </div>
  );
}

function Shot({ label, src }: { label: string; src: string }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-muted">{label}</div>
      <div className="max-h-[520px] overflow-y-auto overflow-hidden rounded-xl border border-border bg-panel">
        <img src={src} alt={label} className="block w-full" />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Preview */
function PreviewTab({ id, url }: { id: string; url: string }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">Aperçu de la copie locale générée. Ouvrez l'original pour comparer.</p>
        <div className="flex gap-2">
          <a href={api.siteUrl(id)} target="_blank" rel="noreferrer">
            <Button size="sm" variant="outline"><ExternalLink className="h-4 w-4" /> Copie générée</Button>
          </a>
          <a href={url} target="_blank" rel="noreferrer">
            <Button size="sm" variant="outline"><ExternalLink className="h-4 w-4" /> Original</Button>
          </a>
        </div>
      </div>
      <div className="overflow-hidden rounded-2xl border border-border bg-white">
        <iframe src={api.siteUrl(id)} title="Aperçu du site généré" className="h-[70vh] w-full" />
      </div>
    </div>
  );
}
