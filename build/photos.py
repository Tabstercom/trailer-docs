#!/usr/bin/env python3
"""
Photo pipeline for Trailer Docs. Two stages, both idempotent.

  ingest   content/<manual>/photos_raw/*  ->  content/<manual>/masters/*.webp
           EXIF-rotated, stripped of metadata, capped at MASTER_PX.
           Phone dumps are ~4 MB each and stay out of git; the master is the
           committed original that everything else is derived from. Stripping
           the metadata matters: phone photos carry the GPS coordinates of
           wherever they were taken.

  render   masters/ + photos.yaml         ->  content/<manual>/images/*.webp
           Rotate, crop, draw the annotations, downscale to OUT_PX.
           images/ is generated, so it is gitignored -- build.py runs this.

Annotations live in photos.yaml as data rather than baked pixels, so a crop can
be nudged or a circle moved without re-shooting. build/annotate.html is the
editor that writes that YAML; nobody should be typing coordinates by hand.

Usage:  python3 build/photos.py              # ingest + render, all manuals
        python3 build/photos.py --ingest     # ingest only
        python3 build/photos.py --force      # ignore the up-to-date check
        python3 build/photos.py --manual setup
"""
import os, sys, math, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "content")

MASTER_PX = 2400   # long edge of the committed master
MASTER_Q = 80
OUT_PX = 1280      # long edge of what ships: the content column is 720 CSS px
OUT_Q = 72
SS = 2             # supersample factor -- ImageDraw does not antialias

RAW_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}

# Annotation colours. Deliberately not the app palette: these are burned into
# photos of dark metal and bright sky, so they need to carry on their own. Each
# stroke is drawn over a translucent dark halo, which is what makes them read
# against a light background as well as a dark one.
PALETTE = {
    "amber": (245, 165, 36),
    "blue":  (46, 155, 214),
    "red":   (224, 71, 62),
    "green": (56, 161, 105),
    "white": (255, 255, 255),
}
HALO = (10, 18, 24, 145)
DEFAULT_COLOR = "amber"
DEFAULT_W = 0.007  # fraction of the output width

try:
    from PIL import Image, ImageDraw, ImageOps
except ImportError:
    sys.exit("Pillow required: pip install pillow")

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")


def slug(name):
    keep = "".join(c if (c.isalnum() or c == "-") else "-" for c in name.lower())
    while "--" in keep:
        keep = keep.replace("--", "-")
    return keep.strip("-")


IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}


def normalize_out(name):
    """Force the .webp the renderer actually writes.

    Typing `hydrolics_off` in the editor used to produce a file with no
    extension, which manual.md could never match and browsers would serve
    with no usable type. Only a recognised image extension is replaced --
    a name like `2.5mm-port` keeps its dot and just gains the suffix.
    """
    stem, ext = os.path.splitext(name)
    low = ext.lower()
    if low == ".webp":
        return name
    return (stem if low in IMG_EXT else name) + ".webp"


def manual_dirs(only=None):
    if not os.path.isdir(CONTENT):
        return []
    out = []
    for mid in sorted(os.listdir(CONTENT)):
        d = os.path.join(CONTENT, mid)
        if os.path.isdir(d) and (only is None or mid == only):
            out.append((mid, d))
    return out


# ---------- ingest ----------

def ingest_manual(d, force=False):
    """photos_raw/* -> masters/*.webp. Returns the number written."""
    rawdir = os.path.join(d, "photos_raw")
    if not os.path.isdir(rawdir):
        return 0
    mdir = os.path.join(d, "masters")
    os.makedirs(mdir, exist_ok=True)

    n = 0
    for fn in sorted(os.listdir(rawdir)):
        src = os.path.join(rawdir, fn)
        stem, ext = os.path.splitext(fn)
        if not os.path.isfile(src) or ext.lower() not in RAW_EXT:
            continue
        dst = os.path.join(mdir, slug(stem) + ".webp")
        if not force and os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            continue
        try:
            im = Image.open(src)
        except Exception as e:
            print("  ! skipped %s (%s)" % (fn, e))
            continue
        # phones record rotation in EXIF rather than in the pixels
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((MASTER_PX, MASTER_PX), Image.LANCZOS)
        # a fresh image carries no info dict, so no EXIF and no GPS survives
        out = Image.new("RGB", im.size)
        out.paste(im)
        out.save(dst, "WEBP", quality=MASTER_Q, method=6)
        n += 1
        print("  ingest %s -> masters/%s  %dx%d" %
              (fn, os.path.basename(dst), out.width, out.height))
    return n


# ---------- render ----------

def _mapper(crop, ow, oh):
    """Normalised-on-the-master point -> pixel in the supersampled output."""
    cx, cy, cw, ch = crop
    def pt(p):
        return ((p[0] - cx) / cw * ow, (p[1] - cy) / ch * oh)
    return pt


def _stroke(dr, pts, color, width):
    """Polyline with round ends. ImageDraw gives round joins but flat caps."""
    w = max(1, int(round(width)))
    if len(pts) == 1:
        pts = [pts[0], (pts[0][0] + 0.01, pts[0][1])]
    dr.line(pts, fill=color, width=w, joint="curve")
    r = w / 2.0
    for p in (pts[0], pts[-1]):
        dr.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color)


def _arrow_head(a, b, width):
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    L = max(width * 3.6, 6.0)
    spread = math.radians(26)
    return [(b[0] - L * math.cos(ang - spread), b[1] - L * math.sin(ang - spread)),
            (b[0], b[1]),
            (b[0] - L * math.cos(ang + spread), b[1] - L * math.sin(ang + spread))]


def _draw_one(dr, ann, pt, ow, color, width, geom_w):
    """One annotation. `width` is this pass's stroke weight, `geom_w` the
    shape's own weight -- they differ on the halo pass, and keeping the
    geometry pinned to geom_w is what stops the halo drifting off the stroke.
    """
    kind = ann.get("type", "pen")
    if kind == "circle":
        c = pt(ann["c"])
        crop = ann["_crop"]
        rx = ann["r"][0] / crop[2] * ow
        ry = ann["r"][1] / crop[3] * ann["_oh"]
        # ImageDraw grows an ellipse outline inward from the bbox, so a fatter
        # halo would sit entirely inside the ring. Push the bbox out by half
        # the extra to straddle it instead.
        pad = (width - geom_w) / 2.0
        rx, ry = rx + pad, ry + pad
        dr.ellipse([c[0] - rx, c[1] - ry, c[0] + rx, c[1] + ry],
                   outline=color, width=max(1, int(round(width))))
    elif kind in ("arrow", "line"):
        a, b = pt(ann["a"]), pt(ann["b"])
        _stroke(dr, [a, b], color, width)
        if kind == "arrow":
            head = _arrow_head(a, b, geom_w)
            dr.polygon(head, fill=color)
            # stroking the outline is how the head grows on the halo pass --
            # sizing the triangle off `width` would make it a different shape
            dr.line(head + [head[0]], fill=color,
                    width=max(1, int(round(width))), joint="curve")
    elif kind == "pen":
        pts = [pt(p) for p in ann.get("pts") or []]
        if pts:
            _stroke(dr, pts, color, width)
    else:
        print("  ! unknown annotation type %r" % kind)


def render_photo(spec, mdir, outdir):
    master = os.path.join(mdir, spec["master"])
    im = Image.open(master).convert("RGB")

    rot = int(spec.get("rotate") or 0) % 360
    if rot:
        im = im.rotate(-rot, expand=True)

    W, H = im.size
    cx, cy, cw, ch = spec.get("crop") or [0.0, 0.0, 1.0, 1.0]
    cw, ch = max(cw, 1e-4), max(ch, 1e-4)
    box = (max(0, round(cx * W)), max(0, round(cy * H)),
           min(W, round((cx + cw) * W)), min(H, round((cy + ch) * H)))
    if box[2] <= box[0] or box[3] <= box[1]:
        box = (0, 0, W, H)
        cx, cy, cw, ch = 0.0, 0.0, 1.0, 1.0
    im = im.crop(box)

    # never upscale past the master's own detail
    w, h = im.size
    scale = min(1.0, float(OUT_PX) / max(w, h))
    ow, oh = max(1, round(w * scale)), max(1, round(h * scale))

    anns = spec.get("annotations") or []
    if anns:
        # draw big, then come down: that downsample is the antialiasing
        big = im.resize((ow * SS, oh * SS), Image.LANCZOS)
        overlay = Image.new("RGBA", big.size, (0, 0, 0, 0))
        dr = ImageDraw.Draw(overlay)
        pt = _mapper((cx, cy, cw, ch), ow * SS, oh * SS)

        prepared = []
        for a in anns:
            a = dict(a)
            a["_crop"] = (cx, cy, cw, ch)
            a["_oh"] = oh * SS
            color = PALETTE.get(a.get("color", DEFAULT_COLOR), PALETTE[DEFAULT_COLOR])
            width = float(a.get("w", DEFAULT_W)) * ow * SS
            prepared.append((a, color, max(1.5, width)))

        # halo pass under everything, so one shape's halo never sits on top of
        # another shape's colour
        for a, _color, width in prepared:
            _draw_one(dr, a, pt, ow * SS, HALO,
                      width + max(3.0, width * 0.85), width)
        for a, color, width in prepared:
            _draw_one(dr, a, pt, ow * SS, color + (255,), width, width)

        big = Image.alpha_composite(big.convert("RGBA"), overlay).convert("RGB")
        im = big.resize((ow, oh), Image.LANCZOS)
    else:
        im = im.resize((ow, oh), Image.LANCZOS)

    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, spec["out"])
    im.save(dst, "WEBP", quality=OUT_Q, method=6)
    return dst, os.path.getsize(dst)


def render_manual(mid, d, force=False):
    specfile = os.path.join(d, "photos.yaml")
    outdir = os.path.join(d, "images")
    if not os.path.exists(specfile):
        return 0

    with open(specfile, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    specs = cfg.get("photos") or []
    mdir = os.path.join(d, "masters")

    spec_mtime = os.path.getmtime(specfile)
    n = 0
    seen = set()
    fixed = 0
    for spec in specs:
        out, master = spec.get("out"), spec.get("master")
        if not out or not master:
            sys.exit("%s: every entry needs 'out' and 'master' (got %r)" % (specfile, spec))
        norm = normalize_out(out)
        if norm != out:
            fixed += 1
            out = norm
            spec = dict(spec, out=out)
        seen.add(out)
        src = os.path.join(mdir, master)
        if not os.path.exists(src):
            sys.exit("%s: master not found: masters/%s" % (specfile, master))
        dst = os.path.join(outdir, out)
        if (not force and os.path.exists(dst)
                and os.path.getmtime(dst) >= max(spec_mtime, os.path.getmtime(src))):
            continue
        _, size = render_photo(spec, mdir, outdir)
        print("  render %s/%s  %d KB" % (mid, out, size // 1024))
        n += 1

    if fixed:
        print("  note: %d entr%s in %s/photos.yaml had no .webp on 'out' -- "
              "rendered with it added" % (fixed, "y" if fixed == 1 else "ies", mid))

    # a photo dropped from the spec should leave the manual, not linger
    if os.path.isdir(outdir):
        for fn in sorted(os.listdir(outdir)):
            if fn not in seen and not fn.startswith("."):
                os.remove(os.path.join(outdir, fn))
                print("  remove %s/%s (not in photos.yaml)" % (mid, fn))
    return n


def run(only=None, force=False, ingest_only=False):
    ing = ren = 0
    for mid, d in manual_dirs(only):
        ing += ingest_manual(d, force)
        if not ingest_only:
            ren += render_manual(mid, d, force)
    if ing or ren:
        print("photos: %d ingested, %d rendered" % (ing, ren))
    return ing, ren


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ingest", action="store_true", help="ingest only, skip render")
    ap.add_argument("--force", action="store_true", help="rebuild even if up to date")
    ap.add_argument("--manual", help="limit to one manual id")
    a = ap.parse_args()
    ing, ren = run(a.manual, a.force, a.ingest)
    if not ing and not ren:
        print("photos: nothing to do")


if __name__ == "__main__":
    main()
