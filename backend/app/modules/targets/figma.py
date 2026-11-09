"""Figma export target.

Turns the verified local copy into an **editable Figma design**. The renderer
walks each generated page and produces a nested tree of design nodes with real
geometry and computed styles (``Renderer.extract_design``). Here we:

* embed every referenced image as base64 (downscaled to keep the bundle light),
* package a small, self-contained **Figma plugin** whose UI already carries this
  project's design data, so the user just imports the plugin and clicks once.

The plugin rebuilds the tree as editable layers: containers -> frames with
**auto-layout** when they were flexbox (direction, gap, padding, alignment),
repeated siblings (cards, nav items) -> **components + instances** (per-instance
text), ``<img>``/background -> image fills, ``<svg>`` -> vectors, text -> real
text layers (font, size, colour).
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from PIL import Image

from app.core.logging import get_logger
from app.modules.exporter.exporter import zip_project

log = get_logger("figma")

_MAX_IMG_DIM = 1600          # px; downscale larger raster images
_MAX_ONE_IMG = 2_500_000     # bytes of encoded image to embed for a single node
_MAX_TOTAL_IMG = 14_000_000  # bytes of embedded images for the whole export


def _file_url_to_path(src: str) -> Path | None:
    try:
        u = urlparse(src)
        if u.scheme != "file":
            return None
        return Path(url2pathname(unquote(u.path)))
    except Exception:  # noqa: BLE001
        return None


def _encode_image(path: Path) -> str | None:
    """Return base64 of a (possibly downscaled) PNG/JPEG for this image file."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:  # noqa: BLE001 - not a raster PIL can read
        return base64.b64encode(raw).decode("ascii") if len(raw) <= _MAX_ONE_IMG else None
    if max(im.size) > _MAX_IMG_DIM:
        im.thumbnail((_MAX_IMG_DIM, _MAX_IMG_DIM))
    has_alpha = im.mode in ("RGBA", "LA", "P")
    buf = io.BytesIO()
    if has_alpha:
        im.convert("RGBA").save(buf, format="PNG", optimize=True)
    else:
        im.convert("RGB").save(buf, format="JPEG", quality=82, optimize=True)
    data = buf.getvalue()
    if len(data) > _MAX_ONE_IMG and not has_alpha:
        im.thumbnail((1100, 1100))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=72, optimize=True)
        data = buf.getvalue()
    return base64.b64encode(data).decode("ascii") if len(data) <= _MAX_ONE_IMG else None


def _embed_node(node: dict, budget: dict) -> None:
    if node.get("t") == "IMG":
        if node.get("svg"):
            return
        src = node.get("src") or ""
        path = _file_url_to_path(src)
        if path is None or not path.is_file():
            node["_drop"] = True
            return
        if path.suffix.lower() == ".svg":
            try:
                node["svg"] = path.read_text(encoding="utf-8", errors="replace")
                node.pop("src", None)
            except OSError:
                node["_drop"] = True
            return
        if budget["t"] >= _MAX_TOTAL_IMG:
            node["_drop"] = True
            return
        b64 = _encode_image(path)
        if not b64:
            node["_drop"] = True
            return
        budget["t"] += len(b64)
        node["b64"] = b64
        node.pop("src", None)
        return
    kids = node.get("children")
    if kids:
        for c in kids:
            _embed_node(c, budget)
        node["children"] = [c for c in kids if not c.get("_drop")]


def embed_tree(root: dict) -> int:
    """Embed every image in the design tree as base64, in place. Returns bytes used."""
    budget = {"t": 0}
    _embed_node(root, budget)
    return budget["t"]


def _count_nodes(node: dict) -> int:
    return 1 + sum(_count_nodes(c) for c in (node.get("children") or []))


# --------------------------------------------------------------------------- #
# The Figma plugin (self-contained, data baked into the UI).
# --------------------------------------------------------------------------- #
_MANIFEST = {
    "name": "Replicator → Figma",
    "id": "replicator-figma-import",
    "api": "1.0.0",
    "main": "code.js",
    "ui": "ui.html",
    "editorType": ["figma"],
}

_CODE_JS = r"""/* Replicator → Figma — rebuilds a replicated page as an editable, nested design
   (hierarchy + auto-layout + components for repeated blocks). */
const STYLE = {100:'Thin',200:'ExtraLight',300:'Light',400:'Regular',500:'Medium',600:'SemiBold',700:'Bold',800:'ExtraBold',900:'Black'};
function styleFor(w){ return STYLE[Math.round((w||400)/100)*100] || 'Regular'; }
function solid(c){ return { type:'SOLID', color:{ r:c[0], g:c[1], b:c[2] }, opacity: c.length>3 ? c[3] : 1 }; }

function collectFonts(n, want){
  if(n.t === 'TEXT'){ const f = { family:n.font||'Inter', style:styleFor(n.weight) }; want[f.family+'|'+f.style] = f; }
  if(n.children) for(const c of n.children) collectFonts(c, want);
}

async function build(doc){
  const pages = (doc && doc.pages) || [];
  const want = { 'Inter|Regular': { family:'Inter', style:'Regular' } };
  for(const p of pages) if(p.root) collectFonts(p.root, want);
  const ok = {};
  await Promise.all(Object.keys(want).map(async (k) => { try { await figma.loadFontAsync(want[k]); ok[k] = want[k]; } catch(e){} }));
  let fallback = ok['Inter|Regular'];
  if(!fallback){ fallback = { family:'Roboto', style:'Regular' }; try { await figma.loadFontAsync(fallback); } catch(e){} }
  const ctx = { ok, fallback };

  const made = []; let ox = 0;
  for(const p of pages){
    const page = figma.createFrame();
    page.name = p.name || 'Page';
    page.resize(Math.max(1, p.w||1200), Math.max(1, p.h||800));
    page.x = ox; page.y = 0;
    page.fills = [solid(p.bg || [1,1,1,1])];
    page.clipsContent = true;
    appendChildren(page, (p.root && p.root.children) || [], false, false, ctx);
    made.push(page);
    ox += (p.w||1200) + 160;
  }
  if(made.length){ figma.currentPage.selection = made; figma.viewport.scrollAndZoomIntoView(made); }
  return made.length;
}

function makeText(n, ctx){
  const t = figma.createText();
  t.fontName = ctx.ok[(n.font||'Inter')+'|'+styleFor(n.weight)] || ctx.fallback;
  t.characters = n.text || '';
  t.fontSize = Math.max(1, n.size||16);
  t.fills = [solid(n.color||[0,0,0,1])];
  try { t.resize(Math.max(1, n.w), t.height); t.textAutoResize = 'HEIGHT'; } catch(e){}
  t.textAlignHorizontal = { left:'LEFT', right:'RIGHT', center:'CENTER', justify:'JUSTIFIED' }[n.align] || 'LEFT';
  if(n.lh){ try { t.lineHeight = { value:n.lh, unit:'PIXELS' }; } catch(e){} }
  if(n.ls){ try { t.letterSpacing = { value:n.ls, unit:'PIXELS' }; } catch(e){} }
  if(n.opacity != null && n.opacity < 1) t.opacity = n.opacity;
  return t;
}
function makeImage(n){
  if(n.svg){
    let node; try { node = figma.createNodeFromSvg(n.svg); } catch(e){ node = figma.createRectangle(); }
    try { node.resize(Math.max(1, n.w), Math.max(1, n.h)); } catch(e){}
    if(n.opacity != null && n.opacity < 1) node.opacity = n.opacity;
    return node;
  }
  const rect = figma.createRectangle();
  try { rect.resize(Math.max(1, n.w), Math.max(1, n.h)); } catch(e){}
  if(n.b64){ const img = figma.createImage(figma.base64Decode(n.b64)); rect.fills = [{ type:'IMAGE', scaleMode: n.fit==='cover'?'FILL':'FIT', imageHash: img.hash }]; }
  else rect.fills = [];
  if(n.radius) rect.cornerRadius = n.radius;
  if(n.opacity != null && n.opacity < 1) rect.opacity = n.opacity;
  return rect;
}
function makeFrame(n, ctx, noComp){
  const f = figma.createFrame();
  try { f.resize(Math.max(1, n.w), Math.max(1, n.h)); } catch(e){}
  f.fills = n.fill ? [solid(n.fill)] : [];
  if(n.radius) f.cornerRadius = n.radius;
  if(n.borderColor){ f.strokes = [solid(n.borderColor)]; f.strokeWeight = n.borderW || 1; }
  if(n.shadow){ const s = n.shadow; f.effects = [{ type:'DROP_SHADOW', visible:true, blendMode:'NORMAL', color:{ r:s.color[0], g:s.color[1], b:s.color[2], a:s.color[3] }, offset:{ x:s.x, y:s.y }, radius:s.blur||0, spread:s.spread||0 }]; }
  if(n.opacity != null && n.opacity < 1) f.opacity = n.opacity;
  f.clipsContent = !!n.clip;
  if(n.layout){
    f.layoutMode = n.layout;
    f.itemSpacing = Math.max(0, Math.round(n.gap||0));
    if(n.pad){ f.paddingTop = n.pad[0]||0; f.paddingRight = n.pad[1]||0; f.paddingBottom = n.pad[2]||0; f.paddingLeft = n.pad[3]||0; }
    f.primaryAxisAlignItems = n.primary || 'MIN';
    f.counterAxisAlignItems = (n.counter === 'BASELINE' ? 'MIN' : (n.counter || 'MIN'));
    f.primaryAxisSizingMode = 'FIXED'; f.counterAxisSizingMode = 'FIXED';
    if(n.wrap){ try { f.layoutWrap = 'WRAP'; } catch(e){} }
  } else {
    f.layoutMode = 'NONE';
  }
  appendChildren(f, n.children || [], !!n.layout, noComp, ctx);
  return f;
}
function buildNode(n, ctx, noComp){
  if(n.t === 'TEXT') return makeText(n, ctx);
  if(n.t === 'IMG') return makeImage(n);
  return makeFrame(n, ctx, noComp);
}
function place(el, n, autoParent){ if(!autoParent){ el.x = n.x || 0; el.y = n.y || 0; } }

function appendChildren(parent, children, autoParent, noComp, ctx){
  const N = children.length;
  let i = 0;
  while(i < N){
    const n = children[i];
    let j = i;
    if(!noComp && n.t === 'FRAME' && n.sig){
      while(j+1 < N && children[j+1].t === 'FRAME' && children[j+1].sig === n.sig) j++;
    }
    if(j > i){
      try { componentRun(parent, children.slice(i, j+1), autoParent, ctx); i = j+1; continue; }
      catch(e){ /* fall through to plain build */ }
    }
    const el = buildNode(n, ctx, noComp);
    place(el, n, autoParent);
    parent.appendChild(el);
    i++;
  }
}

function componentRun(parent, run, autoParent, ctx){
  const first = makeFrame(run[0], ctx, true);   // no nested components inside a component
  place(first, run[0], autoParent);
  parent.appendChild(first);
  const comp = figma.createComponentFromNode(first);
  comp.name = ((run[0].sig || 'Bloc').split(':')[0]) || 'Bloc';
  for(let k=1; k<run.length; k++){
    const inst = comp.createInstance();
    place(inst, run[k], autoParent);
    parent.appendChild(inst);
    try { overrideInstance(inst, run[k], ctx); } catch(e){}
  }
}

function dataTexts(n, out){ if(n.t === 'TEXT'){ out.push(n); return; } if(n.children) for(const c of n.children) dataTexts(c, out); }
function instTexts(node, out){ if(node.type === 'TEXT'){ out.push(node); return; } if('children' in node) for(const c of node.children) instTexts(c, out); }
function overrideInstance(inst, dataNode, ctx){
  const dl = []; dataTexts(dataNode, dl);
  const il = []; instTexts(inst, il);
  const m = Math.min(dl.length, il.length);
  for(let x=0; x<m; x++){
    const d = dl[x], ln = il[x];
    try { ln.fontName = ctx.ok[(d.font||'Inter')+'|'+styleFor(d.weight)] || ctx.fallback; ln.characters = d.text || ''; ln.fills = [solid(d.color||[0,0,0,1])]; } catch(e){}
  }
}

figma.showUI(__html__, { width: 380, height: 300 });
figma.ui.onmessage = async (msg) => {
  if(msg.type === 'build'){
    try { const n = await build(msg.data); figma.notify('Import terminé — ' + n + ' page(s) ✓'); figma.ui.postMessage({ type:'done' }); }
    catch(e){ figma.notify('Erreur : ' + (e.message || e)); figma.ui.postMessage({ type:'error', message: String(e.message || e) }); }
  } else if(msg.type === 'cancel'){
    figma.closePlugin();
  }
};
"""

_UI_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body{font:13px/1.5 Inter,system-ui,sans-serif;margin:0;padding:18px;color:#0b0b0d}
  h2{font-size:15px;margin:0 0 4px}
  p{color:#555;margin:0 0 14px}
  .meta{background:#f5f5f3;border-radius:10px;padding:10px 12px;margin-bottom:14px;font-size:12px;color:#333}
  button{font:inherit;font-weight:600;border:0;border-radius:10px;padding:11px 16px;cursor:pointer}
  .go{background:#2337ff;color:#fff;width:100%}
  .go:disabled{opacity:.5;cursor:default}
  .cancel{background:transparent;color:#777;width:100%;margin-top:8px}
  .status{margin-top:12px;font-size:12px;color:#555;min-height:16px}
</style></head><body>
  <h2>Replicator → Figma</h2>
  <p>Reconstruit la copie répliquée en calques éditables (auto-layout + composants).</p>
  <div class="meta" id="meta"></div>
  <button class="go" id="go">Importer dans Figma</button>
  <button class="cancel" id="cancel">Fermer</button>
  <div class="status" id="status"></div>
  <script>
    var DATA = __DATA__;
    var pages = (DATA.pages||[]);
    function countNodes(n){ var c=1; if(n.children) for(var i=0;i<n.children.length;i++) c+=countNodes(n.children[i]); return c; }
    var nodes = pages.reduce(function(a,p){ return a + (p.root?countNodes(p.root):0); }, 0);
    document.getElementById('meta').textContent =
      (DATA.name||'Projet') + ' — ' + pages.length + ' page(s), ' + nodes + ' calque(s)';
    document.getElementById('go').onclick = function(){
      this.disabled = true;
      document.getElementById('status').textContent = 'Construction…';
      parent.postMessage({ pluginMessage: { type:'build', data: DATA } }, '*');
    };
    document.getElementById('cancel').onclick = function(){
      parent.postMessage({ pluginMessage: { type:'cancel' } }, '*');
    };
    onmessage = function(e){
      var m = e.data.pluginMessage; if(!m) return;
      if(m.type==='done') document.getElementById('status').textContent = 'Terminé ✓';
      if(m.type==='error') document.getElementById('status').textContent = 'Erreur : ' + m.message;
    };
  </script>
</body></html>
"""

_README = """# Export Figma — {name}

Ce dossier contient un **plugin Figma** prêt à l'emploi qui reconstruit votre
copie répliquée en **calques éditables** : frames imbriquées, **auto-layout**
sur les conteneurs flex, **composants** pour les blocs répétés (cartes, items),
textes, images et vecteurs.

## Importer dans Figma (bureau)

1. Ouvrez l'app **Figma** (bureau), dans un fichier de design.
2. Menu **Plugins → Development → Import plugin from manifest…**
3. Sélectionnez le fichier `plugin/manifest.json` de ce dossier.
4. Lancez **Plugins → Development → Replicator → Figma**.
5. Cliquez **Importer dans Figma**.

Chaque page devient une *frame* à l'échelle réelle. Les conteneurs flex
deviennent des frames en **auto-layout** (vous changez un espacement, tout se
réaligne) ; les blocs répétés deviennent un **composant + instances** (le texte
de chaque instance est conservé) ; les textes restent éditables, les images des
remplissages d'image, les icônes SVG des vecteurs.

- `plugin/` — le plugin (manifest, code, interface avec vos données intégrées)
- `design.json` — les données brutes du design (pour référence / réutilisation)

> Les polices doivent être disponibles dans votre espace Figma (les polices
> Google Fonts le sont) ; sinon le texte retombe sur une substitution.
"""


def package_figma(doc: dict, out_dir: Path, zip_path: Path, *, arc_root: str = "figma") -> dict:
    """Write the design JSON + a ready-to-run Figma plugin, then zip it."""
    plugin = out_dir / "plugin"
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "manifest.json").write_text(json.dumps(_MANIFEST, indent=2), encoding="utf-8")
    (plugin / "code.js").write_text(_CODE_JS, encoding="utf-8")
    data_json = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    safe = data_json.replace("</", "<\\/")      # don't break the inline <script>
    (plugin / "ui.html").write_text(_UI_TEMPLATE.replace("__DATA__", safe), encoding="utf-8")
    (out_dir / "design.json").write_text(data_json, encoding="utf-8")
    (out_dir / "README.md").write_text(_README.format(name=doc.get("name", "site")), encoding="utf-8")
    zip_project(out_dir, zip_path, arc_root=arc_root)
    pages = doc.get("pages", [])
    return {"pages": len(pages), "nodes": sum(_count_nodes(p["root"]) for p in pages if p.get("root"))}
