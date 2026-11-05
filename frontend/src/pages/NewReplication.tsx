import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Rocket, Settings2, Loader2, Zap, Layers, FileText, Globe, Blocks, FileCode2, Atom, Triangle, Database,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  Button, Card, CardContent, CardHeader, CardTitle, CardDescription,
  Input, Label, Select, Checkbox,
} from "@/components/ui";
import type { OutputTarget, ReplicationMode, ReplicationRequest } from "@/types";
import { cn } from "@/lib/utils";

const MODES: { id: ReplicationMode; title: string; desc: string; icon: typeof Zap }[] = [
  { id: "auto", title: "Auto", desc: "Smart defaults — just paste a URL", icon: Zap },
  { id: "full", title: "Full", desc: "Deep crawl, all breakpoints, quality loop", icon: Layers },
  { id: "single_page", title: "Single page", desc: "Only the page you give", icon: FileText },
];

const ALL_VIEWPORTS = ["desktop", "laptop", "tablet", "mobile", "small"];

type Kind = "site" | "wordpress";
const STACKS: { id: OutputTarget; title: string; desc: string; icon: typeof Zap }[] = [
  { id: "static", title: "HTML / CSS / JS", desc: "Open index.html, nothing to install", icon: FileCode2 },
  { id: "react", title: "React", desc: "Vite project: npm install && npm run dev", icon: Atom },
  { id: "nextjs", title: "Next.js", desc: "App Router, pre-rendered pages", icon: Triangle },
  { id: "wordpress_headless", title: "WordPress headless", desc: "WordPress content + Next.js front-end", icon: Database },
];

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
      setError("Please enter a URL.");
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
      navigate(`/projects/${res.project_id}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">New replication</h1>
        <p className="text-muted-foreground mt-1">Paste a URL and let the engine do the rest.</p>
      </div>

      <form onSubmit={submit} className="space-y-6">
        <Card>
          <CardContent className="pt-5 space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="url">Website URL</Label>
              <Input
                id="url"
                placeholder="https://example.com"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="name">Project name (optional)</Label>
              <Input id="name" placeholder="My site copy" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
          </CardContent>
        </Card>

        <div className="space-y-3">
          <Label>Output</Label>
          <div className="grid sm:grid-cols-2 gap-3">
            {([
              { id: "site", title: "Replicated site", desc: "Pixel-faithful copy in the stack of your choice", icon: Globe },
              { id: "wordpress", title: "WordPress template", desc: "Theme to upload in WordPress, content imported on activation", icon: Blocks },
            ] as const).map((k) => (
              <button
                key={k.id}
                type="button"
                onClick={() => setKind(k.id)}
                className={cn(
                  "text-left rounded-xl border p-4 transition-colors",
                  kind === k.id ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-secondary"
                )}
              >
                <k.icon className={cn("h-5 w-5 mb-2", kind === k.id ? "text-primary" : "text-muted-foreground")} />
                <div className="font-semibold">{k.title}</div>
                <div className="text-xs text-muted-foreground mt-0.5">{k.desc}</div>
              </button>
            ))}
          </div>
          {kind === "site" && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {STACKS.map((st) => (
                <button
                  key={st.id}
                  type="button"
                  onClick={() => setStack(st.id)}
                  className={cn(
                    "text-left rounded-lg border p-3 transition-colors",
                    stack === st.id ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-secondary"
                  )}
                >
                  <st.icon className={cn("h-4 w-4 mb-1.5", stack === st.id ? "text-primary" : "text-muted-foreground")} />
                  <div className="text-sm font-semibold">{st.title}</div>
                  <div className="text-[11px] leading-tight text-muted-foreground mt-0.5">{st.desc}</div>
                </button>
              ))}
            </div>
          )}
          {isWp && (
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={importContent} onChange={(e) => setImportContent(e.target.checked)} />
              Import the WordPress database of the source (posts, categories, tags, images) when available
            </label>
          )}
          <p className="text-xs text-muted-foreground">
            The copy contains no external link or resource: every image, font, stylesheet and script is local.
          </p>
        </div>

        <div className="grid sm:grid-cols-3 gap-3">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setMode(m.id)}
              className={cn(
                "text-left rounded-xl border p-4 transition-colors",
                mode === m.id ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-secondary"
              )}
            >
              <m.icon className={cn("h-5 w-5 mb-2", mode === m.id ? "text-primary" : "text-muted-foreground")} />
              <div className="font-semibold">{m.title}</div>
              <div className="text-xs text-muted-foreground mt-0.5">{m.desc}</div>
            </button>
          ))}
        </div>

        <div>
          <button
            type="button"
            onClick={() => setAdvanced((a) => !a)}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <Settings2 className="h-4 w-4" />
            {advanced ? "Hide" : "Show"} advanced options
          </button>

          {advanced && (
            <Card className="mt-3 animate-fade-in">
              <CardHeader>
                <CardTitle className="text-base">Advanced</CardTitle>
                <CardDescription>Overrides the selected mode's defaults.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-3 gap-3">
                  <div className="space-y-1.5">
                    <Label>Max pages</Label>
                    <Input type="number" min={1} max={300} value={maxPages}
                      onChange={(e) => setMaxPages(+e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Max depth</Label>
                    <Input type="number" min={0} max={5} value={maxDepth}
                      onChange={(e) => setMaxDepth(+e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Fix cycles</Label>
                    <Input type="number" min={0} max={5} value={fixCycles}
                      onChange={(e) => setFixCycles(+e.target.value)} />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label>Breakpoints to capture</Label>
                  <div className="flex flex-wrap gap-2">
                    {ALL_VIEWPORTS.map((v) => (
                      <button
                        key={v}
                        type="button"
                        onClick={() => toggleVp(v)}
                        className={cn(
                          "rounded-md border px-3 py-1.5 text-sm capitalize transition-colors",
                          viewports.includes(v) ? "border-primary bg-primary/10 text-primary" : "hover:bg-secondary"
                        )}
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={keepJs} onChange={(e) => setKeepJs(e.target.checked)} />
                  Keep original JavaScript (default: strip framework runtime)
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={keepExternal} onChange={(e) => setKeepExternal(e.target.checked)} />
                  Keep links to other websites (default: removed)
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={quality} onChange={(e) => setQuality(e.target.checked)} />
                  Run visual quality check (SSIM comparison + auto-fix)
                </label>
              </CardContent>
            </Card>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <Button type="submit" size="lg" className="w-full" disabled={submitting}>
          {submitting ? <Loader2 className="h-5 w-5 animate-spin" /> : <Rocket className="h-5 w-5" />}
          {submitting ? "Starting…" : "Launch replication"}
        </Button>
        <p className="text-xs text-muted-foreground text-center">
          Only replicate sites you own or are authorised to copy. Private, local and metadata
          addresses are blocked automatically.
        </p>
      </form>
    </div>
  );
}
