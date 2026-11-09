import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Rocket, Settings2, Loader2, Zap, Layers, FileText, Globe, Blocks, FileCode2, Atom, Triangle, Database,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button, Input, Label, Checkbox } from "@/components/ui";
import type { OutputTarget, ReplicationMode, ReplicationRequest } from "@/types";
import { cn } from "@/lib/utils";

const MODES: { id: ReplicationMode; title: string; desc: string; icon: typeof Zap }[] = [
  { id: "auto", title: "Auto", desc: "Réglages malins — collez une URL", icon: Zap },
  { id: "full", title: "Complet", desc: "Exploration profonde, tous les écrans", icon: Layers },
  { id: "single_page", title: "Page unique", desc: "Seulement la page donnée", icon: FileText },
];

const ALL_VIEWPORTS = ["desktop", "laptop", "tablet", "mobile", "small"];

type Kind = "site" | "wordpress";
const STACKS: { id: OutputTarget; title: string; desc: string; icon: typeof Zap }[] = [
  { id: "static", title: "HTML / CSS / JS", desc: "Ouvrir index.html", icon: FileCode2 },
  { id: "react", title: "React", desc: "Projet Vite", icon: Atom },
  { id: "nextjs", title: "Next.js", desc: "App Router, SSG", icon: Triangle },
  { id: "wordpress_headless", title: "WordPress headless", desc: "WP + front Next.js", icon: Database },
];

const KINDS = [
  { id: "site" as Kind, title: "Site répliqué", desc: "Copie fidèle, dans la stack de votre choix", icon: Globe },
  { id: "wordpress" as Kind, title: "Thème WordPress", desc: "Thème à téléverser, contenu importé à l'activation", icon: Blocks },
];

const cardBase = "text-left rounded-2xl border bg-white transition-colors";
const sel = (active: boolean) =>
  active ? "border-accent ring-1 ring-accent bg-accent/[0.04]" : "border-border hover:border-ink/25";

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-3 text-[14px] font-semibold text-ink">{children}</h2>;
}

export default function NewReplication() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [mode, setMode] = useState<ReplicationMode>("auto");
  const [advanced, setAdvanced] = useState(false);
  const [maxPages, setMaxPages] = useState(12);
  const [maxDepth, setMaxDepth] = useState(1);
  const [fixCycles, setFixCycles] = useState(2);
  const [keepJs, setKeepJs] = useState(false);
  const [quality, setQuality] = useState(true);
  const [viewports, setViewports] = useState<string[]>(["desktop", "mobile"]);
  const [kind, setKind] = useState<Kind>("site");
  const [stack, setStack] = useState<OutputTarget>("static");
  const [importContent, setImportContent] = useState(true);
  const [keepExternal, setKeepExternal] = useState(false);
  const target: OutputTarget = kind === "wordpress" ? "wordpress_theme" : stack;
  const isWp = target === "wordpress_theme" || target === "wordpress_headless";
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleVp = (v: string) =>
    setViewports((prev) => (prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!url.trim()) {
      setError("Veuillez saisir une URL.");
      return;
    }
    const payload: ReplicationRequest = {
      url: url.trim(), name: name.trim() || undefined, mode,
      outputs: target === "static" ? ["static"] : ["static", target],
      import_wp_content: isWp ? importContent : undefined,
      keep_external_links: keepExternal || undefined,
    };
    if (advanced) {
      payload.max_pages = maxPages;
      payload.max_depth = maxDepth;
      payload.fix_cycles = fixCycles;
      payload.keep_js = keepJs;
      payload.run_quality_check = quality;
      payload.viewports = viewports;
    }
    setSubmitting(true);
    try {
      const res = await api.startReplication(payload);
      navigate(`/app/projects/${res.project_id}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-8">
        <h1 className="font-display text-[34px] leading-none tracking-tight text-ink">Nouvelle réplication</h1>
        <p className="mt-2 text-[15px] text-muted">Collez une URL, le moteur s'occupe du reste.</p>
      </div>

      <form onSubmit={submit} className="space-y-9">
        {/* URL + name */}
        <div className="rounded-2xl border border-border bg-white p-5">
          <Label htmlFor="url">URL du site</Label>
          <Input
            id="url"
            className="mt-1.5 h-12 text-[16px]"
            placeholder="https://exemple.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            autoFocus
          />
          <div className="mt-4">
            <Label htmlFor="name">Nom du projet (optionnel)</Label>
            <Input id="name" className="mt-1.5" placeholder="Ma copie" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
        </div>

        {/* Output */}
        <div>
          <SectionTitle>Format de sortie</SectionTitle>
          <div className="grid gap-3 sm:grid-cols-2">
            {KINDS.map((k) => (
              <button key={k.id} type="button" onClick={() => setKind(k.id)} className={cn(cardBase, sel(kind === k.id), "p-4")}>
                <span className={cn("grid h-9 w-9 place-items-center rounded-lg", kind === k.id ? "bg-accent text-white" : "bg-panel text-muted")}>
                  <k.icon className="h-[18px] w-[18px]" />
                </span>
                <div className="mt-3 text-[15px] font-semibold text-ink">{k.title}</div>
                <div className="mt-0.5 text-[12.5px] leading-snug text-muted">{k.desc}</div>
              </button>
            ))}
          </div>

          {kind === "site" && (
            <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              {STACKS.map((st) => (
                <button key={st.id} type="button" onClick={() => setStack(st.id)} className={cn(cardBase, sel(stack === st.id), "p-3.5")}>
                  <st.icon className={cn("h-4 w-4", stack === st.id ? "text-accent" : "text-muted")} />
                  <div className="mt-2 text-[13.5px] font-semibold text-ink">{st.title}</div>
                  <div className="mt-0.5 text-[11px] leading-tight text-faint">{st.desc}</div>
                </button>
              ))}
            </div>
          )}

          {isWp && (
            <label className="mt-3 flex items-start gap-2.5 rounded-xl bg-panel/60 p-3 text-[13.5px] text-ink">
              <Checkbox className="mt-0.5" checked={importContent} onChange={(e) => setImportContent(e.target.checked)} />
              Importer la base WordPress du site source (articles, catégories, images) si disponible
            </label>
          )}

          <p className="mt-3 text-[12.5px] text-faint">
            La copie ne contient aucun lien ni ressource externe : images, polices, styles et scripts sont locaux.
          </p>
        </div>

        {/* Mode */}
        <div>
          <SectionTitle>Profondeur</SectionTitle>
          <div className="grid gap-3 sm:grid-cols-3">
            {MODES.map((m) => (
              <button key={m.id} type="button" onClick={() => setMode(m.id)} className={cn(cardBase, sel(mode === m.id), "p-4")}>
                <m.icon className={cn("h-5 w-5", mode === m.id ? "text-accent" : "text-muted")} />
                <div className="mt-2.5 text-[15px] font-semibold text-ink">{m.title}</div>
                <div className="mt-0.5 text-[12.5px] leading-snug text-muted">{m.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Advanced */}
        <div>
          <button
            type="button"
            onClick={() => setAdvanced((a) => !a)}
            className="flex items-center gap-2 text-[14px] font-medium text-muted hover:text-ink"
          >
            <Settings2 className="h-4 w-4" />
            {advanced ? "Masquer" : "Afficher"} les options avancées
          </button>

          {advanced && (
            <div className="mt-3 animate-fade-in rounded-2xl border border-border bg-white p-5">
              <p className="mb-4 text-[13px] text-faint">Remplace les réglages du mode choisi.</p>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label>Pages max</Label>
                  <Input className="mt-1.5" type="number" min={1} max={300} value={maxPages} onChange={(e) => setMaxPages(+e.target.value)} />
                </div>
                <div>
                  <Label>Profondeur</Label>
                  <Input className="mt-1.5" type="number" min={0} max={5} value={maxDepth} onChange={(e) => setMaxDepth(+e.target.value)} />
                </div>
                <div>
                  <Label>Corrections</Label>
                  <Input className="mt-1.5" type="number" min={0} max={5} value={fixCycles} onChange={(e) => setFixCycles(+e.target.value)} />
                </div>
              </div>
              <div className="mt-4">
                <Label>Écrans à capturer</Label>
                <div className="mt-2 flex flex-wrap gap-2">
                  {ALL_VIEWPORTS.map((v) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => toggleVp(v)}
                      className={cn(
                        "rounded-lg border px-3 py-1.5 text-[13px] capitalize transition-colors",
                        viewports.includes(v) ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:border-ink/25"
                      )}
                    >
                      {v}
                    </button>
                  ))}
                </div>
              </div>
              <div className="mt-4 space-y-3">
                <label className="flex items-start gap-2.5 text-[13.5px] text-ink">
                  <Checkbox className="mt-0.5" checked={keepJs} onChange={(e) => setKeepJs(e.target.checked)} />
                  Conserver le JavaScript d'origine (par défaut : retiré)
                </label>
                <label className="flex items-start gap-2.5 text-[13.5px] text-ink">
                  <Checkbox className="mt-0.5" checked={keepExternal} onChange={(e) => setKeepExternal(e.target.checked)} />
                  Conserver les liens vers d'autres sites (par défaut : retirés)
                </label>
                <label className="flex items-start gap-2.5 text-[13.5px] text-ink">
                  <Checkbox className="mt-0.5" checked={quality} onChange={(e) => setQuality(e.target.checked)} />
                  Contrôle qualité visuel (comparaison SSIM + correction automatique)
                </label>
              </div>
            </div>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div>
          <Button type="submit" variant="accent" size="lg" className="w-full" disabled={submitting}>
            {submitting ? <Loader2 className="h-5 w-5 animate-spin" /> : <Rocket className="h-5 w-5" />}
            {submitting ? "Démarrage…" : "Lancer la réplication"}
          </Button>
          <p className="mt-3 text-center text-[12px] text-faint">
            Répliquez uniquement des sites que vous possédez ou êtes autorisé à copier. Les adresses privées et
            locales sont bloquées automatiquement.
          </p>
        </div>
      </form>
    </div>
  );
}
