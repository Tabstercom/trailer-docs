#!/usr/bin/env python3
"""
Build the Trailer Docs single-file offline app.

Reads:  content/<manual>/manual.md   (prose -> Guide / Illustrated)
        content/<manual>/checklist.yaml (condensed tick steps + reference cards)
        content/<manual>/images/*        (inlined as base64 for offline use)
        build/manuals.yaml               (master list + status)
        VERSION                          (version number shown in the app)

Writes: site/Trailer Docs.html          (one self-contained file)

Usage:  python3 build/build.py
"""
import os, re, json, base64, subprocess, mimetypes, html, sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "content")
SITE = os.path.join(ROOT, "site")
VERSION_FILE = os.path.join(ROOT, "VERSION")

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")


def version():
    """Version string from the VERSION file at the repo root."""
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except FileNotFoundError:
        return "0.0.0"


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def image_data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def md_to_guide(mdpath, images):
    """Markdown -> (guide_html, toc_list). Callout fenced divs -> styled callouts."""
    out = subprocess.run(
        ["pandoc", mdpath, "-f", "markdown+fenced_divs", "-t", "html", "--wrap=none"],
        capture_output=True, text=True, encoding="utf-8")
    body = out.stdout

    # merge any split lists (defensive)
    body = re.sub(r'</ol>\s*<ol[^>]*>', '', body)
    body = re.sub(r'</ul>\s*<ul[^>]*>', '', body)

    # fenced-div callouts -> callout markup
    def open_callout(kind, label):
        return (f'<div class="callout {kind}">'
                f'<span class="clabel">{label}</span>')
    body = re.sub(r'<div class="important">\s*',
                  lambda m: open_callout("imp", "Important"), body)
    body = re.sub(r'<div class="note">\s*',
                  lambda m: open_callout("note", "Note"), body)

    # inline images as data URIs; tag them so Guide can hide them
    def repl_img(m):
        src = m.group(1)
        name = os.path.basename(src)
        uri = images.get(name)
        if not uri:
            return ''  # missing image -> drop silently (photos come later)
        return f'<img class="photo" src="{uri}" loading="lazy" alt="">'
    body = re.sub(r'<img[^>]*src="([^"]+)"[^>]*/?>', repl_img, body)

    # strip any <strong> that pandoc left wrapping a heading
    body = re.sub(r'<h([12])([^>]*)><strong>(.*?)</strong></h\1>',
                  r'<h\1\2>\3</h\1>', body)

    # TOC from h1
    toc = re.findall(r'<h1 id="([^"]+)">(.*?)</h1>', body)
    toc = [(hid, re.sub("<.*?>", "", t)) for hid, t in toc]
    return body, toc


def build_manual(m):
    mid = m["id"]
    d = os.path.join(CONTENT, mid)
    if m.get("status") != "ready":
        return {**m, "guide": "", "toc": [], "checklist": {"phases": [], "reference": []}}

    # images
    images = {}
    imgdir = os.path.join(d, "images")
    if os.path.isdir(imgdir):
        for fn in sorted(os.listdir(imgdir)):
            fp = os.path.join(imgdir, fn)
            if os.path.isfile(fp):
                images[fn] = image_data_uri(fp)

    guide, toc = md_to_guide(os.path.join(d, "manual.md"), images)
    cl = load_yaml(os.path.join(d, "checklist.yaml"))
    return {
        "id": mid, "title": m["title"], "subtitle": m["subtitle"],
        "status": "ready",
        "guide": guide, "toc": toc,
        "hasPhotos": bool(images),
        "checklist": {"phases": cl.get("phases", []), "reference": cl.get("reference", [])},
    }


def step_text(st):
    """A checklist step is a plain string or {t: "...", flag: imp|win}."""
    if isinstance(st, dict):
        return st.get("t", ""), st.get("flag", "")
    return str(st), ""


def static_fallback(manuals, build):
    """Readable HTML for viewers that don't run JavaScript.

    iOS previews an HTML attachment in Quick Look, which renders markup but
    never executes scripts — without this the app paints nothing at all. The
    real app overwrites #app on load, so this is only ever seen with JS off.
    Photos are dropped: they'd double the file size for a fallback view.
    """
    parts = ['<div class="wrap nojs">',
             '<div class="nojs-note"><b>Preview mode.</b> This page is being shown '
             "without JavaScript, so the tabs and the tap-through checklist aren't "
             'running — the full text of every manual is below. On iPhone, attachments '
             'preview this way; open the file in a browser (or ask for the hosted link) '
             'to get the app.</div>']

    for m in manuals:
        if m.get("status") != "ready":
            continue
        parts.append(f'<h2 class="nojs-title">{html.escape(m["title"])}</h2>')
        parts.append(f'<p class="nojs-sub">{html.escape(m["subtitle"])}</p>')

        guide = re.sub(r'<img[^>]*>', '', m.get("guide", ""))
        parts.append(f'<div class="doc reading">{guide}</div>')

        phases = m["checklist"].get("phases") or []
        if phases:
            parts.append('<h2 class="nojs-title">Checklist</h2>')
            for ph in phases:
                parts.append(f'<h3 class="nojs-phase">{html.escape(ph.get("title",""))}</h3><ul>')
                for st in ph.get("steps", []):
                    txt, flag = step_text(st)
                    cls = ' class="imp"' if flag == "imp" else ''
                    parts.append(f'<li{cls}>{txt}</li>')
                parts.append('</ul>')

        for card in (m["checklist"].get("reference") or []):
            parts.append(f'<h3 class="nojs-phase">{html.escape(card.get("title",""))}</h3>'
                         f'<div class="card">{card.get("body","")}</div>')

    parts.append(f'<footer>Version {build["version"]} &middot; built {build["stamp"]}</footer>')
    parts.append('</div>')
    return "\n".join(parts)


# ---------- PWA (hosted copy) ----------
# The standalone file stays exactly as it was; these extras only apply to the
# copy served over HTTPS, where a service worker can run. Installed to the home
# screen, that copy works with no signal at all -- which is the whole point on
# site.

PWA_HEAD = """<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icon-180.png">
"""

PWA_SCRIPT = """<script>
if('serviceWorker' in navigator){
  window.addEventListener('load', function(){
    navigator.serviceWorker.register('sw.js').catch(function(){});
  });
}
</script>
"""

MANIFEST = {
    "name": "Trailer Docs",
    "short_name": "Trailer Docs",
    "description": "On-site documentation for the scanning trailer.",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#f3f1ec",
    "theme_color": "#1b4965",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png",
         "purpose": "any maskable"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png",
         "purpose": "any maskable"},
    ],
}

SW_JS = """// Trailer Docs service worker -- offline shell for the hosted copy.
// The cache name carries the build version, so publishing a new version
// installs a fresh cache and drops the old one.
const CACHE = 'trailer-docs-__VERSION__';
const ASSETS = ['./', './index.html', './manifest.webmanifest',
                './icon-180.png', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Cache first: on set there is often a weak signal, and waiting on the network
// is worse than serving the copy we already have. A background fetch refreshes
// the cache for next launch.
self.addEventListener('fetch', e => {
  const req = e.request;
  if(req.method !== 'GET') return;
  e.respondWith(
    caches.match(req, {ignoreSearch: true}).then(hit => {
      const net = fetch(req).then(res => {
        if(res && res.ok && new URL(req.url).origin === self.location.origin){
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
        }
        return res;
      }).catch(() => null);
      if(hit) return hit;
      return net.then(res => res || (req.mode === 'navigate'
        ? caches.match('./index.html') : Response.error()));
    })
  );
});
"""


def write_icons(outdir):
    """Accent-coloured tile with a white tick. Home-screen icon on iOS/Android.

    Drawn rather than shipped as binary so there's no image to keep in sync
    with the palette, and the bytes are identical build to build.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  (Pillow not installed - skipping icons)")
        return

    for size in (180, 192, 512):
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22),
                            fill=(27, 73, 101, 255))
        # tick kept inside the middle 80% so maskable crops don't clip it
        w = max(2, int(size * 0.085))
        pts = [(size * 0.30, size * 0.52), (size * 0.44, size * 0.66),
               (size * 0.71, size * 0.36)]
        d.line(pts, fill=(255, 255, 255, 255), width=w, joint="curve")
        for p in (pts[0], pts[-1]):
            d.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2],
                      fill=(255, 255, 255, 255))
        img.save(os.path.join(outdir, f"icon-{size}.png"), "PNG", optimize=True)


def write_pwa(outdir, standalone_html, build):
    """Write the hosted copy: index.html + manifest + service worker + icons."""
    hosted = standalone_html.replace("</head>", PWA_HEAD + "</head>", 1)
    hosted = hosted.replace("</body>", PWA_SCRIPT + "</body>", 1)
    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(hosted)

    with open(os.path.join(outdir, "manifest.webmanifest"), "w", encoding="utf-8") as f:
        json.dump(MANIFEST, f, indent=2)

    with open(os.path.join(outdir, "sw.js"), "w", encoding="utf-8") as f:
        f.write(SW_JS.replace("__VERSION__", build["version"]))

    write_icons(outdir)


def main():
    cfg = load_yaml(os.path.join(ROOT, "build", "manuals.yaml"))
    manuals = [build_manual(m) for m in cfg["manuals"]]

    now = datetime.now()
    build = {
        "version": version(),
        "date": now.strftime("%Y-%m-%d"),
        "stamp": now.strftime("%Y-%m-%d %H:%M"),
    }

    tpl = open(os.path.join(ROOT, "build", "template.html"), encoding="utf-8").read()
    data = json.dumps(manuals, ensure_ascii=False)
    # guard </script> inside data
    data = data.replace("</", "<\\/")
    payload = ("window.MANUALS = " + data + ";" +
               "window.BUILD = " + json.dumps(build) + ";")
    html_out = tpl.replace("/*__DATA__*/", payload)
    html_out = html_out.replace("<!--__STATIC__-->", static_fallback(manuals, build))

    os.makedirs(SITE, exist_ok=True)
    outpath = os.path.join(SITE, "Trailer Docs.html")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(html_out)
    write_pwa(SITE, html_out, build)

    kb = os.path.getsize(outpath) // 1024
    ready = [m["id"] for m in manuals if m["status"] == "ready"]
    print(f"built {outpath}  ({kb} KB)  v{build['version']}  {build['stamp']}  "
          f"ready: {', '.join(ready)}")
    print(f"       hosted copy: index.html + manifest + sw.js + icons in {SITE}")


if __name__ == "__main__":
    main()
