# Trailer Docs

On-site documentation for the scanning trailer, built as a single self-contained
offline web app. One source of truth per manual generates the reading guide and
the tap-through checklist; everything bundles into one HTML file you can drop on
a phone and open in any browser — no server, no internet.

## What's here

```
trailer-docs/
├── content/                 # SOURCE OF TRUTH — edit these
│   ├── setup/
│   │   ├── manual.md        # full prose (headings, steps, callouts, images)
│   │   ├── checklist.yaml   # condensed tick steps + reference cards
│   │   └── images/          # photos referenced by manual.md (inlined on build)
│   ├── packdown/            # stubs — not written yet
│   ├── daily-ops/
│   └── debugging/
├── build/
│   ├── manuals.yaml         # master list of manuals + status (ready | soon)
│   ├── build.py             # the build script
│   └── template.html        # app shell (HTML/CSS/JS)
├── VERSION                  # version number stamped into the app
└── site/
    ├── Trailer Docs.html    # THE OUTPUT — the standalone file you can send
    ├── index.html           # same app + service worker, for hosting
    ├── manifest.webmanifest # PWA metadata (name, colours, icons)
    ├── sw.js                # offline cache; cache name carries the version
    └── icon-*.png           # home-screen icons, generated on build
```

## Build

Needs Python 3, `pandoc`, and `pip install pyyaml`.

```
python3 build/build.py
```

This regenerates `site/Trailer Docs.html`. Open that file in a browser, or send
it to a phone and "Add to Home Screen" to run it full-screen like an app.
Checklist ticks are saved per-manual in the browser, per device.

## Version

`VERSION` at the repo root holds the version number (plain text, e.g. `1.0.0`).
Each build stamps it — plus the build date and time — into the app: the version
and date show top-right on the hub, and the full stamp sits in the footer. Bump
`VERSION` before a build you hand out, so people on site can tell you which copy
they're holding.

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
  - Photos (later): drop the file in `images/` and reference it with
    `![](images/my-photo.jpg)`. It's inlined as base64 on build and shown in the
    **Illustrated** view (hidden in **Guide**).
- **Checklist** — edit `content/<manual>/checklist.yaml`. Each phase has a
  `title` and `steps`. A step is either a plain string, or
  `{t: "text", flag: imp}` (amber "important") / `{flag: win}` (green finish).
  `reference:` holds the quick-reference cards (set `amber: true` to tint one).

## Adding a new manual

1. Create `content/<id>/` with `manual.md`, `checklist.yaml`, `images/`.
2. In `build/manuals.yaml`, set that manual's `status: ready` (and its title
   and subtitle).
3. `python3 build/build.py`. It appears on the hub automatically.

Manuals left at `status: soon` show as greyed "Coming soon" tiles.

## Sending it to a phone

Android opens the file in Chrome, so the full app just works. **iPhone is
different**: tapping an HTML attachment in WhatsApp, Mail or Files opens it in
Quick Look, which renders the page but never runs JavaScript — so the app would
paint nothing at all.

Every build therefore includes a no-JavaScript fallback: if scripts don't run,
the page shows the full prose of each manual plus the checklist and reference
cards as plain (untickable) lists, behind an amber "Preview mode" note. Photos
are left out of that view to keep the file small.

To give iPhone users the real app — tabs, tap-through checklist, saved ticks,
add-to-home-screen — send the hosted link instead of the file. `file://` on iOS
can't save checklist state or be added to the home screen either way.

## The hosted copy

Live at **https://tabstercom.github.io/trailer-docs/**

`site/index.html` is the same app with a service worker attached, so once it has
been opened over the network it runs with no signal at all. On site:

1. Open the link once somewhere with signal.
2. **Share → Add to Home Screen** (iPhone) or **Install app** (Android).
3. It launches full-screen and works offline from then on.

Publishing is a push: the workflow in `.github/workflows/pages.yml` ships
whatever is committed under `site/`. The build runs locally (it needs pandoc),
so the flow is `python3 build/build.py`, commit, push.

The service worker caches under a name that includes the version, so **bump
`VERSION` when you change content** — that's what makes installed phones pick up
the new copy instead of serving the old cache. A phone updates on the second
launch after a release: one to fetch it, one to run it.

## Notes

- The Word `.docx` is generated separately (not part of this build) and remains
  the print/hand-off master. When its text changes, update `manual.md` to match
  so the app stays in sync.
- Everything is offline and self-contained. Google Fonts load when online and
  fall back to the system font otherwise.
