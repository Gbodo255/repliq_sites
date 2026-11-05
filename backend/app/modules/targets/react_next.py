"""React (Vite) and Next.js (App Router) project generators.

Both produce a ready-to-run project: ``npm install`` then ``npm run dev``.
Pages are real JSX components; the markup shared by every page becomes a
layout component; the original per-page stylesheets are rendered as React 19
hoistable ``<link>`` / ``<style>`` elements in their original order, and the
original ``<html>`` / ``<body>`` attributes are applied before first paint.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.modules.targets.common import (
    attrs_script,
    copy_static,
    head_jsx,
    js_route,
    nest_body_selectors,
    page_middle_jsx,
    pascal,
    shell_jsx,
    write,
)
from app.modules.targets.jsx import JsxContext
from app.modules.targets.model import SiteModel

# Exact pins: the generated project installs the very versions it was built
# and verified with.
VERSIONS = {
    "react": "19.3.1",
    "react-dom": "19.3.1",
    "react-router-dom": "7.18.5",
    "vite": "8.3.6",
    "@vitejs/plugin-react": "6.2.1",
    "next": "16.4.5",
    "html-react-parser": "6.1.9",
}


def _pkg_name(model: SiteModel, suffix: str) -> str:
    import re
    base = re.sub(r"[^a-z0-9-]+", "-", model.site_name.lower()).strip("-") or "replicated-site"
    return f"{base[:40]}-{suffix}"


def _rewrite_css_tree(root: Path, fn) -> None:
    for p in root.rglob("*.css"):
        text = p.read_text(encoding="utf-8", errors="replace")
        new = fn(text)
        if new != text:
            p.write_text(new, encoding="utf-8")


# ----------------------------------------------------------------- React
def build_react(model: SiteModel, site_dir: Path, out: Path) -> dict:
    ctx = JsxContext(ssr=False)
    copy_static(site_dir, out / "public")
    _rewrite_css_tree(out / "public", nest_body_selectors)

    used: set[str] = set()
    routes = []
    for page in model.pages:
        comp = pascal(page.key or "home", used)
        head = nest_body_selectors(head_jsx(page))
        middle = page_middle_jsx(page, ctx)
        write(out / "src" / "pages" / f"{comp}.jsx", _component(comp, head, middle, js_route(page.key)))
        routes.append((js_route(page.key), comp))

    layout = shell_jsx(model.shell, ctx)
    write(out / "src" / "components" / "Layout.jsx",
          "// Markup shared by every page of the original site (header, footer, wrappers).\n"
          "export default function Layout({ children }) {\n  return (\n    <>" + layout + "</>\n  );\n}\n")

    imports = "\n".join(f'import {c} from "./pages/{c}.jsx";' for _, c in routes)
    route_el = "\n".join(f'          <Route path="{r}" element={{<{c} />}} />' for r, c in routes)
    home_comp = routes[0][1] if routes else "Home"
    write(out / "src" / "App.jsx", f'''import {{ useEffect }} from "react";
import {{ BrowserRouter, Routes, Route }} from "react-router-dom";
import Layout from "./components/Layout.jsx";
{imports}

function useInteractions() {{
  useEffect(() => {{
    if (window.ReplicatorInteractions) {{ window.ReplicatorInteractions.init(); return; }}
    const s = document.createElement("script");
    s.src = "/js/interactions.js";
    s.defer = true;
    document.body.appendChild(s);
  }}, []);
}}

export default function App() {{
  useInteractions();
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
{route_el}
          <Route path="*" element={{<{home_comp} />}} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}}
''')
    write(out / "src" / "main.jsx", '''import { createRoot } from "react-dom/client";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(<App />);
''')
    write(out / "index.html", f'''<!DOCTYPE html>
<html lang="{model.lang}">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{_html_escape(model.home.title if model.pages else model.site_name)}</title>
    <link rel="stylesheet" href="/css/responsive.css" />
    <style>#root{{display:contents}}</style>
  </head>
  <body>
    <script>{attrs_script(model)}</script>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
''')
    write(out / "vite.config.js", '''import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, open: true },
  preview: { port: 4173 },
  build: { chunkSizeWarningLimit: 4096 },
});
''')
    write(out / "package.json", json.dumps({
        "name": _pkg_name(model, "react"),
        "private": True,
        "version": "1.0.0",
        "type": "module",
        "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
        "dependencies": {k: VERSIONS[k] for k in ("react", "react-dom", "react-router-dom")},
        "devDependencies": {k: VERSIONS[k] for k in ("vite", "@vitejs/plugin-react")},
    }, indent=2) + "\n")
    write(out / ".gitignore", "node_modules\ndist\n")
    write(out / "README.md", _readme_react(model, routes))
    return {"pages": len(routes), "raw_fallbacks": ctx.raw_fallbacks}


# ----------------------------------------------------------------- Next.js
def build_next(model: SiteModel, site_dir: Path, out: Path) -> dict:
    ctx = JsxContext(ssr=True)
    copy_static(site_dir, out / "public")
    used: set[str] = set()
    routes = []
    for page in model.pages:
        comp = pascal(page.key or "home", used)
        head = head_jsx(page, with_title=False)
        middle = page_middle_jsx(page, ctx)
        write(out / "components" / "pages" / f"{comp}.jsx", _component(comp, head, middle, js_route(page.key)))
        meta = {"title": page.title}
        if page.description:
            meta["description"] = page.description
        route_dir = out / "app" if not page.key else out / "app" / page.key
        write(route_dir / "page.jsx", f'''import {comp} from "@/components/pages/{comp}.jsx";

export const metadata = {json.dumps(meta, ensure_ascii=False)};

export default function Page() {{
  return <{comp} />;
}}
''')
        routes.append((js_route(page.key), comp))

    shell = shell_jsx(model.shell, ctx)
    write(out / "components" / "SiteShell.jsx",
          "// Markup shared by every page of the original site (header, footer, wrappers).\n"
          "export default function SiteShell({ children }) {\n  return (\n    <>" + shell + "</>\n  );\n}\n")
    write(out / "app" / "layout.jsx", f'''import Script from "next/script";
import SiteShell from "@/components/SiteShell.jsx";

const ATTRS = {json.dumps(attrs_script(model), ensure_ascii=False)};

export const metadata = {{ title: {json.dumps(model.site_name, ensure_ascii=False)} }};

export default function RootLayout({{ children }}) {{
  return (
    <html lang={json.dumps(model.lang)} suppressHydrationWarning>
      <head>
        <Script id="rx-attrs" strategy="beforeInteractive">{{ATTRS}}</Script>
        <link rel="stylesheet" href="/css/responsive.css" precedence="low" />
      </head>
      <body suppressHydrationWarning>
        <SiteShell>{{children}}</SiteShell>
        <Script src="/js/interactions.js" strategy="afterInteractive" />
      </body>
    </html>
  );
}}
''')
    write(out / "app" / "not-found.jsx", f'''export const metadata = {{ title: "404" }};

export default function NotFound() {{
  return (
    <main style={{{{ padding: "6rem 1.5rem", textAlign: "center" }}}}>
      <h1>404</h1>
      <p><a href="/">{_js_text("← Accueil")}</a></p>
    </main>
  );
}}
''')
    write(out / "next.config.mjs", '''/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  images: { unoptimized: true },
};

export default nextConfig;
''')
    write(out / "jsconfig.json", json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./*"]}}}, indent=2) + "\n")
    write(out / "package.json", json.dumps({
        "name": _pkg_name(model, "next"),
        "private": True,
        "version": "1.0.0",
        "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
        "dependencies": {k: VERSIONS[k] for k in ("next", "react", "react-dom")},
    }, indent=2) + "\n")
    write(out / ".gitignore", "node_modules\n.next\nout\n")
    write(out / "README.md", _readme_next(model, routes))
    return {"pages": len(routes), "raw_fallbacks": ctx.raw_fallbacks}


# ----------------------------------------------------------------- helpers
def _component(name: str, head: str, middle: str, source: str) -> str:
    return (
        f"// Replicated page: {source}\n"
        f"export default function {name}() {{\n"
        "  return (\n"
        "    <>\n"
        f"      {head}\n"
        f"      {middle}\n"
        "    </>\n"
        "  );\n"
        "}\n"
    )


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _js_text(s: str) -> str:
    return "{" + json.dumps(s, ensure_ascii=False) + "}"


def _readme_react(model: SiteModel, routes) -> str:
    pages = "\n".join(f"- `{r}` → `src/pages/{c}.jsx`" for r, c in routes)
    return f"""# {model.site_name} — React (Vite)

Projet React généré par le Universal Website Replication Engine à partir de
{model.source_url}.

## Lancer

```bash
npm install
npm run dev
```

Le site s'ouvre sur http://localhost:5173.

Build de production :

```bash
npm run build
npm run preview
```

Le dossier `dist/` est une SPA : configurez votre hébergeur pour renvoyer
`index.html` sur toutes les routes (Netlify, Vercel, Nginx `try_files`).

## Structure

- `src/components/Layout.jsx` : en-tête / pied de page communs à toutes les pages
- `src/pages/*.jsx` : une page = un composant
- `public/` : images, polices, CSS et JS d'origine (100 % local, aucun lien externe)

## Pages

{pages}
"""


def _readme_next(model: SiteModel, routes) -> str:
    pages = "\n".join(f"- `{r}` → `components/pages/{c}.jsx`" for r, c in routes)
    return f"""# {model.site_name} — Next.js

Projet Next.js (App Router) généré par le Universal Website Replication
Engine à partir de {model.source_url}. Toutes les pages sont pré-rendues
(SSG).

## Lancer

```bash
npm install
npm run dev
```

Le site s'ouvre sur http://localhost:3000.

Production :

```bash
npm run build
npm start
```

## Structure

- `app/layout.jsx` : layout racine (attributs `<html>`/`<body>` d'origine)
- `components/SiteShell.jsx` : en-tête / pied de page communs
- `components/pages/*.jsx` : une page = un composant
- `public/` : images, polices, CSS et JS d'origine (100 % local, aucun lien externe)

## Pages

{pages}
"""
