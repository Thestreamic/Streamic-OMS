"""
scripts/build_static.py — The Streamic simple hand-authored site builder.

Replaces the old fragile RSS / generated_articles.json pipeline.
Reads data/manual_articles.json as the single source of truth.

Usage:
    python3 scripts/build_static.py

To add a new article:
    1. Create docs/articles/<slug>.html
    2. Add one entry to data/manual_articles.json
    3. Upload image to docs/articles/images/ (or docs/assets/)
    4. Commit and push — GitHub Actions will run this script.
"""

import json
import os
import re
import shutil
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT        = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS        = os.path.join(ROOT, "docs")
ARTS_DIR    = os.path.join(DOCS, "articles")
DATA_DIR    = os.path.join(ROOT, "data")
MANIFEST    = os.path.join(DATA_DIR, "manual_articles.json")
BASE_URL    = os.environ.get("SITE_BASE_URL", "https://www.thestreamic.in").rstrip("/")
GA          = "G-0VSHDN3ZR6"
AUTHOR      = "The Streamic Editorial Team"
FALLBACK_IMG = "articles/images/streamic-default.jpg"

# ── Category config ───────────────────────────────────────────────────────
CATEGORIES = {
    "ai-post-production": {
        "label": "AI in Broadcasting",
        "icon": "🎬",
        "color": "#FF2D55",
        "page": "ai-post-production.html",
        "desc": "AI-driven editing tools, automated QC, intelligent MAM, colour grading.",
    },
    "post-production-workflows": {
        "label": "Post Production Workflows",
        "icon": "🎞️",
        "color": "#5856d6",
        "page": "post-production-workflows.html",
        "desc": "NLE interoperability, proxy pipelines, MAM/PAM integration, cloud post.",
    },
    "howto": {
        "label": "How-To Guides",
        "icon": "🔧",
        "color": "#34C759",
        "page": "howto.html",
        "desc": "Step-by-step guides for broadcast engineers and post-production teams.",
    },
    "insights": {
        "label": "Expert Insights",
        "icon": "💡",
        "color": "#FF9500",
        "page": "insights.html",
        "desc": "Long-form analysis and interviews with broadcast and media IT professionals.",
    },
    "editorsdesk": {
        "label": "Editorial Insights",
        "icon": "✍️",
        "color": "#b8860b",
        "page": "editorsdesk.html",
        "desc": "Commentary, perspective, and engineering analysis from the Streamic editorial team.",
    },
}

# ── Section config ────────────────────────────────────────────────────────
SECTIONS = {
    "latest-insights",
    "media-it-updates",
    "workflow-deep-dives",
    "howto-guides",
    "editorial-insights",
}

# ── Helpers ───────────────────────────────────────────────────────────────
def e(s):
    """HTML-escape a string."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))

def fmt_date(iso):
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%B %d, %Y")
    except Exception:
        return iso

def w(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def resolve_image(img_field, base=""):
    """
    Return the best available image path.
    img_field is a public relative path like 'articles/images/foo.jpg'
    or 'assets/foo.png'.
    Returns the public path to use in HTML (relative to docs/).
    Falls back to FALLBACK_IMG if file not found.
    """
    if not img_field or not img_field.strip():
        return f"{base}{FALLBACK_IMG}"
    # Strip leading slash for consistency
    rel = img_field.lstrip("/")
    disk_path = os.path.join(DOCS, rel)
    if os.path.exists(disk_path):
        return f"{base}{rel}"
    # Try the fallback
    fallback_disk = os.path.join(DOCS, FALLBACK_IMG)
    if os.path.exists(fallback_disk):
        return f"{base}{FALLBACK_IMG}"
    # Last resort: return original, let browser handle it
    return f"{base}{rel}"


# ── Shared HTML blocks ────────────────────────────────────────────────────
def _consent_gtag():
    return f"""<script>
    window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}
    gtag('consent','default',{{'analytics_storage':'denied','ad_storage':'denied',
    'ad_user_data':'denied','ad_personalization':'denied','wait_for_update':500}});
  </script>
  <script async src="https://www.googletagmanager.com/gtag/js?id={GA}"></script>
  <script>gtag('js',new Date());gtag('config','{GA}');</script>"""

def _fonts():
    return ('<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display'
            '&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">')

def head(title, desc, canon, css="style.css", og_img="", robots="index,follow"):
    css_prefix = css[:-len("style.css")] if css.endswith("style.css") else ""
    hp_css = f"{css_prefix}homepage-layout.css"
    og_img_tag = f'  <meta property="og:image" content="{e(og_img)}">\n' if og_img else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  {_consent_gtag()}
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{e(title)}</title>
  <meta name="description" content="{e(desc)}">
  <meta name="robots" content="{robots}">
  <meta name="author" content="{AUTHOR}">
  <link rel="canonical" href="{e(canon)}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="The Streamic">
  <meta property="og:title" content="{e(title)}">
  <meta property="og:description" content="{e(desc)}">
  <meta property="og:url" content="{e(canon)}">
{og_img_tag}  <meta name="twitter:card" content="summary_large_image">
  {_fonts()}
  <link rel="stylesheet" href="{css}">
  <link rel="stylesheet" href="{hp_css}">
</head>"""

def nav(active="", base=""):
    cats = [
        ("/",                               "Home"),
        ("ai-post-production.html",         "AI in Broadcasting"),
        ("howto.html",                      "How-To Guides"),
        ("post-production-workflows.html",  "Post Production Workflows"),
        ("insights.html",                   "Expert Insights"),
        ("editorsdesk.html",                "Editorial Insights"),
    ]
    def li(h, lbl):
        cls = ' class="active"' if h == active else ""
        href = h if h.startswith("/") else f"{base}{h}"
        return f'<li><a href="{href}"{cls}>{lbl}</a></li>'
    lis = "".join(li(h, l) for h, l in cats)
    mob_all = cats + [("about.html", "About"), ("contact.html", "Contact")]
    mob = "".join(f'<a href="{h if h.startswith("/") else base+h}">{l}</a>'
                  for h, l in mob_all)
    toggle = (
        'onclick="(function(b,m){'
        "m.classList.toggle('open');"
        "b.setAttribute('aria-expanded',m.classList.contains('open'));"
        "document.body.classList.toggle('menu-open',m.classList.contains('open'));"
        '})(this,this.closest(\'nav\').querySelector(\'.nav-mob\'))"'
    )
    return f"""<nav class="nav">
  <div class="nav-inner">
    <a href="{base if base else '/'}" class="nav-logo">
      <img src="{base}assets/logo.png" alt="" onerror="this.style.display='none'" aria-hidden="true">
      <div class="nav-logo-text">
        <span class="nav-logo-name">The Streamic</span>
        <span class="nav-logo-tagline">Media &amp; Broadcast IT Analysis</span>
      </div>
    </a>
    <div class="nav-divider" aria-hidden="true"></div>
    <ul class="nav-links">{lis}</ul>
    <div class="nav-right">
      <a href="{base}about.html" class="nav-desk">About</a>
      <button class="nav-toggle" aria-label="Menu" type="button" {toggle}>
        <span></span><span></span><span></span>
      </button>
    </div>
  </div>
  <div class="nav-gold" aria-hidden="true"></div>
  <div class="nav-mob">{mob}</div>
</nav>"""

def footer(base=""):
    yr = datetime.now().year
    return f"""<footer class="footer">
  <div class="footer-gold" aria-hidden="true"></div>
  <div class="footer-grid">
    <div>
      <div class="footer-brand">The Streamic</div>
      <div class="footer-tagline">Media &amp; Broadcast IT Analysis</div>
      <p class="footer-tag">Independent broadcast &amp; streaming technology journalism. Original analysis for engineers and media professionals.</p>
      <div class="footer-social">
        <a href="https://twitter.com/thestreamic" target="_blank" rel="noopener noreferrer" class="footer-social-link">
          <svg width="14" height="14" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
          @thestreamic
        </a>
        <a href="https://www.linkedin.com/company/thestreamic" target="_blank" rel="noopener noreferrer" class="footer-social-link">
          <svg width="14" height="14" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
          TheStreamic
        </a>
      </div>
    </div>
    <div class="footer-col">
      <h4>Coverage</h4>
      <a href="{base}ai-post-production.html">AI in Broadcasting</a>
      <a href="{base}howto.html">How-To Guides</a>
      <a href="{base}post-production-workflows.html">Post Production Workflows</a>
      <a href="{base}insights.html">Expert Insights</a>
      <a href="{base}editorsdesk.html">Editorial Insights</a>
    </div>
    <div class="footer-col">
      <h4>Site</h4>
      <a href="{base}about.html">About</a>
      <a href="{base}contact.html">Contact</a>
      <a href="{base}editorial-policy.html">Editorial Policy</a>
      <a href="{base}privacy.html">Privacy Policy</a>
      <a href="{base}terms.html">Terms of Use</a>
    </div>
    <div class="footer-col">
      <h4>Dublin, Ireland</h4>
      <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a>
      <span style="font-size:12px;color:#bbb;display:block;margin-top:4px">Adamstown, Lucan</span>
    </div>
  </div>
  <div class="footer-bottom">
    <span>&copy; {yr} The Streamic &mdash; thestreamic.in</span>
    <span>All trademarks belong to their respective owners.</span>
  </div>
</footer>"""

def cookie_banner():
    return """<div id="ts-cookie">
  <div class="cookie-in">
    <div class="cookie-txt">
      <strong>We use cookies</strong>
      Analytics cookies help us understand site performance. Optional advertising cookies are disabled until future activation.
      <a href="/privacy.html">Privacy Policy</a>
    </div>
    <div class="cookie-btns">
      <button class="cookie-no" onclick="tsCC(false)">Reject optional</button>
      <button class="cookie-ok" onclick="tsCC(true)">Accept all</button>
    </div>
  </div>
</div>
<script>
(function(){
  var K='ts_cc',s=localStorage.getItem(K),b=document.getElementById('ts-cookie');
  if(!s&&b)b.style.display='block';
  window.tsCC=function(ok){
    localStorage.setItem(K,ok?'granted':'denied');
    if(b)b.style.display='none';
    if(typeof gtag!='undefined')gtag('consent','update',{
      analytics_storage:ok?'granted':'denied',ad_storage:'denied',
      ad_user_data:'denied',ad_personalization:'denied'});
  };
  if(s==='granted'&&typeof gtag!='undefined')gtag('consent','update',{
    analytics_storage:'granted',ad_storage:'denied',
    ad_user_data:'denied',ad_personalization:'denied'});
})();
</script>"""


# ── Card component ────────────────────────────────────────────────────────
def article_card(a, base=""):
    """Render one editorial article card. Used on homepage sections and category pages."""
    slug  = a["slug"]
    href  = f"{base}articles/{slug}.html"
    img   = resolve_image(a.get("image", ""), base)
    title = e(a.get("title", ""))
    desc  = e(a.get("description", ""))
    date  = fmt_date(a.get("date", ""))
    cat   = a.get("category", "ai-post-production")
    cinfo = CATEGORIES.get(cat, CATEGORIES["ai-post-production"])
    lbl   = e(cinfo["label"])
    col   = cinfo["color"]
    icon  = cinfo["icon"]
    fb    = f"{base}assets/fallback.jpg"

    return f"""<a href="{href}" class="sc-card">
  <div class="sc-card-img">
    <img src="{img}" alt="{title}" loading="lazy"
         onerror="this.onerror=null;this.src='{fb}'">
  </div>
  <div class="sc-card-body">
    <span class="sc-card-tag" style="color:{col}">{icon} {lbl}</span>
    <h3 class="sc-card-title">{title}</h3>
    <p class="sc-card-desc">{desc}</p>
    <div class="sc-card-foot">
      <time class="sc-card-date">{date}</time>
      <span class="sc-card-read">Read analysis &#8594;</span>
    </div>
  </div>
</a>"""


# ── Card grid CSS (injected once in every page that uses cards) ───────────
CARD_CSS = """<style>
/* ── Streamic static article cards ──────────────────────────── */
.sc-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;margin:24px 0 40px}
.sc-card{display:flex;flex-direction:column;background:#fff;border:1px solid rgba(0,0,0,.07);
  border-radius:14px;overflow:hidden;text-decoration:none;color:inherit;
  transition:transform .28s cubic-bezier(.2,.8,.2,1),box-shadow .28s cubic-bezier(.2,.8,.2,1),border-color .2s}
.sc-card:hover{transform:translateY(-3px);box-shadow:0 14px 36px rgba(0,0,0,.10);border-color:rgba(0,0,0,.13)}
.sc-card-img{aspect-ratio:16/10;overflow:hidden;background:#e8e8ed;flex-shrink:0}
.sc-card-img img{width:100%;height:100%;object-fit:cover;object-position:center;display:block;
  transition:transform .45s ease}
.sc-card:hover .sc-card-img img{transform:scale(1.04)}
.sc-card-body{display:flex;flex-direction:column;flex:1;padding:18px 18px 16px;gap:8px}
.sc-card-tag{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.08em}
.sc-card-title{font-family:'DM Serif Display',Georgia,serif;font-size:18px;line-height:1.25;
  letter-spacing:-.015em;color:#1d1d1f;display:-webkit-box;-webkit-line-clamp:3;
  -webkit-box-orient:vertical;overflow:hidden}
.sc-card:hover .sc-card-title{color:#0066cc}
.sc-card-desc{font-size:13.5px;line-height:1.55;color:#6e6e73;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;
  flex:1}
.sc-card-foot{display:flex;align-items:center;justify-content:space-between;
  padding-top:12px;border-top:1px solid rgba(0,0,0,.06);margin-top:auto}
.sc-card-date{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:#86868b}
.sc-card-read{font-size:12px;font-weight:600;color:#0066cc}
/* Section headers */
.sc-sec-hdr{display:flex;align-items:baseline;justify-content:space-between;
  gap:16px;padding-bottom:10px;border-bottom:2px solid #1d1d1f;margin-bottom:6px}
.sc-sec-hdr h2{font-family:'DM Serif Display',Georgia,serif;font-size:18px;
  letter-spacing:-.03em;margin:0}
.sc-sec-intro{font-size:13px;color:#6e6e73;margin-bottom:20px;line-height:1.55}
/* Cat header */
.sc-cat-hdr{padding:40px 0 8px}
.sc-cat-hdr h1{font-family:'DM Serif Display',Georgia,serif;
  font-size:clamp(28px,4vw,42px);letter-spacing:-.03em;margin-bottom:8px}
.sc-cat-hdr p{font-size:15px;color:#6e6e73;max-width:700px;line-height:1.65}
/* Responsive */
@media(max-width:900px){.sc-grid{grid-template-columns:repeat(2,1fr);gap:18px}}
@media(max-width:580px){.sc-grid{grid-template-columns:1fr;gap:14px}
  .sc-card-title{font-size:17px}
  .sc-card-img{aspect-ratio:3/2}}
</style>"""


# ── Homepage builder ──────────────────────────────────────────────────────
def build_homepage(articles):
    """Build docs/index.html and docs/featured.html."""
    published = [a for a in articles if a.get("status") == "published"]

    latest    = [a for a in published if a.get("section") == "latest-insights"]
    media_it  = [a for a in published if a.get("section") == "media-it-updates"]
    deep_dive = [a for a in published if a.get("section") == "workflow-deep-dives"]
    editorial = [a for a in published if a.get("section") == "editorial-insights"]

    # Hero = first featured article, or first latest-insights article
    hero = next((a for a in published if a.get("featured")), latest[0] if latest else None)

    def _section(title, link_href, link_lbl, arts, intro=""):
        if not arts:
            return ""
        cards = "\n".join(article_card(a) for a in arts[:6])
        view_all = f'<a href="{link_href}">{link_lbl} &#8594;</a>' if link_href else ""
        intro_html = f'<p class="sc-sec-intro">{e(intro)}</p>' if intro else ""
        return f"""<section style="margin-bottom:48px">
  <div class="sc-sec-hdr"><h2>{e(title)}</h2>{view_all}</div>
  {intro_html}
  <div class="sc-grid">{cards}</div>
</section>"""

    # Hero block
    hero_html = ""
    if hero:
        img  = resolve_image(hero.get("image", ""))
        cat  = hero.get("category", "ai-post-production")
        ci   = CATEGORIES.get(cat, CATEGORIES["ai-post-production"])
        href = f"articles/{hero['slug']}.html"
        hero_html = f"""<section class="hp-hero" aria-label="Featured story">
  <a href="{href}" class="hp-hero-img-link" tabindex="-1" aria-hidden="true">
    <img class="hp-hero-img" src="{img}" alt="{e(hero.get('title',''))}"
         loading="eager" onerror="this.onerror=null;this.src='assets/fallback.jpg'">
  </a>
  <div class="hp-hero-overlay" aria-hidden="true"></div>
  <div class="hp-hero-body">
    <span class="hp-hero-tag">{e(ci['icon'])} {e(ci['label'])}</span>
    <h1 class="hp-hero-hl"><a href="{href}">{e(hero.get('title',''))}</a></h1>
    <div class="hp-hero-meta">
      <span>{e(AUTHOR)}</span><span>&#124;</span>
      <span>{fmt_date(hero.get('date',''))}</span>
    </div>
    <a href="{href}" class="hp-hero-cta">Read Analysis <span class="hp-hero-cta__arrow">&#8594;</span></a>
  </div>
</section>"""

    latest_section = _section(
        "Latest Insights", "ai-post-production.html", "View all",
        [a for a in latest if a is not hero],
        "Original Streamic analysis on broadcast automation, IP infrastructure, cloud production, and editorial operations — selected for depth, not noise."
    )
    media_section = _section(
        "Latest Media IT Updates", "", "",
        media_it
    )
    deep_section = _section(
        "Workflow Deep Dives", "post-production-workflows.html", "View all",
        deep_dive
    )
    ed_section = _section(
        "Editorial Insights", "editorsdesk.html", "View all",
        editorial
    )

    title_str = "The Streamic — Broadcast &amp; Media IT Analysis"
    desc_str  = "Independent broadcast and streaming technology journalism. Original analysis for engineers and media professionals."
    canon     = f"{BASE_URL}/"
    og_img    = resolve_image(hero.get("image","")) if hero else ""
    if og_img and not og_img.startswith("http"):
        og_img = f"{BASE_URL}/{og_img}"

    html = f"""{head(title_str, desc_str, canon, og_img=og_img)}
{CARD_CSS}
<body data-category="featured">
{nav("/")}
<main>
  {hero_html}
  <div class="w" style="padding-top:36px">
    {latest_section}
    {media_section}
    {deep_section}
    {ed_section}
  </div>
</main>
{footer()}
{cookie_banner()}
<script src="main.js" defer></script>
</body>
</html>"""

    w(os.path.join(DOCS, "index.html"),    html)
    w(os.path.join(DOCS, "featured.html"), html)
    return len(published)


# ── Category page builder ─────────────────────────────────────────────────
def build_category_page(cat_key, articles):
    ci       = CATEGORIES[cat_key]
    published = [a for a in articles
                 if a.get("status") == "published" and a.get("category") == cat_key]
    canon    = f"{BASE_URL}/{ci['page']}"
    title    = f"{ci['label']} — The Streamic"
    desc     = ci["desc"]

    cards = "\n".join(article_card(a) for a in published) if published else (
        '<p style="color:var(--ink4);padding:40px 0">No articles published yet in this category.</p>'
    )

    html = f"""{head(title, desc, canon)}
{CARD_CSS}
<body data-category="{cat_key}">
{nav(ci['page'])}
<main>
  <div class="w">
    <div class="sc-cat-hdr">
      <h1>{ci['icon']} {ci['label']}</h1>
      <p>{e(desc)}</p>
    </div>
    <div class="sc-grid">{cards}</div>
  </div>
</main>
{footer()}
{cookie_banner()}
<script src="main.js" defer></script>
</body>
</html>"""

    out = os.path.join(DOCS, ci["page"])
    w(out, html)
    return len(published)


# ── Sitemap ───────────────────────────────────────────────────────────────
def build_sitemap(articles):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    published = [a for a in articles if a.get("status") == "published"]

    statics = [
        ("",                               "daily",   "1.0"),
        ("featured.html",                  "daily",   "0.95"),
        ("ai-post-production.html",        "weekly",  "0.90"),
        ("post-production-workflows.html", "weekly",  "0.85"),
        ("howto.html",                     "weekly",  "0.85"),
        ("insights.html",                  "weekly",  "0.85"),
        ("editorsdesk.html",               "weekly",  "0.85"),
        ("about.html",                     "monthly", "0.60"),
        ("contact.html",                   "monthly", "0.55"),
        ("editorial-policy.html",          "monthly", "0.55"),
        ("privacy.html",                   "yearly",  "0.30"),
        ("terms.html",                     "yearly",  "0.30"),
    ]

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for pg, freq, pri in statics:
        lines.append(
            f'  <url><loc>{BASE_URL}/{pg}</loc>'
            f'<lastmod>{today}</lastmod>'
            f'<changefreq>{freq}</changefreq>'
            f'<priority>{pri}</priority></url>'
        )
    for a in published:
        slug = a["slug"]
        pub  = a.get("date", today)
        lines.append(
            f'  <url><loc>{BASE_URL}/articles/{slug}.html</loc>'
            f'<lastmod>{pub}</lastmod>'
            f'<changefreq>monthly</changefreq>'
            f'<priority>0.75</priority></url>'
        )
    lines.append('</urlset>')
    w(os.path.join(DOCS, "sitemap.xml"), "\n".join(lines))


# ── Robots ────────────────────────────────────────────────────────────────
def build_robots():
    content = f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n"
    w(os.path.join(DOCS, "robots.txt"), content)


# ── Asset copy ────────────────────────────────────────────────────────────
def copy_assets():
    """Copy root-level style.css, homepage-layout.css, main.js into docs/ if they exist at root."""
    for fn in ("style.css", "homepage-layout.css", "main.js"):
        src = os.path.join(ROOT, fn)
        dst = os.path.join(DOCS, fn)
        if os.path.isfile(src) and not os.path.isfile(dst):
            shutil.copy2(src, dst)
    # Ensure static files exist
    for fn in ("ads.txt", "CNAME"):
        src = os.path.join(ROOT, fn)
        dst = os.path.join(DOCS, fn)
        if os.path.isfile(src) and not os.path.isfile(dst):
            shutil.copy2(src, dst)
    # .nojekyll
    nj = os.path.join(DOCS, ".nojekyll")
    if not os.path.exists(nj):
        open(nj, "w").close()


# ── Validate manifest ─────────────────────────────────────────────────────
def load_and_validate():
    if not os.path.isfile(MANIFEST):
        raise SystemExit(f"✗ Manifest not found: {MANIFEST}")

    with open(MANIFEST, "r", encoding="utf-8") as f:
        raw = json.load(f)

    valid   = []
    warns   = []
    skipped = 0

    for entry in raw:
        slug = entry.get("slug", "").strip()
        if not slug:
            warns.append("  ⚠ Entry missing slug — skipped")
            skipped += 1
            continue

        if entry.get("status") != "published":
            skipped += 1
            continue

        # Validate required fields
        for req in ("title", "date", "category"):
            if not entry.get(req):
                warns.append(f"  ⚠ {slug}: missing '{req}' — skipped")
                skipped += 1
                break
        else:
            # Check category is known
            cat = entry.get("category", "")
            if cat not in CATEGORIES:
                warns.append(f"  ⚠ {slug}: unknown category '{cat}' — skipped")
                skipped += 1
                continue

            # Check section is known (not fatal — default to latest-insights)
            sec = entry.get("section", "")
            if sec and sec not in SECTIONS:
                warns.append(f"  ⚠ {slug}: unknown section '{sec}' — defaulting to latest-insights")
                entry["section"] = "latest-insights"

            # Check article HTML exists
            html_path = os.path.join(ARTS_DIR, f"{slug}.html")
            if not os.path.isfile(html_path):
                warns.append(f"  ⚠ {slug}: docs/articles/{slug}.html not found — card skipped")
                skipped += 1
                continue

            valid.append(entry)

    return valid, warns, skipped


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    print()
    print("═" * 60)
    print("  The Streamic — build_static.py")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 60)

    # 1. Load + validate manifest
    articles, warns, skipped = load_and_validate()

    for w_msg in warns:
        print(w_msg)
    if warns:
        print()

    print(f"  ✓ Loaded {len(articles)} published articles ({skipped} skipped/unpublished)")

    # 2. Copy assets
    copy_assets()
    print("  ✓ Assets verified")

    # 3. Build homepage
    n = build_homepage(articles)
    print(f"  ✓ Homepage built (index.html + featured.html) — {n} articles")

    # 4. Build category pages
    for cat_key in CATEGORIES:
        count = build_category_page(cat_key, articles)
        page  = CATEGORIES[cat_key]["page"]
        print(f"  ✓ {page} ({count} articles)")

    # 5. Sitemap + robots
    build_sitemap(articles)
    print("  ✓ sitemap.xml")
    build_robots()
    print("  ✓ robots.txt")

    # 6. Validation summary
    print()
    print("── Validation ──────────────────────────────────────────")

    checks = {
        "docs/index.html exists":                os.path.isfile(os.path.join(DOCS, "index.html")),
        "docs/featured.html exists":             os.path.isfile(os.path.join(DOCS, "featured.html")),
        "docs/ai-post-production.html exists":   os.path.isfile(os.path.join(DOCS, "ai-post-production.html")),
        "docs/post-production-workflows.html":   os.path.isfile(os.path.join(DOCS, "post-production-workflows.html")),
        "docs/howto.html exists":                os.path.isfile(os.path.join(DOCS, "howto.html")),
        "docs/sitemap.xml exists":               os.path.isfile(os.path.join(DOCS, "sitemap.xml")),
    }
    # Check index.html has no forbidden strings
    if os.path.isfile(os.path.join(DOCS, "index.html")):
        idx = open(os.path.join(DOCS, "index.html"), encoding="utf-8").read()
        for bad in ("generated_articles.json", "rewrite_feed", "Gemini", "Groq",
                    "AI quality gate", "This page has been removed"):
            checks[f"index.html: no '{bad}'"] = bad not in idx

    all_ok = True
    for label, ok in checks.items():
        print(f"  {'✓' if ok else '✗'}  {label}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print(f"✅ Build complete — {len(articles)} articles published.")
    else:
        print("⚠  Build complete with warnings — check ✗ items above.")
    print()


if __name__ == "__main__":
    main()
