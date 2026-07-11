#!/usr/bin/env python3
"""
Porch Project — static directory page generator.

Reads the public Google Sheet (same one directory.html uses) and writes one
real, crawlable HTML page per business, a crawlable index, and a sitemap.xml.

Why this exists: directory.html builds its list in the browser from the Sheet,
so Google sees an empty page. These generated pages put the business text into
the raw HTML so Google (and Facebook link previews) can actually read it.

No third-party packages — Python standard library only. Runs the same on your
Mac and on GitHub's servers (the GitHub Action).

Config comes from environment variables (the Action sets them) with sensible
defaults, so you can also just run:  python3 tools/build_directory.py
"""

import csv
import html
import io
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ─── Config (env vars override these defaults) ──────────────────────────────
SHEET_ID = os.environ.get("PP_SHEET_ID", "171eJCF7VLBDw4olLc5tSnQC3eiOMJ1JyQPm8wDXbsg8")
TAB = os.environ.get("PP_TAB", "Businesses")
SITE_URL = os.environ.get("PP_SITE_URL", "https://porchproject.co").rstrip("/")
COMMUNITY = os.environ.get("PP_COMMUNITY", "Steiner Ranch")
GA4_ID = os.environ.get("PP_GA4_ID", "G-P33RNWQCBJ").strip()  # site-wide GA4 id; env var overrides
# Where to write pages. Default: the folder this script lives in (the repo root).
OUTPUT_DIR = Path(os.environ.get("PP_OUTPUT_DIR", Path(__file__).resolve().parent))
# Optional: read from a local CSV file instead of the network (used for testing).
LOCAL_CSV = os.environ.get("PP_LOCAL_CSV", "").strip()

DIRECTORY_SUBPATH = "directory"  # pages live at /directory/<slug>/


# ─── Data loading ───────────────────────────────────────────────────────────
def load_rows():
    if LOCAL_CSV:
        text = Path(LOCAL_CSV).read_text(encoding="utf-8")
    else:
        url = (
            f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
            f"/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(TAB)}"
        )
        with urllib.request.urlopen(url, timeout=30) as resp:
            text = resp.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        # normalise keys to lowercase/stripped, like directory.html does
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if row.get("name"):
            rows.append(row)
    return rows


# ─── Helpers ────────────────────────────────────────────────────────────────
def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "business"


def unique_slugs(rows):
    seen, out = {}, []
    for r in rows:
        base = slugify(r["name"])
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(base if n == 0 else f"{base}-{n+1}")
    return out


def esc(s):
    return html.escape(s or "", quote=True)


def norm_url(u):
    u = (u or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u


def pipe_list(s):
    return [p.strip() for p in re.split(r"[|,]", s or "") if p.strip()]


def meta_desc(row):
    base = row.get("tagline") or row.get("description") or ""
    base = re.sub(r"\s+", " ", base).strip()
    return (base[:157] + "…") if len(base) > 158 else base


def ga4_head():
    if not GA4_ID:
        return ""
    return f"""  <script async src="https://www.googletagmanager.com/gtag/js?id={GA4_ID}"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', '{GA4_ID}');
  </script>
"""


def ga4_click_script():
    # Fires a GA4 event whenever a visitor clicks an outbound business link.
    if not GA4_ID:
        return ""
    return """  <script>
    document.addEventListener('click', function (e) {
      var a = e.target.closest('a[data-pp-track]');
      if (!a || typeof gtag !== 'function') return;
      gtag('event', 'business_link_click', {
        business: a.getAttribute('data-pp-business') || '',
        link_type: a.getAttribute('data-pp-track') || 'link',
        link_url: a.href
      });
    });
  </script>
"""


# ─── Page template ──────────────────────────────────────────────────────────
def contact_rows(row, biz_name):
    items = []

    def track(url, label, kind, extra=""):
        return (
            f'<a href="{esc(url)}" data-pp-track="{kind}" '
            f'data-pp-business="{esc(biz_name)}" '
            f'rel="noopener"{extra}>{esc(label)}</a>'
        )

    web = norm_url(row.get("website"))
    if web:
        shown = re.sub(r"^https?://(www\.)?", "", web).rstrip("/")
        items.append(("Website", track(web, shown, "website", ' target="_blank"')))
    if row.get("phone"):
        digits = re.sub(r"[^0-9+]", "", row["phone"])
        items.append(("Phone", track("tel:" + digits, row["phone"], "phone")))
    if row.get("email"):
        items.append(("Email", track("mailto:" + row["email"], row["email"], "email")))
    if row.get("address"):
        items.append(("Address", esc(row["address"])))
    if row.get("hours"):
        items.append(("Hours", esc(row["hours"])))
    for key, label in (("facebook", "Facebook"), ("instagram", "Instagram"),
                       ("linkedin", "LinkedIn"), ("other", "More")):
        val = norm_url(row.get(key))
        if val:
            items.append((label, track(val, label, "social", ' target="_blank"')))

    lis = "\n".join(
        f'      <div class="pp-row"><span class="pp-row-k">{k}</span>'
        f'<span class="pp-row-v">{v}</span></div>'
        for k, v in items
    )
    return lis


def json_ld(row, url):
    import json
    data = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": row["name"],
        "url": url,
        "areaServed": COMMUNITY,
    }
    if row.get("description"):
        data["description"] = re.sub(r"\s+", " ", row["description"]).strip()
    if norm_url(row.get("website")):
        data["sameAs"] = [norm_url(row["website"])]
    if row.get("phone"):
        data["telephone"] = row["phone"]
    if row.get("email"):
        data["email"] = row["email"]
    if row.get("address"):
        data["address"] = row["address"]
    if norm_url(row.get("logo url") or row.get("logo")):
        data["image"] = norm_url(row.get("logo url") or row.get("logo"))
    return json.dumps(data, ensure_ascii=False, indent=2)


def business_page(row, slug):
    name = row["name"]
    url = f"{SITE_URL}/{DIRECTORY_SUBPATH}/{slug}/"
    title = f"{name} — {COMMUNITY} | Porch Project"
    desc = meta_desc(row)
    logo = norm_url(row.get("logo url") or row.get("logo"))
    badge = (row.get("badge") or "verified").lower()
    badge_label = "Porch Neighbor" if badge == "neighbor" else "Porch Verified"
    cats = pipe_list(row.get("categories")) + pipe_list(row.get("subcategories"))
    cat_html = ""
    if cats:
        chips = "".join(f'<span class="pp-chip">{esc(c)}</span>' for c in dict.fromkeys(cats))
        cat_html = f'<div class="pp-chips">{chips}</div>'
    desc_html = ""
    if row.get("description"):
        paras = [esc(p) for p in re.split(r"\n\s*\n", row["description"]) if p.strip()]
        desc_html = "".join(f"<p>{p}</p>" for p in paras)
    og_image = f'\n  <meta property="og:image" content="{esc(logo)}">' if logo else ""
    logo_html = (
        f'<img class="pp-logo" src="{esc(logo)}" alt="{esc(name)} logo">' if logo
        else f'<div class="pp-logo pp-logo-ph">{esc("".join(w[0] for w in name.split()[:2]).upper())}</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(desc)}">
  <link rel="canonical" href="{esc(url)}">
  <meta property="og:type" content="business.business">
  <meta property="og:title" content="{esc(name)} — {esc(COMMUNITY)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:url" content="{esc(url)}">{og_image}
  <meta name="twitter:card" content="summary">
  <link rel="stylesheet" href="../../styles.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Cormorant+Garamond:wght@500;600&display=swap" rel="stylesheet">
  <script type="application/ld+json">
{json_ld(row, url)}
  </script>
  <style>
    .pp-page{{max-width:720px;margin:0 auto;padding:24px 20px 64px;font-family:'DM Sans',-apple-system,sans-serif;color:#2b2b2b;line-height:1.6}}
    .pp-back{{display:inline-block;margin-bottom:24px;color:#6b6b6b;text-decoration:none;font-size:.95rem}}
    .pp-back:hover{{color:#2b2b2b}}
    .pp-head{{display:flex;gap:18px;align-items:center;margin-bottom:8px}}
    .pp-logo{{width:72px;height:72px;border-radius:14px;object-fit:contain;background:#fff;border:1px solid #eee;flex:none}}
    .pp-logo-ph{{display:flex;align-items:center;justify-content:center;font-family:'Cormorant Garamond',serif;font-size:1.6rem;color:#8a6d3b;background:#f3ede1}}
    h1{{font-family:'Cormorant Garamond',Georgia,serif;font-size:2.1rem;margin:0;font-weight:600}}
    .pp-tagline{{color:#6b6b6b;margin:2px 0 0}}
    .pp-badge{{display:inline-block;margin:14px 0;padding:4px 12px;border-radius:999px;font-size:.8rem;font-weight:600;background:#eaf3ea;color:#356a3a}}
    .pp-chips{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 20px}}
    .pp-chip{{background:#f3ede1;color:#7a6231;padding:4px 12px;border-radius:999px;font-size:.82rem}}
    .pp-desc p{{margin:0 0 14px}}
    .pp-contact{{margin-top:26px;border-top:1px solid #eee;padding-top:20px}}
    .pp-row{{display:flex;gap:14px;padding:7px 0;border-bottom:1px solid #f4f4f4;font-size:.98rem}}
    .pp-row-k{{flex:none;width:88px;color:#9a9a9a;font-weight:500}}
    .pp-row-v a{{color:#356a3a;text-decoration:none}}
    .pp-row-v a:hover{{text-decoration:underline}}
    .pp-foot{{margin-top:40px;font-size:.9rem;color:#9a9a9a}}
    .pp-foot a{{color:#356a3a;text-decoration:none}}
  </style>
{ga4_head()}</head>
<body>
  <main class="pp-page">
    <a class="pp-back" href="{SITE_URL}/directory.html">← Back to the {esc(COMMUNITY)} directory</a>
    <div class="pp-head">
      {logo_html}
      <div>
        <h1>{esc(name)}</h1>
        {f'<p class="pp-tagline">{esc(row["tagline"])}</p>' if row.get("tagline") else ''}
      </div>
    </div>
    <div><span class="pp-badge">{esc(badge_label)}</span></div>
    {cat_html}
    <div class="pp-desc">{desc_html}</div>
    <section class="pp-contact">
{contact_rows(row, name)}
    </section>
    <p class="pp-foot">Listed in the <a href="{SITE_URL}/directory.html">{esc(COMMUNITY)} neighborhood directory</a> · <a href="{SITE_URL}/">Porch Project</a></p>
  </main>
{ga4_click_script()}</body>
</html>
"""


def index_page(entries):
    """A plain, crawlable hub listing every business (helps Google find them)."""
    by_cat = {}
    for e in entries:
        cat = e["cat"] or "Other"
        by_cat.setdefault(cat, []).append(e)
    blocks = []
    for cat in sorted(by_cat):
        def li(e):
            tag = f' — {esc(e["tagline"])}' if e["tagline"] else ""
            return f'      <li><a href="{esc(e["slug"])}/">{esc(e["name"])}</a>{tag}</li>'
        links = "\n".join(li(e) for e in sorted(by_cat[cat], key=lambda x: x["name"].lower()))
        blocks.append(f'    <h2>{esc(cat)}</h2>\n    <ul>\n{links}\n    </ul>')
    body = "\n".join(blocks)
    url = f"{SITE_URL}/{DIRECTORY_SUBPATH}/"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(COMMUNITY)} Neighborhood Business Directory | Porch Project</title>
  <meta name="description" content="A directory of local businesses recommended by {esc(COMMUNITY)} neighbors — verified and neighbor-owned.">
  <link rel="canonical" href="{esc(url)}">
  <link rel="stylesheet" href="../styles.css">
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Cormorant+Garamond:wght@500;600&display=swap" rel="stylesheet">
  <style>
    .pp-page{{max-width:760px;margin:0 auto;padding:32px 20px 64px;font-family:'DM Sans',sans-serif;color:#2b2b2b;line-height:1.6}}
    h1{{font-family:'Cormorant Garamond',serif;font-size:2.4rem;font-weight:600;margin:0 0 6px}}
    h2{{font-family:'Cormorant Garamond',serif;font-size:1.4rem;color:#7a6231;margin:28px 0 8px}}
    ul{{list-style:none;padding:0;margin:0}}
    li{{padding:6px 0;border-bottom:1px solid #f4f4f4}}
    a{{color:#356a3a;text-decoration:none}} a:hover{{text-decoration:underline}}
    .pp-intro{{color:#6b6b6b;margin-bottom:8px}}
  </style>
{ga4_head()}</head>
<body>
  <main class="pp-page">
    <h1>{esc(COMMUNITY)} Business Directory</h1>
    <p class="pp-intro">Local businesses recommended by {esc(COMMUNITY)} neighbors. Also browse the <a href="{SITE_URL}/directory.html">interactive directory</a>.</p>
{body}
  </main>
</body>
</html>
"""


def sitemap(urls, lastmod):
    items = "\n".join(
        f"  <url><loc>{esc(u)}</loc><lastmod>{lastmod}</lastmod></url>" for u in urls
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.w3.org/2000/schemas/sitemap-image">\n'.replace(
            "www.w3.org/2000/schemas/sitemap-image",
            "www.sitemaps.org/schemas/sitemap/0.9",
        )
        + items
        + "\n</urlset>\n"
    )


# ─── Main ───────────────────────────────────────────────────────────────────
def main():
    rows = load_rows()
    slugs = unique_slugs(rows)
    dir_root = OUTPUT_DIR / DIRECTORY_SUBPATH
    dir_root.mkdir(parents=True, exist_ok=True)

    entries, biz_urls = [], []
    for row, slug in zip(rows, slugs):
        page_dir = dir_root / slug
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(business_page(row, slug), encoding="utf-8")
        url = f"{SITE_URL}/{DIRECTORY_SUBPATH}/{slug}/"
        biz_urls.append(url)
        entries.append({
            "slug": slug, "name": row["name"],
            "tagline": row.get("tagline", ""),
            "cat": (pipe_list(row.get("categories")) or [""])[0],
        })

    (dir_root / "index.html").write_text(index_page(entries), encoding="utf-8")

    lastmod = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_urls = [
        f"{SITE_URL}/",
        f"{SITE_URL}/directory.html",
        f"{SITE_URL}/{DIRECTORY_SUBPATH}/",
    ] + biz_urls
    (OUTPUT_DIR / "sitemap.xml").write_text(sitemap(all_urls, lastmod), encoding="utf-8")

    print(f"Generated {len(rows)} business pages")
    print(f"  → {dir_root}/<slug>/index.html")
    print(f"  → {dir_root}/index.html (crawlable hub)")
    print(f"  → {OUTPUT_DIR / 'sitemap.xml'}")
    print(f"GA4 tracking: {'ON (' + GA4_ID + ')' if GA4_ID else 'OFF (no PP_GA4_ID set yet)'}")


if __name__ == "__main__":
    # csv field size + urllib.parse import guard
    import urllib.parse  # noqa: E402
    csv.field_size_limit(sys.maxsize)
    main()
