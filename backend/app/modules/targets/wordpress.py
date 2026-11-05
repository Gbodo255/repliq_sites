"""WordPress outputs.

* ``build_wp_theme``: a classic theme, installable from *Appearance > Themes >
  Add New > Upload*.  On activation it creates every replicated page (exact
  HTML in a Custom HTML block, so it stays editable), imports the posts /
  categories / tags / featured images of a WordPress source, sets the front
  page and pretty permalinks.  Header / footer shared by all pages live in the
  theme; per-page original styles are printed in ``wp_head`` in their
  original order.  Every asset ships inside the theme: no external URL.
* ``build_wp_headless``: a content plugin for WordPress (same importer, exact
  HTML exposed as ``rx_html`` in the REST API) plus a Next.js front-end that
  renders it, with a bundled fallback so the front-end runs even before
  WordPress is up.  A ``docker-compose.yml`` starts a ready WordPress.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

from app.core.utils import slugify
from app.modules.targets import wp_php
from app.modules.targets.common import (
    attrs_script,
    copy_static,
    detok,
    head_jsx,
    js_route,
    pascal,
    shell_jsx,
    write,
)
from app.modules.targets.jsx import JsxContext, style_object
from app.modules.targets.model import SiteModel
from app.modules.targets.react_next import VERSIONS

THEME_VERSION = "1.0.0"


def _names(model: SiteModel) -> tuple[str, str, str]:
    base = slugify(model.site_name)[:32].strip("-") or "site"
    slug = f"rx-{base}"
    prefix = "rx_" + re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return slug, prefix, model.site_name


def _wp_slugs(model: SiteModel) -> dict[str, str]:
    keys = {p.key for p in model.pages}
    out = {}
    for p in model.pages:
        out[p.key] = p.key if p.key else ("home" if "home" not in keys else "front-page")
    return out


def _clean_title(title: str, site: str) -> str:
    for sep in (" – ", " - ", " | ", " — ", " · "):
        if sep in title:
            head, _, tail = title.rpartition(sep)
            if tail.strip() == site.strip() and head.strip():
                return head.strip()
    return title


def _pages_json(model: SiteModel, content_fn=lambda html: html) -> list[dict]:
    slugs = _wp_slugs(model)
    return [{
        "key": p.key,
        "slug": slugs[p.key],
        "title": _clean_title(p.title, model.site_name) or model.site_name,
        "doc_title": p.title or model.site_name,
        "description": p.description,
        "html_attrs": p.html_attrs,
        "body_attrs": p.body_attrs,
        "content": content_fn(p.middle_html()),
    } for p in model.pages]


def _zip_dir(src: Path, out_zip: Path, arc_root: str) -> None:
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                zf.write(path, f"{arc_root}/{path.relative_to(src).as_posix()}")


def _screenshot(png: bytes | None, dest: Path) -> None:
    if not png:
        return
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("RGB")
        w = im.width
        h = min(im.height, int(w * 0.75))
        im = im.crop((0, 0, w, h)).resize((1200, 900))
        im.save(dest, "PNG", optimize=True)
    except Exception:  # noqa: BLE001 - cosmetic only
        pass


def _common_body_classes(model: SiteModel) -> list[str]:
    sets = [set((p.body_attrs.get("class") or "").split()) for p in model.pages]
    if not sets:
        return []
    common = set.intersection(*sets)
    # Page-specific WordPress markers must not leak onto posts/archives.
    return sorted(c for c in common if not re.match(r"^(home|page|page-id-\d+|page-template.*|postid-\d+|single.*|wp-singular|elementor-page.*"
                                                   r"|.*transparent.*|.*page-builder.*)$", c))


def _compose(service_volume: str, mount_target: str, activate_cmd: str, title: str) -> str:
    return f"""# Local WordPress for testing: docker compose up -d  ->  http://localhost:8080
# Admin: http://localhost:8080/wp-admin  (user: admin / password: admin - local only, change it)
services:
  db:
    image: mariadb:11
    restart: unless-stopped
    environment:
      MARIADB_DATABASE: wordpress
      MARIADB_USER: wordpress
      MARIADB_PASSWORD: wordpress
      MARIADB_ROOT_PASSWORD: rootpass
    volumes:
      - db:/var/lib/mysql
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 5s
      timeout: 5s
      retries: 30

  wordpress:
    image: wordpress:6-php8.3-apache
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8080:80"
    environment: &wpenv
      WORDPRESS_DB_HOST: db
      WORDPRESS_DB_USER: wordpress
      WORDPRESS_DB_PASSWORD: wordpress
      WORDPRESS_DB_NAME: wordpress
    volumes:
      - wp:/var/www/html
      - {service_volume}:{mount_target}:ro

  setup:
    image: wordpress:cli-php8.3
    user: "33:33"
    depends_on:
      db:
        condition: service_healthy
      wordpress:
        condition: service_started
    environment: *wpenv
    volumes:
      - wp:/var/www/html
      - {service_volume}:{mount_target}:ro
    entrypoint: ["sh", "-c"]
    command:
      - |
        until [ -f /var/www/html/wp-config.php ]; do sleep 2; done
        until wp db check >/dev/null 2>&1; do sleep 2; done
        wp core is-installed || wp core install --url=http://localhost:8080 --title={json.dumps(title)} --admin_user=admin --admin_password=admin --admin_email=admin@example.com --skip-email
        wp rewrite structure '/%postname%/'
        {activate_cmd}
        echo "WordPress ready on http://localhost:8080"
    restart: "no"

volumes:
  db:
  wp:
"""


# ----------------------------------------------------------------- theme
def build_wp_theme(model: SiteModel, site_dir: Path, out: Path, posts: dict | None = None,
                   screenshot: bytes | None = None) -> dict:
    slug, prefix, name = _names(model)
    theme = out / ".build" / slug          # zipped below; only the installable zip is shipped
    if theme.exists():
        shutil.rmtree(theme)
    copy_static(site_dir, theme)
    vals = dict(PREFIX=prefix, NAME=name.replace("*/", ""), VERSION=THEME_VERSION)

    write(theme / "style.css", f"""/*
Theme Name: {vals['NAME']} (Replicated)
Author: Universal Website Replication Engine
Description: Pixel-faithful WordPress theme replicated from the original site. Activating it creates the pages and imports the content automatically.
Version: {THEME_VERSION}
Requires at least: 6.0
Tested up to: 6.8
Requires PHP: 7.4
License: GPL-2.0-or-later
License URI: license.txt
Text Domain: {prefix}
*/
""")
    write(theme / "functions.php", wp_php.fill(wp_php.THEME_FUNCTIONS, **vals))
    write(theme / "inc" / "importer.php", wp_php.fill(wp_php.IMPORTER, **vals))
    write(theme / "inc" / "template.php", wp_php.fill(wp_php.THEME_TEMPLATE_PHP, **vals))
    write(theme / "header.php", wp_php.fill(wp_php.THEME_HEADER, **vals))
    write(theme / "footer.php", wp_php.fill(wp_php.THEME_FOOTER, **vals))
    write(theme / "page.php", wp_php.fill(wp_php.THEME_PAGE, **vals))
    write(theme / "single.php", wp_php.fill(wp_php.THEME_SINGLE, **vals))
    write(theme / "index.php", wp_php.fill(wp_php.THEME_INDEX, **vals))
    write(theme / "404.php", wp_php.fill(wp_php.THEME_404, **vals))
    write(theme / "css" / "rx-entry.css", wp_php.ENTRY_CSS)
    write(theme / "license.txt", "GPL-2.0-or-later. Replicated site content belongs to its owner.\n")

    data = theme / "inc" / "data"
    write(data / "pages.json", json.dumps(_pages_json(model), ensure_ascii=False, indent=1))
    write(data / "posts.json", json.dumps(posts or {"posts": [], "categories": [], "tags": []},
                                         ensure_ascii=False, indent=1))
    write(data / "site.json", json.dumps({"name": name,
                                         "common_body_classes": _common_body_classes(model)},
                                        ensure_ascii=False, indent=1))
    for p in model.pages:
        write(theme / "inc" / "heads" / f"{p.key or 'home'}.html",
              "\n".join(h.html() for h in p.head) + "\n")
    write(theme / "inc" / "heads" / "_default.html", "\n".join(h.html() for h in model.default_head()) + "\n")
    write(theme / "inc" / "parts" / "open.html", model.shell.open_html())
    write(theme / "inc" / "parts" / "close.html", model.shell.close_html())
    write(theme / "inc" / "parts" / "post-open.html", model.post_chrome.open_html())
    write(theme / "inc" / "parts" / "post-close.html", model.post_chrome.close_html())
    _screenshot(screenshot, theme / "screenshot.png")

    _zip_dir(theme, out / f"{slug}.zip", slug)
    shutil.rmtree(out / ".build", ignore_errors=True)
    write(out / "docker-compose.yml", _compose(f"./{slug}.zip", f"/tmp/{slug}.zip",
                                               f"wp theme install /tmp/{slug}.zip --force --activate && "
                                               f"wp eval '{prefix}_import_content();'",
                                               name))
    write(out / "README.md", f"""# {name} — thème WordPress

Thème WordPress généré par le Universal Website Replication Engine à partir
de {model.source_url}.

## Installation dans votre WordPress

1. *Apparence → Thèmes → Ajouter → Téléverser un thème* : choisissez
   **`{slug}.zip`**, puis *Installer* et *Activer*.
2. C'est tout : à l'activation, le thème crée automatiquement les
   {len(model.pages)} page(s) répliquée(s){', importe les ' + str(len((posts or {}).get('posts', []))) + ' article(s), catégories et images' if posts and posts.get('posts') else ''},
   définit la page d'accueil et active les permaliens `/%postname%/`.

Le contenu reste modifiable dans l'éditeur (bloc *HTML personnalisé*).
*Apparence → Replicator* permet de réimporter le contenu à tout moment.

Aucune ressource externe : images, polices, CSS et JS sont dans le thème.

## Tester en local (Docker)

```bash
docker compose up -d
```

Puis http://localhost:8080 (admin : http://localhost:8080/wp-admin,
identifiant `admin` / mot de passe `admin` — local uniquement).
""")
    return {"theme": slug, "zip": f"{slug}.zip", "pages": len(model.pages),
            "posts": len((posts or {}).get("posts", []))}


# ----------------------------------------------------------------- headless
_IMPORTANT_RE = re.compile(r"!\s*important", re.I)


def _extract_important(html: str, scope: str) -> str:
    """Move ``!important`` inline declarations into a scoped ``<style>``.

    React (used to render the headless content) cannot express ``!important``
    in a style object; an attribute-scoped rule keeps the exact cascade.
    """
    if "important" not in html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    rules, n = [], 0
    for el in soup.find_all(style=True):
        st = el["style"]
        if not _IMPORTANT_RE.search(st):
            continue
        keep, imp = [], []
        for decl in st.split(";"):
            if ":" not in decl:
                continue
            (imp if _IMPORTANT_RE.search(decl) else keep).append(decl.strip())
        n += 1
        rid = f"{scope}-{n}"
        el["data-rx-i"] = rid
        if keep:
            el["style"] = "; ".join(keep)
        else:
            del el["style"]
        rules.append(f'[data-rx-i="{rid}"]{{{"; ".join(imp)}}}')
    if not rules:
        return html
    return f"<style>{''.join(rules)}</style>" + str(soup)


def _headless_url(key: str) -> str:
    return js_route(key)


def _headless_detok(html: str, blog: str = "blog") -> str:
    html = detok(html, "", _headless_url)
    return re.sub(r"\{\{POST:([^}]*)\}\}", lambda m: f"/{blog}/{m.group(1)}", html)


def build_wp_headless(model: SiteModel, site_dir: Path, out: Path, posts: dict | None = None) -> dict:
    slug, prefix, name = _names(model)
    plugin_slug = f"{slug}-content"
    keys = {p.key for p in model.pages}
    blog = next(b for b in ("blog", "articles", "posts-archive") if b not in keys)
    vals = dict(PREFIX=prefix, NAME=name.replace("*/", ""), VERSION=THEME_VERSION, BLOG=blog)
    posts = posts or {"posts": [], "categories": [], "tags": []}

    # ---- WordPress side: content plugin
    wp_dir = out / "wordpress"
    plugin = out / ".build" / plugin_slug  # zipped below; only the installable zip is shipped
    if plugin.exists():
        shutil.rmtree(plugin)
    pages = _pages_json(model, lambda h: _extract_important(h, "c"))
    write(plugin / f"{plugin_slug}.php", wp_php.fill(wp_php.HEADLESS_PLUGIN, **vals))
    write(plugin / "importer.php", wp_php.fill(wp_php.IMPORTER, **vals))
    write(plugin / "data" / "pages.json", json.dumps(pages, ensure_ascii=False, indent=1))
    write(plugin / "data" / "posts.json", json.dumps(posts, ensure_ascii=False, indent=1))
    for post in posts.get("posts", []):        # featured images for the media library
        rel = (post.get("featured") or "").replace("{{A}}/", "")
        if rel and (site_dir / rel).is_file():
            (plugin / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(site_dir / rel, plugin / rel)
    wp_dir.mkdir(parents=True, exist_ok=True)
    _zip_dir(plugin, wp_dir / f"{plugin_slug}.zip", plugin_slug)
    shutil.rmtree(out / ".build", ignore_errors=True)

    # ---- Front-end: Next.js
    fe = out / "frontend"
    copy_static(site_dir, fe / "public")
    ctx = JsxContext(ssr=True)
    write(fe / "content" / "pages.json", json.dumps([
        {"key": p["key"], "slug": p["slug"], "title": p["doc_title"], "description": p["description"],
         "html": _headless_detok(p["content"], blog)} for p in pages], ensure_ascii=False, indent=1))
    write(fe / "content" / "posts.json", json.dumps([
        {**{k: v for k, v in post.items() if k != "content"},
         "featured": _headless_detok(post.get("featured", ""), blog),
         "html": _headless_detok(_extract_important(post.get("content", ""), "p"), blog)}
        for post in posts.get("posts", [])], ensure_ascii=False, indent=1))

    used: set[str] = set()
    routes = []
    for p in model.pages:
        comp = pascal(p.key or "home", used)
        write(fe / "components" / "heads" / f"{comp}.jsx",
              f"export default function {comp}Head() {{\n  return <>{head_jsx(p, with_title=False)}</>;\n}}\n")
        route_dir = fe / "app" if not p.key else fe / "app" / p.key
        write(route_dir / "page.jsx", f'''import Head from "@/components/heads/{comp}.jsx";
import {{ getPage }} from "@/lib/wordpress";
import {{ renderHtml }} from "@/lib/render";

export const revalidate = 60;

export async function generateMetadata() {{
  const page = await getPage({json.dumps(p.key)});
  return {{ title: page.title, description: page.description || undefined }};
}}

export default async function Page() {{
  const page = await getPage({json.dumps(p.key)});
  return (
    <>
      <Head />
      {{renderHtml(page.html)}}
    </>
  );
}}
''')
        routes.append((js_route(p.key), comp))
    home_comp = routes[0][1] if routes else "Home"
    from app.modules.targets.model import PageModel as _PM
    default_page = _PM(key="default", title="", source_url="", output_path="", html_attrs={}, body_attrs={},
                       head=model.default_head(), description="", soup=None)
    write(fe / "components" / "heads" / "Default.jsx",
          "export default function DefaultHead() {\n  return <>" + head_jsx(default_page, with_title=False) + "</>;\n}\n")
    write(fe / "components" / "PostChrome.jsx",
          "// Site header / footer around posts and archives.\n"
          "export default function PostChrome({ children }) {\n  return (\n    <>"
          + shell_jsx(model.post_chrome, ctx) + "</>\n  );\n}\n")

    write(fe / "components" / "SiteShell.jsx",
          "// Markup shared by every page of the original site (header, footer, wrappers).\n"
          "export default function SiteShell({ children }) {\n  return (\n    <>"
          + shell_jsx(model.shell, ctx) + "</>\n  );\n}\n")
    write(fe / "app" / "layout.jsx", f'''import Script from "next/script";
import SiteShell from "@/components/SiteShell.jsx";

const ATTRS = {json.dumps(attrs_script(model), ensure_ascii=False)};

export const metadata = {{ title: {json.dumps(name, ensure_ascii=False)} }};

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
    write(fe / "app" / blog / "page.jsx", f'''import Head from "@/components/heads/Default.jsx";
import PostChrome from "@/components/PostChrome.jsx";
import {{ getPosts }} from "@/lib/wordpress";

export const revalidate = 60;
export const metadata = {{ title: "Blog" }};

export default async function Blog() {{
  const posts = await getPosts();
  return (
    <>
      <Head />
      <link rel="stylesheet" href="/css/rx-entry.css" precedence="default" />
      <PostChrome>
      <main className="rx-entry rx-archive">
        <h1 className="rx-title">Blog</h1>
        <div className="rx-grid">
          {{posts.map((p) => (
            <article className="rx-card" key={{p.slug}}>
              {{p.featured ? <a className="rx-thumb" href={{`/{blog}/${{p.slug}}`}}><img src={{p.featured}} alt="" /></a> : null}}
              <h2><a href={{`/{blog}/${{p.slug}}`}}>{{p.title}}</a></h2>
              <p className="rx-meta">{{p.date ? new Date(p.date).toLocaleDateString() : ""}}</p>
              <p className="rx-excerpt">{{p.excerpt}}</p>
            </article>
          ))}}
        </div>
      </main>
      </PostChrome>
    </>
  );
}}
''')
    write(fe / "app" / blog / "[slug]" / "page.jsx", f'''import {{ notFound }} from "next/navigation";
import Head from "@/components/heads/Default.jsx";
import PostChrome from "@/components/PostChrome.jsx";
import {{ getPost, getPosts }} from "@/lib/wordpress";
import {{ renderHtml }} from "@/lib/render";

export const revalidate = 60;
export const dynamicParams = true;

export async function generateStaticParams() {{
  const posts = await getPosts();
  return posts.map((p) => ({{ slug: p.slug }}));
}}

export async function generateMetadata({{ params }}) {{
  const {{ slug }} = await params;
  const post = await getPost(slug);
  return {{ title: post ? post.title : "Blog" }};
}}

export default async function Post({{ params }}) {{
  const {{ slug }} = await params;
  const post = await getPost(slug);
  if (!post) notFound();
  return (
    <>
      <Head />
      <link rel="stylesheet" href="/css/rx-entry.css" precedence="default" />
      <PostChrome>
      <main className="rx-entry">
        <article>
          <h1 className="rx-title">{{post.title}}</h1>
          <p className="rx-meta">{{post.date ? new Date(post.date).toLocaleDateString() : ""}}</p>
          {{post.featured ? <figure className="rx-featured"><img src={{post.featured}} alt="" /></figure> : null}}
          <div className="rx-content">{{renderHtml(post.html)}}</div>
        </article>
      </main>
      </PostChrome>
    </>
  );
}}
''')
    write(fe / "app" / "not-found.jsx", '''export default function NotFound() {
  return (
    <main style={{ padding: "6rem 1.5rem", textAlign: "center" }}>
      <h1>404</h1>
      <p><a href="/">{"\\u2190"}</a></p>
    </main>
  );
}
''')
    write(fe / "public" / "css" / "rx-entry.css", wp_php.ENTRY_CSS)
    write(fe / "lib" / "wordpress.js", '''// Data access: WordPress REST API first, bundled content as a fallback so the
// front-end always works (even before WordPress is installed).
import fallbackPages from "@/content/pages.json";
import fallbackPosts from "@/content/posts.json";

const WP = (process.env.WORDPRESS_URL || "http://localhost:8080").replace(/\\/+$/, "");

async function wp(route, params = {}) {
  const qs = new URLSearchParams({ rest_route: route, ...params }).toString();
  try {
    const res = await fetch(`${WP}/?${qs}`, { next: { revalidate: 60 }, signal: AbortSignal.timeout(4000) });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function decode(s) {
  return String(s || "")
    .replace(/<[^>]+>/g, "")
    .replace(/&#(\\d+);/g, (_, n) => String.fromCharCode(Number(n)))
    .replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#039;|&apos;/g, "'")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">");
}

export async function getPage(key) {
  const local = fallbackPages.find((p) => p.key === key) || fallbackPages[0];
  const data = await wp("/wp/v2/pages", { slug: local.slug, _fields: "title,rx_html,rx_key,excerpt" });
  if (Array.isArray(data) && data.length && typeof data[0].rx_html === "string" && data[0].rx_html.trim()) {
    return {
      title: local.title || decode(data[0].title && data[0].title.rendered),
      description: local.description,
      html: data[0].rx_html,
    };
  }
  return local;
}

export async function getPosts() {
  const data = await wp("/wp/v2/posts", { per_page: "100", _embed: "1", _fields: "slug,title,date,excerpt,_links,_embedded" });
  if (Array.isArray(data) && data.length) {
    return data.map((p) => {
      const local = fallbackPosts.find((x) => x.slug === p.slug);
      const media = p._embedded && p._embedded["wp:featuredmedia"];
      return {
        slug: p.slug,
        title: decode(p.title && p.title.rendered),
        date: p.date,
        excerpt: decode(p.excerpt && p.excerpt.rendered),
        featured: (local && local.featured) || (media && media[0] && media[0].source_url) || "",
      };
    });
  }
  return fallbackPosts;
}

export async function getPost(slug) {
  const data = await wp("/wp/v2/posts", { slug, _fields: "slug,title,date,rx_html" });
  const local = fallbackPosts.find((p) => p.slug === slug);
  if (Array.isArray(data) && data.length) {
    return {
      slug,
      title: decode(data[0].title && data[0].title.rendered),
      date: data[0].date,
      featured: local ? local.featured : "",
      html: data[0].rx_html || "",
    };
  }
  return local || null;
}
''')
    write(fe / "lib" / "render.jsx", '''// HTML from WordPress -> React elements, rendered on the server.
import parse, { attributesToProps, domToReact } from "html-react-parser";
import render from "dom-serializer";

const NO_WS = new Set(["table", "thead", "tbody", "tfoot", "tr", "colgroup", "select", "optgroup"]);

const options = {
  replace(node) {
    if (node.type === "text" && node.parent && NO_WS.has(node.parent.name) && !node.data.trim()) {
      return <></>;
    }
    if (node.type === "comment" || (node.type === "script" && node.name === "script")) {
      return <></>;
    }
    if (node.name === "svg" || node.name === "math") {
      const Tag = node.name;
      return <Tag {...attributesToProps(node.attribs, node.name)} dangerouslySetInnerHTML={{ __html: render(node.children) }} />;
    }
    if (node.name === "noscript" || node.name === "template") {
      return <></>;
    }
    return undefined;
  },
};

export function renderHtml(html) {
  return parse(String(html || ""), options);
}

export { domToReact };
''')
    write(fe / "next.config.mjs", '''/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  images: { unoptimized: true },
};

export default nextConfig;
''')
    write(fe / "jsconfig.json", json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./*"]}}}, indent=2) + "\n")
    write(fe / "package.json", json.dumps({
        "name": f"{slug}-headless",
        "private": True,
        "version": "1.0.0",
        "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
        "dependencies": {
            "next": VERSIONS["next"], "react": VERSIONS["react"], "react-dom": VERSIONS["react-dom"],
            "html-react-parser": VERSIONS["html-react-parser"], "dom-serializer": "3.1.1",
        },
    }, indent=2) + "\n")
    write(fe / ".env.local.example", "# URL of the WordPress install (docker compose: http://localhost:8080)\nWORDPRESS_URL=http://localhost:8080\n")
    write(fe / ".env.local", "WORDPRESS_URL=http://localhost:8080\n")
    write(fe / ".gitignore", "node_modules\n.next\n")

    write(out / "docker-compose.yml", _compose(f"./wordpress/{plugin_slug}.zip", f"/tmp/{plugin_slug}.zip",
                                               f"wp plugin install /tmp/{plugin_slug}.zip --force --activate",
                                               name))
    write(out / "README.md", f"""# {name} — WordPress headless

Généré par le Universal Website Replication Engine à partir de
{model.source_url}.

- `wordpress/{plugin_slug}.zip` : extension WordPress qui crée les pages
  (et les articles importés) et expose leur HTML exact via l'API REST.
- `frontend/` : site Next.js qui affiche le contenu WordPress à l'identique.

## Démarrage rapide

1. WordPress (Docker) :

   ```bash
   docker compose up -d
   ```

   WordPress est prêt sur http://localhost:8080 avec l'extension activée et le
   contenu importé (admin : `admin` / `admin`, local uniquement).

   *Avec votre propre WordPress* : *Extensions → Ajouter → Téléverser* →
   `wordpress/{plugin_slug}.zip` → *Activer*.

2. Front-end :

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   http://localhost:3000. L'URL WordPress se règle dans `frontend/.env.local`
   (`WORDPRESS_URL`). Si WordPress n'est pas joignable, le front-end utilise
   le contenu embarqué : il fonctionne toujours.

Les modifications faites dans WordPress apparaissent sur le front-end en
moins de 60 secondes (ISR).

## Routes

{chr(10).join(f"- `{r}`" for r, _ in routes)}
- `/{blog}` et `/{blog}/[slug]` : articles WordPress
""")
    return {"plugin": plugin_slug, "pages": len(routes), "posts": len(posts.get("posts", [])),
            "raw_fallbacks": ctx.raw_fallbacks}


__all__ = ["build_wp_theme", "build_wp_headless", "style_object"]
