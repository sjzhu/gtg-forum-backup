import argparse, json, os, re, html, math, subprocess, sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = str(Path(__file__).resolve().parent.parent)
CATS_SNAPSHOT = os.path.join(ROOT, "tools", "categories_snapshot.json")
PER_PAGE = 50

# Branch that actually holds the raw category folders + uploads/. Used to build
# raw.githubusercontent.com URLs in --mode pages, regardless of which branch this
# script itself is being run from.
IMAGE_SOURCE_BRANCH = "main"


def detect_owner_repo():
    url = subprocess.check_output(["git", "-C", ROOT, "remote", "get-url", "origin"], text=True).strip()
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", url)
    if not m:
        raise RuntimeError(f"Could not parse GitHub owner/repo from origin remote: {url}")
    return m.group(1), m.group(2)


ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--mode", choices=["local", "pages"], default="local",
                help="local: relative links for browsing off disk (default, used for the main branch). "
                     "pages: images point at raw.githubusercontent.com so the output can be published "
                     "standalone (e.g. on a `pages` branch) without shipping the uploads/ folders.")
ap.add_argument("--out", default=None, help="Output directory (default: <repo>/readable for local, "
                                             "<repo>/../_pages_build for pages)")
args = ap.parse_args()

MODE = args.mode
if args.out:
    OUT = os.path.abspath(args.out)
elif MODE == "local":
    OUT = os.path.join(ROOT, "readable")
else:
    OUT = os.path.join(str(Path(ROOT).parent), "_pages_build")

if MODE == "pages":
    GITHUB_OWNER, GITHUB_REPO = detect_owner_repo()

TOP_SLUGS = ["administration", "conventions", "games", "general-gtg", "old-rules-gameplay-boards", "other-games"]

# ---------- load category display names ----------
snap = json.load(open(CATS_SNAPSHOT))
cat_meta = {}  # id -> {name, slug, description_text, parent}
for c in snap["category_list"]["categories"]:
    cat_meta[c["id"]] = {"name": c["name"], "slug": c["slug"], "description_text": c.get("description_text") or "", "parent": None}
    for s in c.get("subcategory_list") or []:
        cat_meta[s["id"]] = {"name": s["name"], "slug": s["slug"], "description_text": s.get("description_text") or "", "parent": c["id"]}

def cat_name(cid):
    m = cat_meta.get(cid)
    return m["name"] if m else f"Category #{cid}"

def cat_slug(cid):
    m = cat_meta.get(cid)
    return m["slug"] if m else f"cat-{cid}"

# ---------- helpers ----------
def esc(s):
    return html.escape(s or "", quote=True)

def fmt_dt(iso):
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso

def upload_local_name(url):
    u = urlparse(url)
    return u.path.lstrip("/").replace("/", "__")

UPLOAD_RE = re.compile(r'(src|href)="(?:https://forums\.greaterthangames\.com)?(/uploads/[^"]+)"')
TOPIC_LINK_RE = re.compile(r'href="(?:https://forums\.greaterthangames\.com)?/t/[^/"]+/(\d+)(?:/(\d+))?"')
CATEGORY_LINK_RE = re.compile(r'href="(?:https://forums\.greaterthangames\.com)?/c/[^"]*?/(\d+)"')
SITE_INTERNAL_RE = re.compile(r'href="(?:https://forums\.greaterthangames\.com)?(/[a-zA-Z][^"]*)"')

# topic_id -> (top_slug, category_id), filled in during pass 1
topic_location = {}

def section_dir_for(top_slug, cid):
    tid_top = cat_id_for_top(top_slug)
    name = "general" if cid == tid_top else cat_slug(cid)
    return os.path.join(OUT, top_slug, name)

def process_cooked(cooked, top_slug, current_out_dir):
    def _upload(m):
        attr, url = m.group(1), m.group(2)
        local = upload_local_name(url)
        local_path = os.path.join(ROOT, top_slug, "uploads", local)
        if not os.path.exists(local_path):
            return m.group(0)
        if MODE == "pages":
            gh_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{IMAGE_SOURCE_BRANCH}/{top_slug}/uploads/{local}"
            return f'{attr}="{gh_url}"'
        rel_root = os.path.relpath(ROOT, current_out_dir)
        return f'{attr}="{rel_root}/{top_slug}/uploads/{local}"'
    cooked = UPLOAD_RE.sub(_upload, cooked)

    def _topic(m):
        tid, postnum = int(m.group(1)), m.group(2)
        loc = topic_location.get(tid)
        if not loc:
            return f'data-orig-href="/t/.../{tid}"'
        t_top, t_cid = loc
        target_dir = os.path.join(section_dir_for(t_top, t_cid), "topics")
        target = os.path.join(target_dir, f"{tid}.html")
        rel = os.path.relpath(target, current_out_dir)
        anchor = f"#post-{postnum}" if postnum else ""
        return f'href="{rel}{anchor}"'
    cooked = TOPIC_LINK_RE.sub(_topic, cooked)

    def _category(m):
        cid = int(m.group(1))
        if cid not in cat_meta:
            return m.group(0)
        m_ = cat_meta[cid]
        if m_["parent"] is None:
            target_dir = os.path.join(OUT, m_["slug"])
        else:
            top_slug_of_cat = cat_meta[m_["parent"]]["slug"]
            target_dir = section_dir_for(top_slug_of_cat, cid)
        target = os.path.join(target_dir, "index.html")
        rel = os.path.relpath(target, current_out_dir)
        return f'href="{rel}"'
    cooked = CATEGORY_LINK_RE.sub(_category, cooked)

    # anything else pointing at the live site's own paths (user profiles, tags, search, badges...)
    # has no equivalent page in this offline archive, so drop the href rather than leave it dead.
    cooked = SITE_INTERNAL_RE.sub(r'data-orig-href="\1"', cooked)

    # protocol-relative "//forums..." urls (emoji, avatars) resolve as file:// and break when
    # this archive is browsed from disk; make them explicit https so they at least load online.
    cooked = cooked.replace('="//forums.greaterthangames.com', '="https://forums.greaterthangames.com')
    return cooked

ACTION_LABELS = {
    "pinned.enabled": "pinned this topic",
    "pinned.disabled": "unpinned this topic",
    "pinned_globally.enabled": "pinned this topic globally",
    "pinned_globally.disabled": "unpinned this topic globally",
    "banner.enabled": "made this topic a banner",
    "banner.disabled": "removed this topic as a banner",
    "closed.enabled": "closed this topic",
    "closed.disabled": "reopened this topic",
    "archived.enabled": "archived this topic",
    "archived.disabled": "unarchived this topic",
    "autoclosed.enabled": "closed this topic automatically",
    "autoclosed.disabled": "reopened this topic",
    "autobumped.enabled": "bumped this topic automatically",
    "visible.enabled": "made this topic visible",
    "visible.disabled": "unlisted this topic",
    "split_topic": "split this topic",
    "public_topic": "made this a public topic",
    "private_topic": "made this a private topic",
}

def action_label(code, who):
    label = ACTION_LABELS.get(code) or (code.replace(".", " ").replace("_", " ") if code else "performed an action on this topic")
    if who:
        label += f" ({who})"
    return label

def initials(name):
    parts = re.split(r"[\s_\-\.]+", name.strip())
    parts = [p for p in parts if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()

def avatar_color(name):
    h = sum(ord(c) for c in name) if name else 0
    hue = h % 360
    return f"hsl({hue} 45% 42%)"

CSS = """
:root{--bg:#f7f7f5;--panel:#fff;--text:#1c1c1c;--muted:#6b6b6b;--border:#e3e2df;--accent:#8a3b2f;--link:#8a3b2f;}
@media (prefers-color-scheme: dark){
  :root{--bg:#1a1a18;--panel:#242422;--text:#eae8e4;--muted:#a3a19c;--border:#3a3a36;--accent:#e08a6e;--link:#e08a6e;}
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;margin:0;padding:0;line-height:1.5;}
.wrap{max-width:900px;margin:0 auto;padding:24px 16px 64px;}
a{color:var(--link);text-decoration:none;}
a:hover{text-decoration:underline;}
.crumbs{font-size:13px;color:var(--muted);margin-bottom:16px;}
.crumbs a{color:var(--muted);}
h1{font-size:26px;margin:0 0 8px;}
h2{font-size:20px;margin:28px 0 10px;}
.desc{color:var(--muted);font-size:14px;margin-bottom:20px;}
.card-list{display:flex;flex-direction:column;gap:10px;}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px 16px;}
.card .title{font-weight:600;font-size:16px;}
.card .meta{color:var(--muted);font-size:13px;margin-top:4px;}
.topic-row{display:flex;justify-content:space-between;gap:12px;align-items:baseline;flex-wrap:wrap;}
.topic-row .right{color:var(--muted);font-size:13px;white-space:nowrap;}
.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:4px;background:var(--border);color:var(--muted);margin-left:6px;}
.pager{display:flex;gap:8px;justify-content:center;margin-top:24px;flex-wrap:wrap;}
.pager a,.pager span{padding:6px 11px;border:1px solid var(--border);border-radius:6px;font-size:13px;}
.pager .current{background:var(--accent);color:#fff;border-color:var(--accent);}
.small-action{text-align:center;color:var(--muted);font-size:13px;margin:10px 0;padding:2px 0;}
.small-action .who{font-weight:600;color:var(--text);}
.post{background:var(--panel);border:1px solid var(--border);border-radius:10px;margin-bottom:14px;overflow:hidden;}
.post-head{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--border);}
.avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:600;font-size:13px;flex-shrink:0;}
.who{font-weight:600;}
.when{color:var(--muted);font-size:12px;}
.postnum{margin-left:auto;color:var(--muted);font-size:12px;}
.post-body{padding:14px 16px;font-size:15px;overflow-wrap:break-word;}
.post-body img{max-width:100%;height:auto;border-radius:6px;}
.post-body pre{overflow-x:auto;background:var(--bg);padding:10px;border-radius:6px;}
.post-body blockquote{border-left:3px solid var(--border);margin:8px 0;padding:4px 0 4px 12px;color:var(--muted);}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:40px;}
"""

def page(title, body, depth, crumbs=None):
    rel = "../" * depth if depth else "./"
    crumb_html = ""
    if crumbs:
        parts = []
        for label, href in crumbs:
            if href:
                parts.append(f'<a href="{href}">{esc(label)}</a>')
            else:
                parts.append(esc(label))
        crumb_html = f'<div class="crumbs">{" &rsaquo; ".join(parts)}</div>'
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{rel}style.css">
</head><body><div class="wrap">
{crumb_html}
{body}
<footer>Offline archive of forums.greaterthangames.com &middot; generated from local backup</footer>
</div></body></html>"""

def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

# ---------- pass 1: load all topics per top-level folder, grouped by category_id ----------
by_top = {}  # top_slug -> {cat_id: [topic_summary,...]}
topic_top_of = {}  # topic_id -> top_slug (needed to find its posts/topics dir)

for top_slug in TOP_SLUGS:
    folder = os.path.join(ROOT, top_slug)
    groups = {}
    for tid in os.listdir(os.path.join(folder, "topics")):
        tpath = os.path.join(folder, "topics", tid, "topic.json")
        if not os.path.exists(tpath):
            continue
        t = json.load(open(tpath))
        cid = t.get("category_id")
        groups.setdefault(cid, []).append({
            "id": t["id"],
            "title": t.get("title") or "(untitled)",
            "slug": t.get("slug") or "",
            "posts_count": t.get("posts_count") or 0,
            "reply_count": t.get("reply_count") or 0,
            "views": t.get("views") or 0,
            "created_at": t.get("created_at"),
            "last_posted_at": t.get("last_posted_at") or t.get("created_at"),
            "closed": t.get("closed"),
            "archived": t.get("archived"),
            "pinned_globally": t.get("pinned_globally"),
        })
        topic_top_of[t["id"]] = top_slug
        topic_location[t["id"]] = (top_slug, cid)
    by_top[top_slug] = groups

print("Loaded topics:", {k: sum(len(v) for v in g.values()) for k, g in by_top.items()})

# ---------- render topic detail pages ----------
def render_topic_page(top_slug, cid, tsum, out_topic_path, rel_to_out):
    folder = os.path.join(ROOT, top_slug)
    tid = tsum["id"]
    posts_all_path = os.path.join(folder, "posts", str(tid), "posts_all.json")
    posts_initial_path = os.path.join(folder, "posts", str(tid), "posts_initial.json")
    ppath = posts_all_path if os.path.exists(posts_all_path) else posts_initial_path
    posts = []
    if os.path.exists(ppath):
        d = json.load(open(ppath))
        posts = d.get("posts", [])
    posts.sort(key=lambda p: p.get("post_number") or 0)

    body_parts = [f'<h1>{esc(tsum["title"])}</h1>']
    tags = []
    if tsum.get("pinned_globally"): tags.append("pinned")
    if tsum.get("closed"): tags.append("closed")
    if tsum.get("archived"): tags.append("archived")
    if tags:
        body_parts.append('<div class="desc">' + " ".join(f'<span class="tag">{t}</span>' for t in tags) + '</div>')
    body_parts.append(f'<div class="desc">{tsum["posts_count"]} posts &middot; {tsum["views"]} views &middot; started {fmt_dt(tsum["created_at"])}</div>')

    for p in posts:
        uname = p.get("username") or p.get("display_username") or "unknown"
        if p.get("post_type") == 3:
            label = action_label(p.get("action_code"), p.get("action_code_who"))
            body_parts.append(
                f'<div class="small-action" id="post-{p.get("post_number")}">'
                f'<span class="who">{esc(uname)}</span> {esc(label)} '
                f'&middot; <span class="when">{fmt_dt(p.get("created_at"))}</span></div>'
            )
            continue
        avatar_html = f'<div class="avatar" style="background:{avatar_color(uname)}">{esc(initials(uname))}</div>'
        reply_note = ""
        if p.get("reply_to_post_number"):
            reply_note = f' <span class="when">(in reply to #{p["reply_to_post_number"]})</span>'
        cooked = p.get("cooked") or f"<p>{esc(p.get('raw',''))}</p>"
        cooked = process_cooked(cooked, top_slug, os.path.dirname(out_topic_path))
        body_parts.append(f"""<div class="post" id="post-{p.get('post_number')}">
  <div class="post-head">
    {avatar_html}
    <div><div class="who">{esc(uname)}</div><div class="when">{fmt_dt(p.get('created_at'))}{reply_note}</div></div>
    <div class="postnum">#{p.get('post_number')}</div>
  </div>
  <div class="post-body">{cooked}</div>
</div>""")

    crumbs = [("All Categories", f"{rel_to_out}/index.html")]
    top_name = cat_name(cat_id_for_top(top_slug))
    crumbs.append((top_name, f"{rel_to_out}/{top_slug}/index.html"))
    if cid != cat_id_for_top(top_slug):
        crumbs.append((cat_name(cid), f"{rel_to_out}/{top_slug}/{cat_slug(cid)}/index.html"))
    crumbs.append((tsum["title"], None))

    depth = out_topic_path.replace(OUT + "/", "").count("/")
    html_doc = page(tsum["title"], "\n".join(body_parts), depth, crumbs)
    write(out_topic_path, html_doc)

def cat_id_for_top(top_slug):
    for cid, m in cat_meta.items():
        if m["slug"] == top_slug and m["parent"] is None:
            return cid
    return None

# ---------- render topic list pages (paginated) with links to topic pages ----------
def render_listing(topics, section_dir, section_title, crumbs_prefix):
    topics_sorted = sorted(topics, key=lambda t: t["last_posted_at"] or "", reverse=True)
    n = len(topics_sorted)
    pages = max(1, math.ceil(n / PER_PAGE))
    for pi in range(pages):
        chunk = topics_sorted[pi*PER_PAGE:(pi+1)*PER_PAGE]
        rows = []
        for t in chunk:
            href = f"topics/{t['id']}.html"
            tagbits = ""
            if t.get("pinned_globally"): tagbits += '<span class="tag">pinned</span>'
            if t.get("closed"): tagbits += '<span class="tag">closed</span>'
            rows.append(f"""<div class="card topic-row">
  <div><a class="title" href="{href}">{esc(t['title'])}</a>{tagbits}</div>
  <div class="right">{t['posts_count']} posts &middot; {t['views']} views &middot; {fmt_dt(t['last_posted_at'])}</div>
</div>""")
        body = f'<h1>{esc(section_title)}</h1><div class="desc">{n} topics</div><div class="card-list">' + "\n".join(rows) + "</div>"

        pager = []
        if pages > 1:
            for p in range(pages):
                fname = "index.html" if p == 0 else f"page-{p+1}.html"
                if p == pi:
                    pager.append(f'<span class="current">{p+1}</span>')
                else:
                    pager.append(f'<a href="{fname}">{p+1}</a>')
            body += f'<div class="pager">{"".join(pager)}</div>'

        out_name = "index.html" if pi == 0 else f"page-{pi+1}.html"
        out_path = os.path.join(section_dir, out_name)
        depth = out_path.replace(OUT + "/", "").count("/")
        crumbs = crumbs_prefix + [(section_title, None)]
        write(out_path, page(section_title, body, depth, crumbs))

# ---------- main generation ----------
top_index_rows = []

for top_slug in TOP_SLUGS:
    tid_top = cat_id_for_top(top_slug)
    groups = by_top[top_slug]
    top_dir = os.path.join(OUT, top_slug)
    total_topics = sum(len(v) for v in groups.values())
    top_name = cat_name(tid_top)
    top_desc = cat_meta.get(tid_top, {}).get("description_text", "")

    # subcategory cards for the top-level index page
    sub_cards = []
    direct_topics = groups.get(tid_top, [])
    if direct_topics:
        sub_cards.append(f'<div class="card"><a class="title" href="general/index.html">General ({top_name})</a><div class="meta">{len(direct_topics)} topics posted directly in this category</div></div>')
    known_sub_ids = [cid for cid, m in cat_meta.items() if m["parent"] == tid_top]
    for cid in known_sub_ids:
        cnt = len(groups.get(cid, []))
        if cnt == 0:
            continue
        sub_cards.append(f'<div class="card"><a class="title" href="{cat_slug(cid)}/index.html">{esc(cat_name(cid))}</a><div class="meta">{cnt} topics</div></div>')
    # any category ids present in data but unknown in snapshot (shouldn't happen, but be safe)
    for cid in groups:
        if cid != tid_top and cid not in known_sub_ids:
            cnt = len(groups[cid])
            sub_cards.append(f'<div class="card"><a class="title" href="{cat_slug(cid)}/index.html">{esc(cat_name(cid))}</a><div class="meta">{cnt} topics</div></div>')

    body = f'<h1>{esc(top_name)}</h1>'
    if top_desc:
        body += f'<div class="desc">{esc(top_desc)}</div>'
    body += f'<div class="desc">{total_topics} topics total</div>'
    body += '<div class="card-list">' + "\n".join(sub_cards) + "</div>"
    write(os.path.join(top_dir, "index.html"), page(top_name, body, 1, [("All Categories", "../index.html"), (top_name, None)]))

    top_index_rows.append((top_name, top_slug, total_topics, top_desc))

    # render each group (direct + each subcategory) as its own listing section + topic pages
    for cid, topics in groups.items():
        if cid == tid_top:
            section_dir = os.path.join(top_dir, "general")
            section_title = f"{top_name} (general)"
            crumbs_prefix = [("All Categories", "../../index.html"), (top_name, "../index.html")]
        else:
            section_dir = os.path.join(top_dir, cat_slug(cid))
            section_title = cat_name(cid)
            crumbs_prefix = [("All Categories", "../../index.html"), (top_name, "../index.html")]

        render_listing(topics, section_dir, section_title, crumbs_prefix)

        topics_out_dir = os.path.join(section_dir, "topics")
        rel_to_out = os.path.relpath(OUT, topics_out_dir)
        for t in topics:
            out_topic_path = os.path.join(topics_out_dir, f"{t['id']}.html")
            render_topic_page(top_slug, cid, t, out_topic_path, rel_to_out)

# ---------- root index ----------
rows = []
for name, slug, count, desc in top_index_rows:
    rows.append(f'<div class="card"><a class="title" href="{slug}/index.html">{esc(name)}</a><div class="meta">{count} topics{" &middot; " + esc(desc) if desc else ""}</div></div>')
root_body = "<h1>Greater Than Games Forums &mdash; Offline Archive</h1><div class=\"desc\">Backed up from forums.greaterthangames.com</div><div class=\"card-list\">" + "\n".join(rows) + "</div>"
write(os.path.join(OUT, "index.html"), page("GTG Forums Archive", root_body, 0))

write(os.path.join(OUT, "style.css"), CSS)

print("DONE")
