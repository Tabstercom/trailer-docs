# Trailer Docs

On-site documentation for the scanning trailer, built as an offline web app.
One source of truth per manual generates the reading guide and the tap-through
checklist. It's delivered as an installable PWA: open the link once with
signal, add it to the home screen, and it runs full-screen with no internet
from then on.

**Live at https://tabstercom.github.io/trailer-docs/**

## What's here

```
trailer-docs/
├── content/                 # SOURCE OF TRUTH — edit these
│   ├── setup/
│   │   ├── manual.md        # full prose (headings, steps, callouts, photos)
│   │   ├── checklist.yaml   # condensed tick steps + reference cards
│   │   ├── photos_raw/      # phone dump — gitignored, see "Adding photos"
│   │   ├── masters/         # committed originals, EXIF-stripped
│   │   ├── photos.yaml      # crop + annotations for each photo
│   │   └── images/          # rendered photos — generated, gitignored
│   ├── packdown/
│   ├── daily-ops/           # stubs — not written yet
│   └── debugging/
├── build/
│   ├── manuals.yaml         # master list of manuals + status (ready | soon)
│   ├── build.py             # the build script
│   ├── photos.py            # the photo pipeline (build.py runs it)
│   ├── annotate.html        # the annotation editor — open it in a browser
│   └── template.html        # app shell (HTML/CSS/JS)
├── VERSION                  # version number — auto-bumped on every build
└── site/                    # THE OUTPUT — this is what gets published
    ├── index.html           # the app
    ├── photos/              # content-hashed photos
    ├── manifest.webmanifest # PWA metadata (name, colours, icons)
    ├── sw.js                # offline cache; precaches every photo
    └── icon-*.png           # home-screen icons, generated on build
```

## Build

Needs Python 3, `pandoc`, and `pip install pyyaml pillow`.

```
python3 build/build.py
```

That runs the photo pipeline, then regenerates everything under `site/`.

## Version

`VERSION` at the repo root holds the version number (plain text, e.g. `1.3.0`).
Each build stamps it — plus the build date and time — into the app: the version
and date show top-right on the hub, and the full stamp sits in the footer.

**Every build bumps the patch digit automatically** (1.3.0 → 1.3.1) and writes
it back to `VERSION`. You don't need to touch the file; edit it by hand only to
move the major or minor digit for a release worth naming.

That's deliberate, because the service worker caches under a name that includes
the version. An unchanged version means installed phones keep serving the old
cache however many times you rebuild and push — the content ships and nobody on
site ever sees it. Bumping every time makes that impossible to forget.

For a throwaway local build you aren't going to publish:

```
python3 build/build.py --no-bump
```

A phone updates on the second launch after a release: one to fetch it, one to
run it.

## Editing content

- **Prose / the guide** — edit `content/<manual>/manual.md`. It's plain Markdown.
  - `# Heading` starts a numbered section; `## Heading` is a subsection.
  - Numbered steps: a normal `1.` `2.` list. Bulleted criteria: `-` list.
  - Callouts:
    ```
    ::: important
    Text of the important note.
    :::

    ::: note
    Text of the note.
    :::
    ```
  - Photos: see below.
- **Checklist** — edit `content/<manual>/checklist.yaml`. Each phase has a
  `title` and `steps`. A step is either a plain string, or
  `{t: "text", flag: imp}` (amber "important") / `{flag: win}` (green finish).
  `reference:` holds the quick-reference cards (set `amber: true` to tint one).

## Adding photos

Photos go through three stages. Only the middle one is committed: phone dumps
are ~4 MB each and don't belong in git, and the rendered output is derived, so
it doesn't either. The **master** is the committed original — which is what
makes an annotation re-editable a year later without going back to the phone.

```
photos_raw/  →  masters/  →  images/
  (dumped)     (committed)   (generated)
```

**1. Dump and ingest.** Drop the photos in `content/<manual>/photos_raw/`, then:

```
python3 build/photos.py --ingest
```

That rotates them the right way up (phones record rotation in EXIF, not in the
pixels), caps them at 2400 px, and **strips the metadata** — phone photos carry
the GPS coordinates of wherever they were taken, and this is a published site.

**2. Crop and annotate.** Open `build/annotate.html` in a browser — it's a plain
local file, nothing to run. Hit **Open folder…** and pick
`content/<manual>/masters/`. It loads the whole folder as a queue; `←` and `→`
step through it and the sidebar shows what you've done.

| | |
|---|---|
| `1` Crop | drag a box; everything outside it dims |
| `2` Circle | drag a box, get an ellipse round it |
| `3` Pen | freehand, follows the mouse |
| `4` Arrow | drag from tail to head |

Pick a colour and weight, `Ctrl`+`Z` to undo, `P` to preview the crop as it will
ship. Each photo keeps its own state, so you can jump back and forth.

A photo joins the output the moment you touch it — a shoot has more frames than
the manual needs, so the default is **out**, not in. Use the **include**
checkbox for a photo you want whole and unmarked, and set **out** to the
filename `manual.md` will reference.

When the batch is done, leave the output on **Whole file**, hit **Copy**, and
save it as `content/<manual>/photos.yaml`:

```yaml
photos:
  - out: hydraulics-switch.webp
    master: img-4821.webp
    crop: [0.14, 0.26, 0.62, 0.56]
    annotations:
      - {"type":"circle","c":[0.625,0.567],"r":[0.075,0.1],"color":"amber"}
```

Coordinates are fractions of the master, not of the crop, so **re-cropping later
doesn't slide the circles off what they're circling**.

To change photos later, open the folder again and paste the whole existing
`photos.yaml` into **Load from paste…** — it refills every entry it recognises,
so you can adjust one photo and copy the whole file back out.

The editor also autosaves to the browser as you go, keyed on the set of
filenames in the folder. That's a **crash net, not a save** — copy the YAML out
when you finish a batch. Adding a new photo to the folder starts a fresh
autosave, and **Discard saved work** clears it.

**3. Reference it** in `manual.md`. The alt text becomes the visible caption:

```markdown
![Red turn-switch, vertical = hydraulics on](images/hydraulics-switch.webp)
```

For a before/after pair, wrap two in a `pair` div and they lay out side by side:

```markdown
::: pair
![Wrong — clamp on the painted bracket](images/jump-wrong.webp)

![Right — bare metal, away from the battery](images/jump-right.webp)
:::
```

**4. Build.** `python3 build/build.py` renders anything that changed and
publishes it. Photos only appear in the **Illustrated** view, not **Guide**.

If `manual.md` references a photo that doesn't exist, the build **fails** rather
than dropping it silently — otherwise a rename makes a photo vanish from the
manual and nobody finds out until they're on site.

Other flags: `--force` re-renders even when up to date, `--manual <id>` limits
it to one manual. Deleting an entry from `photos.yaml` deletes its rendered
file on the next run.

### Annotation colours

Deliberately not the app palette — these are burned into photos of dark metal
and bright sky, so they have to carry on their own. Each stroke sits on a
translucent dark halo, which is what makes it read against a light background
as well as a dark one.

`amber` (default) · `blue` · `red` · `green` · `white`

The colours, halo and default stroke weight are defined in `build/photos.py`
and mirrored in `build/annotate.html` so the editor preview matches what gets
rendered. **Change one, change both.**

## Adding a new manual

1. Create `content/<id>/` with `manual.md` and `checklist.yaml`.
2. In `build/manuals.yaml`, set that manual's `status: ready` (and its title
   and subtitle).
3. `python3 build/build.py`. It appears on the hub automatically.

Manuals left at `status: soon` show as greyed "Coming soon" tiles.

## Publishing

Publishing is a push: the workflow in `.github/workflows/pages.yml` ships
whatever is committed under `site/`. The build runs locally (it needs pandoc),
so the flow is `python3 build/build.py`, commit, push.

To check it first, serve `site/` over http — opening `index.html` as a `file://`
won't do, because service workers don't run there and neither does the offline
behaviour you'd want to test:

```
python3 -m http.server 8099 --directory site
```

(`.claude/launch.json` has this wired up as the `site` config.)

On site:

1. Open the link once somewhere with signal.
2. **Share → Add to Home Screen** (iPhone) or **Install app** (Android).
3. It launches full-screen and works offline from then on.

Checklist ticks are saved per-manual in the browser, per device.

### How offline works

`sw.js` precaches **every photo at install**, not lazily on first view — a phone
that installs at the office and then drives to a field with no signal has to
have all of them already. Published photo URLs carry a content hash, so a
version bump only re-downloads the photos that actually changed; the rest are
served from the browser's own cache.

That does mean install pulls the whole photo set down at once. It's the one
moment that needs real signal, so do step 1 above on wifi.

## Notes

- Photos ship as separate files rather than inlined, so the app paints before
  they arrive. Guide view hides them; Illustrated shows them.
- The Word `.docx` is generated separately (not part of this build) and remains
  the print/hand-off master. When its text changes, update `manual.md` to match
  so the app stays in sync.
- Google Fonts load when online and fall back to the system font otherwise.
