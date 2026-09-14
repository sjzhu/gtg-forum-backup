# GTG Forums Archive

An offline backup of [forums.greaterthangames.com](https://forums.greaterthangames.com), plus a
generated, human-readable static site for browsing it.

## What's in this repo

- `administration/`, `conventions/`, `games/`, `general-gtg/`, `old-rules-gameplay-boards/`,
  `other-games/`: the raw backup, one folder per top-level forum category. Each contains the
  Discourse API JSON for that category's topics, posts, and category listings, plus a local copy
  of every image/attachment referenced in those posts (`uploads/`).
- `readable/`: a generated static HTML site (~188MB, mostly images) built from the raw data
  above: categories → subcategories → topics → posts, styled and cross-linked like a normal forum.
- `tools/`: the script that generates `readable/` from the raw data, plus a small snapshot of
  category display names/descriptions it uses.

## Viewing the archive

`readable/` is plain HTML and CSS with **no JavaScript and no server-side code**, and every link
and image uses a relative path. There is nothing to install and nothing to build.

1. Clone or pull this repo.
2. Open `readable/index.html` in any web browser. Double-click it, or:
   - macOS: `open readable/index.html`
   - Linux: `xdg-open readable/index.html`
   - Windows: Double-click it in Explorer, or `start readable\index.html`

Browsing from there (categories → topics → posts) works entirely over local `file://` links.

### Optional: serve it over HTTP

Opening the file directly is enough. If you'd rather serve it (e.g. to view it from another
device on your network, or your browser is configured to block `file://` access to local images):

```bash
cd public   # this repo
python3 -m http.server 8000
```

Then visit `http://localhost:8000/readable/` in a browser.

## Regenerating the readable site

If the raw category data changes (some posts are edited or new data is pulled), rebuild `readable/`
with:

```bash
python3 tools/generate_readable_site.py
```

This reads the six category folders directly and rewrites `readable/` from scratch — it's safe
to re-run any time, and takes a few seconds.
