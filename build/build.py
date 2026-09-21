#!/usr/bin/env python3
"""
Build the Trailer Docs PWA.

Reads:  content/<manual>/manual.md      (prose -> Guide / Illustrated)
        content/<manual>/checklist.yaml (condensed tick steps + reference cards)
        content/<manual>/images/*       (rendered photos, see photos.py)
        build/manuals.yaml              (master list + status)
        VERSION                         (version number shown in the app)

Writes: site/index.html                 (the app)
        site/photos/*                   (content-hashed photos)
        site/manifest.webmanifest, sw.js, icon-*.png

Delivery is the hosted PWA only -- install it once with signal, then it runs
with none. Photos are separate files rather than inlined base64: the app paints
before they arrive, the browser caches them one by one, and the service worker
precaches the lot at install so nothing is missing in the field.

Every build bumps the patch digit in VERSION, because the service worker
cache name carries the version and an unchanged one leaves installed phones
on the old cache. Use --no-bump for a local build you will not publish.

Usage:  python3 build/build.py [--no-bump]
"""
import os, re, json, shutil, hashlib, subprocess, sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "content")
SITE = os.path.join(ROOT, "site")
PHOTOS_OUT = os.path.join(SITE, "photos")
VERSION_FILE = os.path.join(ROOT, "VERSION")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow required: pip install pillow")

import photos as photolib


def version():
    """Version string from the VERSION file at the repo root."""
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except FileNotFoundError:
        return "0.0.0"


def bump_version():
    """Increment the patch digit in VERSION and write it back.

    The service worker cache name carries the version, so an unchanged
    VERSION means every installed phone keeps serving the old cache no
    matter how many times you rebuild -- the content ships, nobody sees it.
    Bumping on every build makes that impossible to forget. Pass --no-bump
    for a throwaway local build you are not going to publish.
    """
    cur = version()
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", cur)
    if not m:
        print("VERSION is %r, not X.Y.Z -- leaving it alone" % cur)
        return cur
    major, minor, patch = (int(g) for g in m.groups())
    new = "%d.%d.%d" % (major, minor, patch + 1)
    with open(VERSION_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(new + "\n")
    return new


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def collect_photos(mid, d):
    """images/<name> -> {file, data, w, h}, keyed by the name manual.md uses.

    The published name carries a content hash. The service-worker cache is
    keyed on VERSION, so without this every version bump would re-download
    every photo; with it, an unchanged photo keeps its URL and stays cached.
    """
    out = {}
    imgdir = os.path.join(d, "images")
    if not os.path.isdir(imgdir):
        return out
    for fn in sorted(os.listdir(imgdir)):
        fp = os.path.join(imgdir, fn)
        if not os.path.isfile(fp) or fn.startswith("."):
            continue
        with open(fp, "rb") as f:
            data = f.read()
        with Image.open(fp) as im:
            w, h = im.size
        stem, ext = os.path.splitext(fn)
        h8 = hashlib.sha1(data).hexdigest()[:8]
        out[fn] = {"file": f"{mid}-{stem}.{h8}{ext}", "data": data, "w": w, "h": h}
    return out


def md_to_guide(mdpath, photos, missing):
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

    # point <img> at the published photo; width/height stop lazy-loaded photos
    # from shifting the text under your thumb as you scroll
    def repl_img(m):
        tag, src = m.group(0), m.group(1)
        rec = photos.get(os.path.basename(src))
        if not rec:
            missing.append((mdpath, src))
            return tag
        tag = tag.replace('src="%s"' % src, 'src="photos/%s"' % rec["file"])
        tag = tag.replace(
            '<img',
            '<img class="photo" loading="lazy" decoding="async" '
            'width="%d" height="%d"' % (rec["w"], rec["h"]), 1)
        return tag
    body = re.sub(r'<img[^>]*src="([^"]+)"[^>]*/?>', repl_img, body)

    # strip any <strong> that pandoc left wrapping a heading
    body = re.sub(r'<h([12])([^>]*)><strong>(.*?)</strong></h\1>',
                  r'<h\1\2>\3</h\1>', body)

    # TOC from h1
    toc = re.findall(r'<h1 id="([^"]+)">(.*?)</h1>', body)
    toc = [(hid, re.sub("<.*?>", "", t)) for hid, t in toc]
    return body, toc


def build_manual(m, allphotos, missing):
    mid = m["id"]
    d = os.path.join(CONTENT, mid)
    if m.get("status") != "ready":
        return {**m, "guide": "", "toc": [], "hasPhotos": False,
                "checklist": {"phases": [], "reference": []}}

    photos = collect_photos(mid, d)
    allphotos.update({rec["file"]: rec["data"] for rec in photos.values()})

    guide, toc = md_to_guide(os.path.join(d, "manual.md"), photos, missing)
    cl = load_yaml(os.path.join(d, "checklist.yaml"))
    return {
        "id": mid, "title": m["title"], "subtitle": m["subtitle"],
        "status": "ready",
        "guide": guide, "toc": toc,
        "hasPhotos": bool(photos),
        "checklist": {"phases": cl.get("phases", []), "reference": cl.get("reference", [])},
    }


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

SW_JS = """// Trailer Docs service worker -- the whole point of the hosted copy.
// The cache name carries the build version, so publishing a new version
// installs a fresh cache and drops the old one.
const CACHE = 'trailer-docs-__VERSION__';

// Every photo is precached at install, not lazily on first view: a phone that
// installs at the office and then drives to a field with no signal has to have
// all of them already.
//
// The split matters. SHELL files keep the same URL every build, so a new
// worker has to refetch them or it would serve the previous app forever.
// PHOTO urls carry a content hash, so a url that still matches is
// byte-identical and can be copied straight out of the old cache -- no
// network at all. Pages serves Cache-Control: max-age=600, so ten minutes
// after a build, refetching would put 37 revalidation round trips between a
// weak signal and a working app, for photos the phone already has.
const SHELL = __SHELL__;
const PHOTOS = __PHOTOS__;

self.addEventListener('install', e => {
  e.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL);

    const carried = new Set();
    for (const key of (await caches.keys()).filter(k => k !== CACHE)) {
      const prev = await caches.open(key);
      for (const url of PHOTOS) {
        if (carried.has(url)) continue;
        const hit = await prev.match(url);
        if (hit) { await cache.put(url, hit); carried.add(url); }
      }
    }

    const fresh = PHOTOS.filter(u => !carried.has(u));
    if (fresh.length) await cache.addAll(fresh);
    await self.skipWaiting();
  })());
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
    from PIL import ImageDraw

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
        img.save(os.path.join(outdir, "icon-%d.png" % size), "PNG", optimize=True)


def write_site(html_out, allphotos, build):
    """index.html + photos + manifest + service worker + icons."""
    os.makedirs(SITE, exist_ok=True)

    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_out)

    # rebuilt from scratch: hashed names would otherwise pile up build on build
    shutil.rmtree(PHOTOS_OUT, ignore_errors=True)
    os.makedirs(PHOTOS_OUT, exist_ok=True)
    for name, data in sorted(allphotos.items()):
        with open(os.path.join(PHOTOS_OUT, name), "wb") as f:
            f.write(data)

    with open(os.path.join(SITE, "manifest.webmanifest"), "w", encoding="utf-8") as f:
        json.dump(MANIFEST, f, indent=2)

    # Kept apart on purpose -- see the comment in SW_JS. Shell urls are stable
    # across builds and must be refetched; photo urls are content-hashed and
    # can be carried over from the previous cache untouched.
    shell = ["./", "./index.html", "./manifest.webmanifest",
             "./icon-180.png", "./icon-192.png", "./icon-512.png"]
    photo_urls = ["./photos/" + n for n in sorted(allphotos)]
    sw = SW_JS.replace("__VERSION__", build["version"])
    sw = sw.replace("__SHELL__", json.dumps(shell, indent=2))
    sw = sw.replace("__PHOTOS__", json.dumps(photo_urls, indent=2))
    with open(os.path.join(SITE, "sw.js"), "w", encoding="utf-8") as f:
        f.write(sw)

    write_icons(SITE)


def main():
    args = set(sys.argv[1:])
    unknown = args - {"--no-bump"}
    if unknown:
        sys.exit("unknown option(s): %s\nUsage: python3 build/build.py [--no-bump]"
                 % " ".join(sorted(unknown)))

    photolib.run()

    cfg = load_yaml(os.path.join(ROOT, "build", "manuals.yaml"))
    allphotos, missing = {}, []
    manuals = [build_manual(m, allphotos, missing) for m in cfg["manuals"]]

    if missing:
        # Dropping these silently is how a photo disappears from the manual
        # after a rename and nobody notices until they are on site.
        lines = "\n".join("  %s: %s" % (os.path.relpath(p, ROOT), s) for p, s in missing)
        sys.exit("missing photos referenced by manual.md:\n%s\n"
                 "Run the photo pipeline, or fix the filename." % lines)

    # Bump only once the build is certain to succeed -- a run that dies on a
    # missing photo should not burn a version number.
    now = datetime.now()
    prev = version()
    build = {
        "version": version() if "--no-bump" in args else bump_version(),
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

    write_site(html_out, allphotos, build)

    kb = os.path.getsize(os.path.join(SITE, "index.html")) // 1024
    pkb = sum(len(d) for d in allphotos.values()) // 1024
    ready = [m["id"] for m in manuals if m["status"] == "ready"]
    note = ("bumped from %s" % prev if build["version"] != prev
            else "VERSION held -- installed phones will keep the old cache")
    print("built %s  v%s  %s  (%s)"
          % (SITE, build["version"], build["stamp"], note))
    print("       index.html %d KB + %d photos %d KB" % (kb, len(allphotos), pkb))
    print("       ready: %s" % ", ".join(ready))


if __name__ == "__main__":
    main()
