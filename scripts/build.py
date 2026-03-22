"""
scripts/build.py — The Streamic site builder
Apple Newsroom-style static site generator
"""
import json, os, re, shutil
from datetime import datetime, timezone

ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARTS_F    = os.path.join(ROOT, "data", "generated_articles.json")
DOCS      = os.path.join(ROOT, "docs")
ARTS_D    = os.path.join(DOCS, "articles")
BASE_URL  = os.environ.get("SITE_BASE_URL", "https://www.thestreamic.in").rstrip("/")
GA        = "G-0VSHDN3ZR6"
ADS       = "ca-pub-8033069131874524"
AUTHOR    = "The Streamic Editorial Team"

# ── Editor's Note (AdSense transparency) ─────────────────────────────────────
_EDITORS_NOTE_HTML = (
    '<hr style="margin-top:40px;border:0;border-top:1px solid #eee;">'
    '<p style="font-style:italic;font-size:0.85rem;color:#666;line-height:1.5;margin-top:20px;">'
    '<strong>Editor&#39;s Note:</strong> This technical analysis was synthesised from '
    'industry sources and constructed with the assistance of AI tools. It has been '
    'reviewed and formatted by <strong>The Streamic Editorial Team</strong> '
    'to ensure accuracy and relevance for broadcast professionals.'
    '</p>'
)

PAGE_SIZE = 24

CAT = {
    "featured":           {"label":"Featured",           "icon":"⭐","color":"#1d1d1f","desc":"Independent broadcast and streaming technology journalism."},
    "streaming":          {"label":"Streaming",          "icon":"📡","color":"#0066cc","desc":"OTT platforms, encoding, CDN infrastructure, live streaming workflows."},
    "cloud":              {"label":"Cloud Production",   "icon":"☁️","color":"#5856d6","desc":"Cloud-native broadcast production, remote workflows, REMI architecture."},
    "graphics":           {"label":"Graphics",           "icon":"🎨","color":"#FF9500","desc":"Real-time graphics, virtual sets, motion design, broadcast visuals."},
    "playout":            {"label":"Playout",            "icon":"▶️","color":"#34C759","desc":"Channel playout, broadcast automation, channel-in-a-box, transmission."},
    "infrastructure":     {"label":"Infrastructure",     "icon":"🏗️","color":"#636366","desc":"SMPTE ST 2110, IP routing, network infrastructure, broadcast facility tech."},
    "ai-post-production": {"label":"AI & Post-Production","icon":"🎬","color":"#FF2D55","desc":"AI-driven editing tools, automated QC, intelligent MAM, colour grading."},
    "newsroom":           {"label":"Newsroom",           "icon":"📰","color":"#b8860b","desc":"NRCS systems, remote journalism, newsroom workflow automation."},
}
CAT_PAGE = {c: f"{c}.html" for c in CAT}

# ── helpers
def e(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
def d(iso):
    try: return datetime.strptime(iso[:10],"%Y-%m-%d").strftime("%B %d, %Y")
    except: return iso
def w(path, txt):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"w",encoding="utf-8") as f: f.write(txt)
def rm(wc): return f"{max(1,round(wc/200))} min read"

# ── shared HTML blocks
def _consent():
    return f"""<script>
    window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}
    gtag('consent','default',{{'analytics_storage':'denied','ad_storage':'denied',
    'ad_user_data':'denied','ad_personalization':'denied','wait_for_update':500}});
  </script>
  <script async src="https://www.googletagmanager.com/gtag/js?id={GA}"></script>
  <script>gtag('js',new Date());gtag('config','{GA}');</script>
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADS}" crossorigin="anonymous"></script>"""

def _cookie_banner():
    return """<div id="ts-cookie">
  <div class="cookie-in">
    <div class="cookie-txt">
      <strong>We use cookies</strong>
      Analytics and advertising cookies improve your experience.
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
      analytics_storage:ok?'granted':'denied',ad_storage:ok?'granted':'denied',
      ad_user_data:ok?'granted':'denied',ad_personalization:ok?'granted':'denied'});
  };
  if(s==='granted'&&typeof gtag!='undefined')gtag('consent','update',{
    analytics_storage:'granted',ad_storage:'granted',
    ad_user_data:'granted',ad_personalization:'granted'});
})();
</script>"""

def _ad():
    # Ad slots removed — using Google Auto-Ads after AdSense approval
    # The AdSense script in <head> remains for approval verification
    return ""

def _fonts():
    return '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">'

def head(title, desc, canon, css="style.css", og_img=""):
    og = f'  <meta property="og:image" content="{e(og_img)}">\n' if og_img else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  {_consent()}
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{e(title)}</title>
  <meta name="description" content="{e(desc)}">
  <meta name="robots" content="index,follow">
  <meta name="author" content="{AUTHOR}">
  <link rel="canonical" href="{e(canon)}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="The Streamic">
  <meta property="og:title" content="{e(title)}">
  <meta property="og:description" content="{e(desc)}">
  <meta property="og:url" content="{e(canon)}">
{og}  <meta name="twitter:card" content="summary_large_image">
  {_fonts()}
  <link rel="stylesheet" href="{css}">
</head>"""

def nav(active="", base=""):
    cats = [
        ("featured.html","Featured"),("infrastructure.html","Infrastructure"),("posts.html","All Articles"),
        ("graphics.html","Graphics"),("cloud.html","Cloud Production"),
        ("streaming.html","Streaming"),("ai-post-production.html","AI & Post"),
        ("playout.html","Playout"),("newsroom.html","Newsroom"),("howto.html","How-To"),
    ]
    def _nav_li(h, lbl, base=base, active=active):
        cls = ' class="active"' if h == active else ''
        return f'<li><a href="{base}{h}"{cls}>{lbl}</a></li>'
    lis = "".join(_nav_li(h, lbl) for h, lbl in cats)
    mob_links = "".join(
        f'<a href="{base}{h}">{lbl}</a>' for h,lbl in cats)
    return f"""<nav class="nav">
  <div class="nav-inner">
    <a href="{base}featured.html" class="nav-logo">
      <img src="{base}assets/logo.png" alt="The Streamic">
      <span>The Streamic</span>
    </a>
    <ul class="nav-links">{lis}</ul>
    <div class="nav-right">
      <a href="{base}vlog.html" class="nav-desk">Editor's Desk</a>
      <button class="nav-toggle" aria-label="Menu" onclick="document.querySelector('.nav-mob').classList.toggle('open')">
        <span></span><span></span><span></span>
      </button>
    </div>
  </div>
  <div class="nav-mob">{mob_links}</div>
</nav>"""

def catbar(active_cat="", base=""):
    items = [
        ("streaming","📡 Streaming"),("cloud","☁️ Cloud"),
        ("graphics","🎨 Graphics"),("playout","▶️ Playout"),
        ("infrastructure","🏗️ Infra"),("ai-post-production","🎬 AI & Post"),
        ("newsroom","📰 Newsroom"),
    ]
    pills = "".join(
        f'<a href="{base}{c}.html" class="cpill{"active" if c==active_cat else ""}">{lbl}</a>'
        for c,lbl in items)
    return f'<div class="catbar"><div class="catbar-inner">{pills}</div></div>'

def footer(base=""):
    yr = datetime.now().year
    return f"""<footer class="footer">
  <div class="footer-grid">
    <div>
      <div class="footer-brand">The Streamic</div>
      <p class="footer-tag">Independent broadcast &amp; streaming technology journalism for engineers and media professionals. Original analysis, industry coverage, and technical commentary.</p>
    </div>
    <div class="footer-col">
      <h4>Coverage</h4>
      <a href="{base}streaming.html">Streaming</a>
      <a href="{base}cloud.html">Cloud Production</a>
      <a href="{base}ai-post-production.html">AI &amp; Post</a>
      <a href="{base}graphics.html">Graphics</a>
      <a href="{base}playout.html">Playout</a>
      <a href="{base}infrastructure.html">Infrastructure</a>
      <a href="{base}newsroom.html">Newsroom</a>
    </div>
    <div class="footer-col">
      <h4>Site</h4>
      <a href="{base}about.html">About</a>
      <a href="{base}contact.html">Contact</a>
      <a href="{base}vlog.html">Editor's Desk</a>
      <a href="{base}howto.html">How-To Guides</a>
      <a href="{base}privacy.html">Privacy Policy</a>
      <a href="{base}terms.html">Terms of Use</a>
    </div>
    <div class="footer-col">
      <h4>Follow</h4>
      <a href="https://twitter.com/thestreamic" target="_blank" rel="noopener noreferrer">&#x1D54F; @thestreamic</a>
      <a href="https://www.linkedin.com/company/thestreamic" target="_blank" rel="noopener noreferrer">in TheStreamic</a>
    </div>
  </div>
  <div class="footer-bottom">
    <span>© {yr} The Streamic — thestreamic.in. All rights reserved.</span>
    <span>Independent broadcast technology journalism. All trademarks belong to their respective owners.</span>
  </div>
</footer>"""

# ── NEWS GRID (SSR from generated_articles.json)
def _nc_img(a, base=""):
    img = e(a.get("image_url",""))
    fb  = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    if img:
        slug_ = a.get('slug', '')
        return f'<div class="nc-img"><a href="{base}articles/{slug_}.html" tabindex="-1" aria-hidden="true"><img src="{img}" alt="{title}" loading="lazy" onerror="this.src=&apos;{fb}&apos;"></a></div>'
    return f'<div class="nc-img nc-img-ph"></div>'

def news_card(a, base="", is_first=False):
    """SSR bento-grid-item — mirrors JS buildFeatured/buildStandard structure exactly."""
    cat   = a.get("category","featured")
    cinfo = CAT.get(cat, CAT["featured"])
    slug_ = a.get('slug', '')
    href  = f"{base}articles/{slug_}.html"
    img   = e(a.get("image_url",""))
    fb_   = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    src   = e(a.get("source_domain","").replace("https://","").replace("www.","").split("/")[0].upper())
    cat_lbl = cinfo["label"]

    if is_first:
        # Featured: vertical, large image — no summary (editorial feel)
        src_html_f = f'<span class="bento-source">{src}</span>' if src else ""
        return f"""<li class="bento-grid-item">
  <div class="bento-img-wrap bento-img-featured">
    <a href="{href}" tabindex="-1" aria-hidden="true">
      <img src="{img}" alt="{title}" loading="eager" onerror="this.onerror=null;this.src={fb_}">
    </a>
  </div>
  <div class="bento-body bento-body-featured">
    <span class="bento-cat-tag">{cat_lbl}</span>
    <h2 class="bento-hl bento-hl-featured"><a href="{href}">{title}</a></h2>
    <div class="bento-foot">
      {src_html_f}
      <time style="font-size:11px;color:var(--ink4)">{d(a.get("published",""))}</time>
      <a href="{href}" class="bento-cta-featured">Read Full Article &rarr;</a>
    </div>
  </div>
</li>"""
    else:
        # Standard: vertical cards — no summary (clean editorial look)
        src_html_s = f'<span class="bento-source">{src}</span>' if src else ""
        return f"""<li class="bento-grid-item bento-standard">
  <div class="bento-img-wrap bento-img-std">
    <a href="{href}" tabindex="-1" aria-hidden="true">
      <img src="{img}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src={fb_}">
    </a>
  </div>
  <div class="bento-body bento-body-std">
    <span class="bento-cat-tag">{cat_lbl}</span>
    <h3 class="bento-hl bento-hl-std"><a href="{href}">{title}</a></h3>
    <div class="bento-foot">
      {src_html_s}
      <time style="font-size:11px;color:var(--ink4)">{d(a.get("published",""))}</time>
      <a href="{href}" class="bento-cta">Read Full Article &rarr;</a>
    </div>
  </div>
</li>"""

def news_grid(arts, base=""):
    """SSR bento grid — JS hydrates from news.json, this provides SEO content."""
    if not arts: return ""
    cards = "\n".join(
        news_card(a, base, is_first=(i==0))
        for i, a in enumerate(arts)
    )
    return f'<ul id="bentoGridLarge" class="bento-grid-large">\n{cards}\n</ul>'

# ── EDITORIAL CARD (deep-dive articles)
def ed_card(a, base=""):
    cat   = a.get("category","featured")
    cinfo = CAT.get(cat, CAT["featured"])
    slug_ = a.get('slug', '')
    href  = f"{base}articles/{slug_}.html"
    img   = e(a.get("image_url",""))
    fb    = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    dek   = e((a.get("dek") or a.get("meta_description",""))[:200])
    wc    = a.get("word_count",1000)
    dt    = d(a.get("published",""))
    return f"""<article class="ed-card">
  <div class="ed-img">
    <a href="{href}">
      <img src="{img}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src={fb}">
    </a>
  </div>
  <div class="ed-body">
    <span class="ed-tag" style="background:{cinfo['color']}">{cinfo['icon']} {cinfo['label']}</span>
    <h3 class="ed-hl"><a href="{href}">{title}</a></h3>
    <p class="ed-dek">{dek}</p>
    <div class="ed-foot">
      <span class="ed-meta">{dt} &middot; {rm(wc)}</span>
      <a href="{href}" class="ed-read">Read full analysis &rarr;</a>
    </div>
  </div>
</article>"""

# ── HERO
def hero_block(a, base=""):
    cat   = a.get("category","featured")
    cinfo = CAT.get(cat, CAT["featured"])
    slug_ = a.get('slug', '')
    href  = f"{base}articles/{slug_}.html"
    img   = e(a.get("image_url",""))
    fb    = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    dek   = e((a.get("card_summary") or a.get("dek") or "")[:200])
    wc    = a.get("word_count",800)
    dt    = d(a.get("published",""))
    return f"""<section class="hero">
  <div class="hero-inner">
    <div class="hero-img">
      <a href="{href}">
        <img src="{img}" alt="{title}" loading="eager" onerror="this.onerror=null;this.src={fb}">
      </a>
    </div>
    <div class="hero-body">
      <span class="hero-tag" style="background:{cinfo['color']}">{cinfo['icon']} {cinfo['label']}</span>
      <h2 class="hero-hl"><a href="{href}">{title}</a></h2>
      <p class="hero-dek">{dek}</p>
      <div class="hero-meta">
        <span>By {AUTHOR}</span>
        <span>{dt}</span>
        <span>{rm(wc)}</span>
      </div>
      <a href="{href}" class="hero-cta">Read full story</a>
    </div>
  </div>
</section>"""

# ── FEATURED / INDEX PAGE
def intelligence_feed_section(arts, base=""):
    """3-column Apple Newsroom-style grid — title + source only (no AI summaries).
    Cards are clean: image, category tag, headline, source/date. No card_summary shown.
    Gemini/Groq will fill structured body_html on article pages in future runs.
    """
    rss = [a for a in arts if not a.get("is_editorial") and not a.get("editorial")][:15]
    if not rss:
        return ""

    cards_html = ""
    for a in rss:
        cat     = a.get("category", "featured")
        cinfo   = CAT.get(cat, CAT["featured"])
        slug_   = a.get("slug", "")
        href    = f"{base}articles/{slug_}.html"
        img     = e(a.get("image_url", ""))
        fb      = f"{base}assets/fallback.jpg"
        title   = e(a.get("title", ""))
        src_dom = e(a.get("source_domain","").replace("https://","").replace("www.","").split("/")[0].upper())
        dt      = d(a.get("published",""))
        src_url = e(a.get("source_url","") or a.get("url","") or "")
        cat_lbl = cinfo["label"]
        cat_col = cinfo["color"]
        # Determine if article has proper long-form body (700+ words with h2 structure)
        body    = a.get("body_html","") or ""
        wc      = len(re.sub(r"<[^>]+>"," ",body).split())
        has_long = wc >= 500 and ("<h2>" in body or "<h3>" in body)
        cta_txt = "Read Analysis &rarr;" if has_long else "View Source &rarr;"
        cta_href = href if has_long else (src_url or href)
        cta_target = ' target="_blank" rel="noopener noreferrer nofollow"' if (not has_long and src_url) else ''

        cards_html += f"""
<article style="background:#fff;border-radius:12px;border:1px solid #eee;overflow:hidden;display:flex;flex-direction:column;transition:box-shadow 0.2s ease,transform 0.2s ease">
  <a href="{href}" style="display:block;aspect-ratio:16/9;overflow:hidden;text-decoration:none">
    <img src="{img}" alt="{title}" loading="lazy"
      onerror="this.onerror=null;this.src='{fb}'"
      style="width:100%;height:100%;object-fit:cover;transition:transform 0.3s ease;display:block">
  </a>
  <div style="padding:16px 18px 18px;display:flex;flex-direction:column;flex:1">
    <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:{cat_col};margin-bottom:8px">{cat_lbl}</span>
    <h3 style="font-family:var(--serif);font-size:17px;line-height:1.35;letter-spacing:-.02em;color:var(--ink);margin:0 0 auto">
      <a href="{href}" style="color:inherit;text-decoration:none">{title}</a>
    </h3>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:14px;padding-top:12px;border-top:1px solid #f0f0f0">
      <span style="font-size:11px;color:var(--ink4)">{src_dom} &middot; <time>{dt}</time></span>
      <a href="{cta_href}"{cta_target} style="font-size:12px;font-weight:600;color:var(--blue);text-decoration:none;white-space:nowrap">{cta_txt}</a>
    </div>
  </div>
</article>"""

    disclosure = """<div style="grid-column:1/-1;margin-top:8px;padding:14px 18px;background:#f9f9f9;border-radius:8px;border:1px solid #eee">
  <p style="font-style:italic;font-size:12px;color:#888;line-height:1.5;margin:0">
    <strong style="font-style:normal;color:#666">Editor's Note:</strong> This technical analysis was synthesized from industry RSS feeds and constructed with the assistance of AI tools. It has been reviewed and formatted by <strong style="font-style:normal">The Streamic Editorial Team</strong> to ensure accuracy and relevance for broadcast professionals.
  </p>
</div>"""

    return f"""<section style="margin:48px 0 0">
  <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:8px;padding-bottom:12px;border-bottom:2px solid var(--ink)">
    <h2 style="font-family:var(--serif);font-size:clamp(20px,2.5vw,26px);letter-spacing:-.03em;margin:0">&#128202; Latest Technical Briefings &amp; Industry Analysis</h2>
    <a href="posts.html" style="font-size:13px;font-weight:600;color:var(--blue);text-decoration:none;white-space:nowrap;flex-shrink:0;margin-left:16px">View all articles &rarr;</a>
  </div>
  <p style="font-size:14px;color:var(--ink3);margin:0 0 24px;line-height:1.6">Deep-dive reporting on the intersection of cloud production, AI-driven media workflows, and global streaming infrastructure.</p>
  <style>
    .intel-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}}
    @media(max-width:768px){{.intel-grid{{grid-template-columns:1fr}}}}
    @media(max-width:1024px) and (min-width:769px){{.intel-grid{{grid-template-columns:repeat(2,1fr)}}}}
    .intel-grid article:hover{{box-shadow:0 6px 24px rgba(0,0,0,.08);transform:translateY(-2px)}}
    .intel-grid article:hover img{{transform:scale(1.03)}}
  </style>
  <div class="intel-grid">
    {cards_html}
    {disclosure}
  </div>
</section>"""


def all_articles_page(arts):
    """Generate posts.html — All Articles bento grid linking to articles/."""
    # Use all non-editorial articles sorted newest first
    rss_arts   = [a for a in arts if not a.get("is_editorial") and not a.get("editorial")]
    ed_arts    = [a for a in arts if a.get("is_editorial") or a.get("editorial")]
    all_sorted = rss_arts  # newest first (already sorted in generated_articles.json)

    title  = "All Articles — The Streamic | Broadcast Technology Analysis"
    desc   = "Original broadcast and streaming technology analysis. Expert-level commentary for engineers and media professionals."
    canon  = f"{BASE_URL}/posts.html"

    schema = json.dumps({
        "@context": "https://schema.org", "@type": "WebPage",
        "name": "All Articles — The Streamic", "description": desc,
        "url": f"{BASE_URL}/posts.html",
        "publisher": {"@type": "Organization", "name": "The Streamic", "url": BASE_URL}
    })

    cards = ""
    for i, a in enumerate(all_sorted[:60]):  # show up to 60 articles
        cards += news_card(a, base="", is_first=(i == 0))

    return f"""{head(title, desc, canon)}
<body data-category="featured">
{nav("posts.html")}
{catbar()}
<main>
  <div class="w">
    <div class="cat-hdr">
      <h1>All Articles</h1>
      <p>Original broadcast and streaming technology analysis. Every article is expert-level commentary for engineers and media professionals.</p>
    </div>
    {_ad()}
    <section class="latest" style="margin-top:32px">
      <ul id="bentoGridLarge" class="bento-grid-large">
        {cards}
      </ul>
    </section>
    {_ad()}
  </div>
</main>
<script type="application/ld+json">{schema}</script>
{footer()}
{_cookie_banner()}
<script src="main.js" defer></script>
</body>
</html>"""


def featured_page(arts):
    editorial = [a for a in arts if a.get("is_editorial") or a.get("editorial")][:5]
    hero_art  = editorial[0] if editorial else (arts[0] if arts else None)
    # Change 4c: limit to 12 RSS articles on homepage
    rss_arts  = [a for a in arts if not a.get("is_editorial") and not a.get("editorial")
                 and (not hero_art or a["slug"] != hero_art["slug"])][:12]

    title  = "The Streamic — Independent Broadcast & Streaming Technology News"
    desc   = "Original analysis, deep dives, and curated broadcast technology news for engineers and media professionals."
    canon  = f"{BASE_URL}/featured.html"

    ed_html = "\n".join(ed_card(a) for a in editorial)

    schema = json.dumps({
        "@context":"https://schema.org","@type":"WebPage",
        "name":"The Streamic","description":desc,"url":f"{BASE_URL}/",
        "publisher":{"@type":"Organization","name":"The Streamic","url":BASE_URL}
    })

    # Change 4a: editorial intro text
    intro_html = """<div style="max-width:680px;margin:28px auto 0;padding:0 24px 32px;text-align:center">
  <p style="font-size:15px;line-height:1.7;color:var(--ink2)">
    The Streamic covers broadcast and streaming technology for engineers, architects, and media technology leaders.
    Our editorial team publishes original analysis, technical deep-dives, and curated industry updates — independent of vendor influence.
  </p>
</div>"""

    intel_feed = intelligence_feed_section(feat_arts if "feat_arts" in dir() else arts)

    return f"""{head(title, desc, canon, og_img=(hero_art or {}).get('image_url',''))}
<body data-category="featured">
{nav("featured.html")}
{catbar()}
{hero_block(hero_art) if hero_art else ""}
{intro_html}
<main>
  <div class="w">
{"" if not editorial else f'''<section class="editorial">
      <div class="sec-hdr">
        <h2>📝 Editor's Picks</h2>
        <span style="font-size:13px;color:var(--ink4);font-weight:400">Original analysis by The Streamic editorial team</span>
      </div>
      <div class="ed-list">{ed_html}</div>
    </section>'''}
    {intel_feed}
    {_ad()}
    <section class="latest">
      <div class="sec-hdr">
        <h2>📡 Latest Industry Updates</h2>
        <span style="font-size:12px;color:var(--ink4)">Updated every 6 hours</span>
      </div>
      {news_grid(rss_arts)}
    </section>
    {_ad()}
  </div>
</main>
<script type="application/ld+json">{schema}</script>
{footer()}
{_cookie_banner()}
<script src="main.js" defer></script>
</body>
</html>"""

# ── CATEGORY PAGE
def category_page(cat, arts):
    cinfo = CAT.get(cat, CAT["featured"])
    cpg   = f"{cat}.html"
    canon = f"{BASE_URL}/{cpg}"
    cat_label_ = cinfo.get('label', '')
    title_base = f"{cat_label_} — The Streamic"
    desc  = cinfo["desc"]

    # First article: editorial hero card
    # Top 3 articles: editorial-style horizontal cards
    # Rest: news grid
    editorial = [a for a in arts if a.get("is_editorial") or a.get("editorial")]
    regular   = [a for a in arts if not a.get("is_editorial") and not a.get("editorial")]
    all_arts  = editorial + regular
    all_arts.sort(key=lambda a: a.get("published",""), reverse=True)

    total = len(all_arts)
    total_pages = max(1,(total + PAGE_SIZE -1)//PAGE_SIZE)
    pages = []

    for pg in range(total_pages):
        sl = all_arts[pg*PAGE_SIZE:(pg+1)*PAGE_SIZE]
        first  = sl[:1]
        rest   = sl[1:]

        hero_html = hero_block(first[0], base="") if first else ""
        grid_html = news_grid(rest) if rest else ""

        pag = _pag_html(cat, pg, total_pages)

        pg_title = title_base if pg==0 else f"{title_base} — Page {pg+1}"
        cinfo_icon = cinfo.get('icon','')
        cinfo_label = cinfo.get('label','')
        pg_canon = canon if pg==0 else f"{BASE_URL}/{cat}-p{pg+1}.html"

        latest_section = f'<section class="latest">{grid_html}</section>' if grid_html else ""
        html = f"""{head(pg_title, desc, pg_canon, og_img=(first[0].get('image_url','') if first else ''))}
<body data-category="{cat}">
{nav(cpg)}
{catbar(cat)}
<main>
  <div class="w">
    <div class="cat-hdr">
      <h1>{cinfo_icon} {cinfo_label}</h1>
      <p>{desc}</p>
    </div>
    {hero_html}
    {_ad() if rest else ""}
    {latest_section}
    {_ad()}
    {pag}
  </div>
</main>
{footer()}
{_cookie_banner()}
<script src="main.js" defer></script>
</body>
</html>"""
        pages.append((pg, html))
    return pages

def _pag_html(cat, page, total):
    if total <= 1: return ""
    prev = f'<a href="{cat}.html" class="pag-link">&larr; Newer</a>' if page > 0 else '<span class="dis">&larr; Newer</span>'
    nxt  = f'<a href="{cat}-p{page+2}.html" class="pag-link">Older &rarr;</a>' if page < total-1 else '<span class="dis">Older &rarr;</span>'
    return f'<div class="pag">{prev}<span class="info">Page {page+1} of {total}</span>{nxt}</div>'

# ── ARTICLE PAGE
# Boilerplate sentences to strip from article bodies
# All known boilerplate sentence fragments (substring match)
_BOILER_FRAGMENTS = [
    "Understanding what is changing helps teams plan ahead",
    "Early movers tend to gain an efficiency edge",
    "Teams should discuss this in their next planning cycle",
    "Organisations tracking this should review their current approach",
    "Practical impact will vary by scale, but the direction is clear",
    "Keeping a close eye on vendor roadmaps",
    "The operational details matter as much as the headline",
    "Budgets, staffing, and tooling may all need revisiting",
    "The pace of change in broadcast IP, cloud, and streaming infrastructure has accelerated",
    "New deployments and announced capabilities are revealing practical pathways",
    "Teams with legacy infrastructure commitments will need to assess",
    "What distinguishes this from earlier announcements in the same space",
    "The market context matters here: this development arrives",
    "For engineering and operations teams:",
    "Teams that engage early and plan methodically will be best placed",
    "Engineering teams evaluating this should look beyond headline capability",
    "The broadcast and streaming technology sector continues to evolve rapidly",
    "Media technology decisions made this year will shape production",
    "Industry analysts and practitioners alike are tracking",
    "The integration of software-defined approaches into traditionally hardware-centric",
    "Competitive dynamics between established broadcast technology vendors",
    "Regional differences in broadcast infrastructure maturity",
    "Standards bodies, vendors, and broadcaster engineering teams are increasingly aligned",
    "The economics of media production and distribution continue to shift",
    "An independent editorial overview of the technology forces reshaping",
    "Understanding what is changing helps teams plan ahead",
    "Organisations tracking this should review their current approach",
    "The announcement reflects sustained demand from broadcast operators",
    "For broadcast engineers and technology decision-makers, staying current",
]

def _is_boilerplate(text):
    """Return True if this paragraph is mostly generic filler."""
    return any(b.lower() in text.lower() for b in _BOILER_FRAGMENTS)

def _clean_body(a):
    """
    Return clean article body: strip ALL boilerplate filler sentences.
    Use card_summary if available, else dek + real content paragraphs only.
    """
    is_ed = a.get("is_editorial") or a.get("editorial")
    if is_ed:
        body = a.get("body_html","")
        if body and len(body) > 300:
            return body

    cs_raw = re.sub(r"<[^>]+>", " ", a.get("card_summary","") or "").strip()
    cs_raw = re.sub(r"\s+", " ", cs_raw)
    cs_words = cs_raw.split()

    if len(cs_words) >= 120 and not _is_boilerplate(cs_raw):
        mid = len(cs_words) // 2
        for i in range(mid, min(mid+25, len(cs_words))):
            if cs_words[i].endswith((".", "?")): mid = i+1; break
        p1 = " ".join(cs_words[:mid])
        p2 = " ".join(cs_words[mid:])
        return f"<p>{p1}</p>\n" + (f"<p>{p2}</p>" if p2 else "")

    body_html = a.get("body_html","") or ""
    paras = re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.DOTALL)
    clean = []
    for p in paras:
        txt = re.sub(r"<[^>]+>", " ", p).strip()
        txt = re.sub(r"\s+", " ", txt)
        if len(txt.split()) < 8: continue
        if _is_boilerplate(txt): continue
        clean.append(f"<p>{p.strip()}</p>")

    if clean:
        return "\n".join(clean[:4])

    dek = (a.get("dek") or "").strip()
    teaser = (a.get("meta_description") or a.get("teaser") or "").strip()
    parts = []
    if dek: parts.append(f"<p><strong>{dek}</strong></p>")
    if len(cs_words) >= 20 and cs_raw != dek: parts.append(f"<p>{cs_raw}</p>")
    elif teaser and teaser != dek: parts.append(f"<p>{teaser}</p>")
    return "\n".join(parts) if parts else f"<p>{dek or 'Broadcast technology analysis.'}</p>"


def article_page(a):
    # ── Thin content check: redirect to source for stub articles ──────────────
    body_raw = a.get("body_html","") or ""
    body_wc  = len(re.sub(r"<[^>]+>", " ", body_raw).split())
    has_struct = "<h2>" in body_raw or "<h3>" in body_raw
    src_url_direct = a.get("source_url") or a.get("url") or a.get("link","")
    
    if body_wc < 200 and not has_struct and src_url_direct:
        # Render a clean source-redirect article page (no thin content)
        cat2   = a.get("category","featured")
        ci2    = CAT.get(cat2, CAT["featured"])
        title2 = e(a.get("title","Untitled"))
        dt2    = d(a.get("published",""))
        return f"""{head(title2+" | The Streamic", a.get("meta_description",title2), f"{BASE_URL}/articles/{a['slug']}.html", css="../style.css")}
<body>
{nav(ci2.get("page","featured.html"), base="../")}
<main><div class="art-wrap" style="max-width:680px;padding:60px 24px 80px">
  <a href="../{ci2.get('page','featured.html')}" style="font-size:13px;color:var(--blue);text-decoration:none">← {ci2.get('label','Featured')}</a>
  <h1 style="font-family:var(--serif);font-size:clamp(22px,3.5vw,36px);line-height:1.25;letter-spacing:-.03em;margin:20px 0 12px">{title2}</h1>
  <p style="font-size:13px;color:var(--ink4);margin-bottom:32px">By The Streamic Editorial Team · {dt2}</p>
  <div style="background:var(--bg);border-radius:14px;padding:28px 32px;border-left:4px solid var(--blue)">
    <p style="font-size:15px;color:var(--ink2);line-height:1.7;margin:0 0 20px">This is an industry news item tracked by The Streamic. Our editorial team has flagged it for upcoming analysis. For the complete story, read the original article from {e(a.get('source_domain','the source').replace('https://','').replace('www.','').split('/')[0])}.</p>
    <a href="{e(src_url_direct)}" target="_blank" rel="noopener noreferrer nofollow"
      style="display:inline-flex;align-items:center;gap:8px;padding:12px 24px;background:var(--blue);color:#fff;border-radius:8px;font-size:14px;font-weight:600;text-decoration:none">
      Read Original Article →
    </a>
  </div>
  <p style="font-size:12px;color:var(--ink4);margin-top:24px">The Streamic publishes original broadcast technology analysis on our <a href="../featured.html" style="color:var(--blue)">Featured</a> and <a href="../posts.html" style="color:var(--blue)">All Articles</a> pages.</p>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

    cat   = a.get("category","featured")
    cinfo = CAT.get(cat, CAT["featured"])
    slug  = a["slug"]
    url   = f"{BASE_URL}/articles/{slug}.html"
    title = a.get("title","")
    dek   = a.get("dek") or a.get("meta_description","")
    img   = a.get("image_url","")
    dt    = d(a.get("published",""))
    src_url  = a.get("source_url","")
    src_dom  = a.get("source_domain","")
    is_ed    = a.get("is_editorial") or a.get("editorial")

    # Clean body — card_summary as 2-para analysis (not boilerplate filler)
    body  = _clean_body(a)
    body_words = len(body.replace("<p>","").replace("</p>","").split())
    wc    = body_words or a.get("word_count",300)

    schema = json.dumps({
        "@context":"https://schema.org","@type":"NewsArticle",
        "headline":title,"description":dek,"image":img,
        "datePublished":a.get("published",""),"dateModified":a.get("published",""),
        "author":{"@type":"Organization","name":AUTHOR},
        "publisher":{"@type":"Organization","name":"The Streamic","url":BASE_URL,
                     "logo":{"@type":"ImageObject","url":f"{BASE_URL}/assets/logo.png"}},
        "mainEntityOfPage":url,"wordCount":wc,
    }, indent=2)

    source_credit = ""
    if src_url and src_dom and not is_ed:
        source_credit = f"""<div class="art-source-credit">
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
    <div>
      <span style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:1px;color:var(--blue);display:block;margin-bottom:4px">Original Source</span>
      <strong style="font-size:14px;color:var(--ink)">{e(src_dom)}</strong>
    </div>
    <a href="{e(src_url)}" target="_blank" rel="noopener noreferrer nofollow"
       style="display:inline-flex;align-items:center;gap:6px;padding:10px 20px;
              background:var(--blue);color:#fff;border-radius:8px;font-size:13px;
              font-weight:600;text-decoration:none;">
      View Original Article &rarr;
    </a>
  </div>
  <p style="margin:10px 0 0;font-size:12px;color:var(--ink4)">
    The analysis above is original editorial commentary by The Streamic. The news is reported by {e(src_dom)}.
  </p>
</div>"""

    about_txt = "Original analysis and commentary by The Streamic Editorial Team. Independent broadcast technology journalism for engineers and media professionals." if is_ed else "Editorial commentary and analysis by The Streamic Editorial Team. For the original source, see the attribution above."
    author_box = f"""<div class="art-author">
  <strong>About this article</strong>
  {about_txt}
  <a href="/about.html" style="color:var(--blue);margin-left:6px;">About The Streamic &rarr;</a>
</div>"""

    # Pre-compute variables for f-string compatibility (Python < 3.12)
    editors_note = '' if is_ed else _EDITORS_NOTE_HTML
    cinfo_color = cinfo.get('color','')
    cinfo_lbl   = cinfo.get('label','')
    cinfo_icon2 = cinfo.get('icon','')
    cinfo_page  = CAT_PAGE.get(cat, cat+'.html')
    lic_url   = e(a.get('image_license_url','https://unsplash.com/license'))
    lic_label = e(a.get('image_license','Unsplash License'))
    if not is_ed and src_url:
        title_html = f'<h1><a href="{e(src_url)}" target="_blank" rel="noopener noreferrer nofollow" style="color:inherit;text-decoration:none;">{e(title)}</a></h1>'
    else:
        title_html = f'<h1>{e(title)}</h1>'
    analysis_badge = '<span style="background:var(--blue);color:#fff;padding:3px 9px;border-radius:5px;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.8px">Analysis</span>' if is_ed else ""

    return f"""{head(e(title)+" | The Streamic", dek, url, css="../style.css", og_img=img)}
<body>
{nav(CAT_PAGE.get(cat,cat+".html"), base="../")}
<main>
  <div class="art-wrap">
    <div class="art-breadcrumb">
      <a href="../featured.html">Home</a>
      <span>›</span>
      <a href="../{cinfo_page}" style="color:{cinfo_color}">{cinfo_lbl}</a>
    </div>
    <span class="art-tag" style="background:{cinfo_color}">{cinfo_icon2} {cinfo_lbl}</span>
    {title_html}
    <p class="art-dek">{e(dek)}</p>
    <div class="art-byline">
      <strong>{AUTHOR}</strong>
      <time datetime="{a.get("published","")}" style="color:var(--ink4);font-size:13px">{dt}</time>
      <span>{wc:,} words · {rm(wc)}</span>
      {analysis_badge}
    </div>
    <figure>
      <img src="{e(img)}" alt="{e(title)}" loading="eager">
      <figcaption>{e(a.get("image_credit","Photo via Unsplash — free to use under the Unsplash License"))} — <a href="{lic_url}" rel="nofollow noopener" target="_blank" style="color:var(--ink4)">{lic_label}</a></figcaption>
    </figure>
    {_ad()}
    <div class="art-body">{body}{editors_note}</div>
    {source_credit}
    {_ad()}
    {author_box}
    <div class="art-more">
      <h3>Continue Reading</h3>
      <a href="../{CAT_PAGE.get(cat,cat+'.html')}">{cinfo['icon']} All {cinfo['label']} Coverage</a>
      <a href="../featured.html">⭐ Featured Stories</a>
    </div>
  </div>
</main>
<script type="application/ld+json">{schema}</script>
{footer(base="../")}
{_cookie_banner()}
</body>
</html>"""

# ── STATIC PAGES
def about_page():
    return f"""{head("About The Streamic — Prerak K Mehta","Independent broadcast and streaming technology journalism from Dublin, Ireland.",f"{BASE_URL}/about.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 0 80px;max-width:780px">
<h1 style="font-family:var(--serif);font-size:clamp(28px,4vw,44px);margin-bottom:16px;letter-spacing:-.5px">About The Streamic</h1>
<p style="font-size:17px;color:var(--ink2);line-height:1.65;margin-bottom:20px">The Streamic is an independent broadcast and streaming technology publication covering the tools, standards, and workflows that shape modern media production and delivery.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:20px">We publish original editorial analysis on topics including IP infrastructure (SMPTE ST 2110, NMOS), cloud-native production, operational AI, real-time graphics, playout automation, and newsroom technology. Our readership includes broadcast engineers, operations managers, technology directors, and media industry professionals.</p>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">Our editorial approach</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:16px">We write original analysis — not copied content. Our RSS-curated news feed clearly credits and links to original sources. Long-form articles represent our editorial team&#39;s independent perspective on industry developments.</p>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">Editor &amp; Founder</h2>
<div style="display:flex;align-items:flex-start;gap:20px;background:var(--bg);border-radius:14px;padding:24px;margin-bottom:28px">
  <div style="flex-shrink:0;width:56px;height:56px;border-radius:50%;background:var(--blue);display:flex;align-items:center;justify-content:center;font-size:22px;color:#fff;font-family:var(--serif)">P</div>
  <div>
    <strong style="font-size:16px;color:var(--ink)">Prerak K Mehta</strong>
    <p style="font-size:13px;color:var(--ink4);margin:2px 0 8px">Founder &amp; Editor-in-Chief, The Streamic · Dublin, Ireland</p>
    <p style="font-size:14px;color:var(--ink3);line-height:1.7;margin:0">Broadcast technology professional with 25+ years of IT and media systems experience. Runs the YouTube channel <em>Prerak&#39;s Tech World</em> and covers broadcast engineering, streaming infrastructure, and media technology trends for The Streamic.</p>
    <div style="display:flex;gap:12px;margin-top:12px;flex-wrap:wrap">
      <a href="https://twitter.com/thestreamic" target="_blank" rel="noopener noreferrer"
        style="display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--blue);text-decoration:none;font-weight:500">&#x1D54F; @thestreamic</a>
      <a href="https://www.linkedin.com/company/thestreamic" target="_blank" rel="noopener noreferrer"
        style="display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--blue);text-decoration:none;font-weight:500">in TheStreamic on LinkedIn</a>
    </div>
  </div>
</div>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">Follow Us</h2>
<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:28px">
  <a href="https://twitter.com/thestreamic" target="_blank" rel="noopener noreferrer"
    style="display:inline-flex;align-items:center;gap:8px;padding:10px 18px;border:1px solid var(--line);border-radius:8px;font-size:14px;font-weight:500;color:var(--ink);text-decoration:none;background:#fff">
    &#x1D54F; Twitter / X &nbsp;<strong>@thestreamic</strong>
  </a>
  <a href="https://www.linkedin.com/company/thestreamic" target="_blank" rel="noopener noreferrer"
    style="display:inline-flex;align-items:center;gap:8px;padding:10px 18px;border:1px solid var(--line);border-radius:8px;font-size:14px;font-weight:500;color:var(--ink);text-decoration:none;background:#fff">
    in LinkedIn &nbsp;<strong>TheStreamic</strong>
  </a>
</div>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">Contact</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.7">For editorial enquiries, corrections, or advertising: <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a> &nbsp;|&nbsp; <a href="contact.html" style="color:var(--blue)">Use our contact form &rarr;</a></p>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def contact_page():
    return f"""{head("Contact — The Streamic","Get in touch with The Streamic editorial team in Dublin, Ireland.",f"{BASE_URL}/contact.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 0 80px;max-width:680px">
<h1 style="font-family:var(--serif);font-size:clamp(28px,4vw,40px);margin-bottom:8px">Contact</h1>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:32px">We welcome editorial feedback, tips, corrections, and partnership enquiries.</p>
<div style="background:var(--bg);border-radius:14px;padding:24px 28px;margin-bottom:32px">
  <p style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--ink4);margin-bottom:12px">Our Address</p>
  <address style="font-style:normal;font-size:14px;color:var(--ink2);line-height:1.8">
    <strong>The Streamic</strong><br>
    Adamstown, Lucan<br>
    Dublin, Ireland
  </address>
  <p style="font-size:14px;color:var(--ink3);margin-top:14px;margin-bottom:4px"><strong style="color:var(--ink)">Email:</strong> <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a></p>
  <p style="font-size:14px;color:var(--ink3);margin-bottom:4px"><strong style="color:var(--ink)">Editorial:</strong> Story tips, corrections, press releases</p>
  <p style="font-size:14px;color:var(--ink3)"><strong style="color:var(--ink)">Advertising:</strong> Include &#34;Advertising&#34; in your subject line</p>
</div>
<h2 style="font-family:var(--serif);font-size:22px;margin-bottom:20px">Send us a message</h2>
<form id="contactForm" style="display:flex;flex-direction:column;gap:16px">
  <div>
    <label for="cf-name" style="display:block;font-size:13px;font-weight:600;color:var(--ink);margin-bottom:6px">Your Name</label>
    <input id="cf-name" type="text" name="name" required placeholder="Jane Smith"
      style="width:100%;padding:10px 14px;border:1px solid var(--line);border-radius:8px;font-size:14px;color:var(--ink);background:#fff;box-sizing:border-box">
  </div>
  <div>
    <label for="cf-email" style="display:block;font-size:13px;font-weight:600;color:var(--ink);margin-bottom:6px">Email Address</label>
    <input id="cf-email" type="email" name="email" required placeholder="you@company.com"
      style="width:100%;padding:10px 14px;border:1px solid var(--line);border-radius:8px;font-size:14px;color:var(--ink);background:#fff;box-sizing:border-box">
  </div>
  <div>
    <label for="cf-subject" style="display:block;font-size:13px;font-weight:600;color:var(--ink);margin-bottom:6px">Subject</label>
    <input id="cf-subject" type="text" name="subject" placeholder="Editorial feedback / Story tip / Advertising"
      style="width:100%;padding:10px 14px;border:1px solid var(--line);border-radius:8px;font-size:14px;color:var(--ink);background:#fff;box-sizing:border-box">
  </div>
  <div>
    <label for="cf-message" style="display:block;font-size:13px;font-weight:600;color:var(--ink);margin-bottom:6px">Message</label>
    <textarea id="cf-message" name="message" required rows="5" placeholder="Your message..."
      style="width:100%;padding:10px 14px;border:1px solid var(--line);border-radius:8px;font-size:14px;color:var(--ink);background:#fff;box-sizing:border-box;resize:vertical"></textarea>
  </div>
  <button type="submit" id="cf-submit"
    style="align-self:flex-start;padding:11px 28px;background:var(--blue);color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;transition:background .15s ease">
    Send Message
  </button>
</form>
<div id="cf-status" style="margin-top:16px;font-size:14px;display:none"></div>
<script>
(function(){{
  var form=document.getElementById('contactForm');
  var status=document.getElementById('cf-status');
  var btn=document.getElementById('cf-submit');
  form.addEventListener('submit',function(e){{
    e.preventDefault();
    btn.textContent='Sending...';btn.disabled=true;
    var name=document.getElementById('cf-name').value;
    var email=document.getElementById('cf-email').value;
    var subj=document.getElementById('cf-subject').value||'Contact from The Streamic';
    var msg=document.getElementById('cf-message').value;
    var body='From: '+name+' <'+email+'>\n\n'+msg;
    window.location.href='mailto:technodate3@gmail.com'
      +'?subject='+encodeURIComponent(subj)+'&body='+encodeURIComponent(body);
    status.textContent='Your email client has been opened with your message pre-filled.';
    status.style.color='#34C759';status.style.display='block';
    btn.textContent='Send Message';btn.disabled=false;
  }});
}})();
</script>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def privacy_page():
    yr = datetime.now().year
    return f"""{head("Privacy Policy — The Streamic","Privacy Policy for thestreamic.in",f"{BASE_URL}/privacy.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 0 80px;max-width:760px">
<h1 style="font-family:var(--serif);font-size:clamp(24px,4vw,38px);margin-bottom:20px">Privacy Policy</h1>
<p style="font-size:12px;color:var(--ink4);margin-bottom:28px">Last updated: March 2026</p>
<div style="font-size:15px;color:var(--ink3);line-height:1.75">
<p style="margin-bottom:16px">This Privacy Policy explains how The Streamic ("we", "us", "our") collects and uses information when you visit thestreamic.in.</p>
<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Cookies and Analytics</h2>
<p style="margin-bottom:16px">We use Google Analytics (GA4) to understand how visitors use our site. Analytics cookies are only placed after you click "Accept all" on our cookie banner. You can withdraw consent at any time by clearing your browser cookies.</p>
<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Advertising</h2>
<p style="margin-bottom:16px">We display advertisements via Google AdSense (publisher ID: {ADS}). Google may use cookies to show you personalised ads based on your browsing history. You can opt out at <a href="https://adssettings.google.com" rel="nofollow" style="color:var(--blue)">adssettings.google.com</a>.</p>
<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Data we do not collect</h2>
<p style="margin-bottom:16px">We do not collect names, email addresses, or other personal data unless you contact us directly by email.</p>
<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Contact</h2>
<p>Privacy queries: <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a></p>
</div>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def terms_page():
    return f"""{head("Terms of Use — The Streamic","Terms of Use for thestreamic.in",f"{BASE_URL}/terms.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 0 80px;max-width:760px">
<h1 style="font-family:var(--serif);font-size:clamp(24px,4vw,38px);margin-bottom:20px">Terms of Use</h1>
<p style="font-size:12px;color:var(--ink4);margin-bottom:28px">Last updated: March 2026</p>
<div style="font-size:15px;color:var(--ink3);line-height:1.75">
<p style="margin-bottom:16px">By accessing thestreamic.in you agree to these Terms of Use.</p>
<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Content</h2>
<p style="margin-bottom:16px">Original editorial content on The Streamic is copyright © The Streamic. RSS-curated news summaries credit and link to their original sources. All third-party trademarks are the property of their respective owners.</p>
<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Disclaimer</h2>
<p style="margin-bottom:16px">Content is provided for informational purposes. We make no warranties about accuracy or completeness. The Streamic is not responsible for third-party content linked from this site.</p>
<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">External Links</h2>
<p style="margin-bottom:16px">We link to external sources with rel="nofollow". We are not responsible for the content or privacy practices of linked websites.</p>
</div>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def howto_page():
    guides = [
        {
            "title": "Premiere Pro to Avid Media Composer",
            "desc": "AAF, EDL, and Direct Link interchange methods. Codec compatibility, audio mapping, and troubleshooting the most common handoff failures.",
            "href": "articles/guide-premiere-to-avid.html",
            "tag": "Post-Production",
            "time": "8 min",
        },
        {
            "title": "Vantage: Transcode Any File to MP4 on a NAS Share",
            "desc": "Build a hot folder workflow in Telestream Vantage that accepts any input format and delivers broadcast-ready H.264 MP4 to a local NAS.",
            "href": "articles/guide-vantage-nas-transcode.html",
            "tag": "Vantage · Workflow",
            "time": "10 min",
        },
        {
            "title": "Vantage: Output to AWS S3 for Cloud Delivery",
            "desc": "Extend your Vantage workflow to deliver MP4 output directly to Amazon S3. IAM setup, S3 storage configuration, and parallel NAS + cloud delivery.",
            "href": "articles/guide-vantage-aws-transcode.html",
            "tag": "Vantage · AWS",
            "time": "9 min",
        },
        {
            "title": "Strawberry PAM + Avid Media Composer Workflow",
            "desc": "Configure Production Flow's Strawberry for collaborative editing with Avid Media Composer. Shared storage, ingest hot folders, version control, and automated delivery.",
            "href": "articles/guide-avid-strawberry.html",
            "tag": "PAM · Avid",
            "time": "10 min",
        },
        {
            "title": "Audio Conform: Avid Media Composer to Pro Tools and Back",
            "desc": "Export AAF from Avid, open in Pro Tools for audio finishing, and return the mix in sync. Covers sample rates, BWF export, and timecode alignment.",
            "href": "articles/guide-audio-conform-avid-protools.html",
            "tag": "Avid · Pro Tools · Audio",
            "time": "10 min",
        },
        {
            "title": "Clearing Cache in Avid MediaCentral Cloud UX (2025)",
            "desc": "Fix slow loads, stale thumbnails, and playback errors by clearing browser, application, and server-side proxy cache in MediaCentral Cloud UX.",
            "href": "articles/guide-media-central-cache.html",
            "tag": "MediaCentral · Admin",
            "time": "7 min",
        },
        {
            "title": "Avid MediaCentral Health Check: Services, Connections, and Logs",
            "desc": "Run a full pre-air health check — verify MCPS services, Interplay and iNEWS connections, licensing, and system logs before going on air.",
            "href": "articles/guide-avid-media-central-health-check.html",
            "tag": "MediaCentral · Infrastructure",
            "time": "12 min",
        },
        {
            "title": "Integrating Vizrt Graphics with Avid MediaCentral and iNEWS",
            "desc": "Configure the Vizrt Plugin for MediaCentral and the MOS Gateway to connect Viz Engine templates to iNEWS stories for story-driven graphics playout.",
            "href": "articles/guide-vizrt-avid-integration.html",
            "tag": "Vizrt · iNEWS · MOS",
            "time": "14 min",
        },
        {
            "title": "Upgrade to Windows 11",
            "desc": "Step-by-step upgrade guide for broadcast workstations and edit suites. Compatibility checks, driver verification, and rollback procedure.",
            "href": "articles/guide-windows11-upgrade.html",
            "tag": "IT · Windows",
            "time": "5 min",
        },
        {
            "title": "Upgrade to macOS Sequoia",
            "desc": "How to safely upgrade a post-production Mac. Pre-upgrade checklist, NLE compatibility matrix, and what to do if your plugins break.",
            "href": "articles/guide-macos-upgrade.html",
            "tag": "IT · macOS",
            "time": "5 min",
        },
    ]

    cards = "".join(f''' <div class="howto-card">
  <div class="howto-tag">{g["tag"]}</div>
  <h3>{g["title"]}</h3>
  <p>{g["desc"]}</p>
  <div class="howto-foot">
    <span class="howto-time">&#128337; {g["time"]} read</span>
    <a href="{g["href"]}">Read guide &rarr;</a>
  </div>
</div>''' for g in guides)

    return f"""{head("How-To Guides — The Streamic",
                      "Practical broadcast and post-production workflow guides: Vantage, Avid, Strawberry, AWS, and more.",
                      f"{BASE_URL}/howto.html")}
<body>
{nav("howto.html")}
<main><div class="w">
<div class="cat-hdr">
  <h1>How-To Guides</h1>
  <p>Practical workflow guides for broadcast engineers, post-production supervisors, and media technology teams.</p>
</div>
<div class="howto-grid">{cards}</div>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def vlog_page():
    return f"""{head("Editor's Desk — The Streamic","Notes, commentary and perspective from the Streamic editorial team.",f"{BASE_URL}/vlog.html")}
<body>
{nav("vlog.html")}
<main><div class="w" style="padding:52px 0 80px;max-width:760px">
<div class="cat-hdr">
  <h1>Editor's Desk</h1>
  <p>Commentary, perspective, and notes from the editorial team at The Streamic.</p>
</div>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:24px">The Streamic covers broadcast and streaming technology with a focus on what matters operationally to engineers and technology leaders. This is where we share perspective beyond the news cycle.</p>
<div style="background:var(--bg);border-radius:14px;padding:28px;font-size:14px;color:var(--ink3);line-height:1.7">
  <strong style="color:var(--ink);display:block;margin-bottom:8px">What we're watching in 2026</strong>
  The ST 2110 adoption curve in small-market broadcasters. The economics of cloud production post-Paris 2024. How C2PA is changing newsroom verification workflows. The quiet revolution of operational AI inside MAM systems.
</div>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

# ── SITEMAP
def sitemap(arts):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    statics = [
        ("index.html","daily","1.0"),("featured.html","daily","0.98"),
        ("streaming.html","daily","0.9"),("cloud.html","daily","0.9"),
        ("graphics.html","daily","0.9"),("playout.html","daily","0.9"),
        ("infrastructure.html","daily","0.9"),("ai-post-production.html","daily","0.9"),
        ("newsroom.html","daily","0.9"),("howto.html","weekly","0.8"),
        ("about.html","monthly","0.6"),("contact.html","monthly","0.5"),
        ("privacy.html","yearly","0.3"),("terms.html","yearly","0.3"),
        ("vlog.html","weekly","0.7"),
    ]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for pg,fr,pr in statics:
        lines.append(f'  <url><loc>{BASE_URL}/{pg}</loc><lastmod>{today}</lastmod><changefreq>{fr}</changefreq><priority>{pr}</priority></url>')
    for a in arts:
        slug_ = a.get('slug', '')
        pub_ = a.get('published', '')
        lines.append(f'  <url><loc>{BASE_URL}/articles/{slug_}.html</loc><lastmod>{pub_}</lastmod><changefreq>monthly</changefreq><priority>0.75</priority></url>')
    lines.append('</urlset>')
    return "\n".join(lines)

# ── MAIN
def main():
    with open(ARTS_F,"r",encoding="utf-8") as f: arts = json.load(f)
    if not arts: raise SystemExit("No articles")

    os.makedirs(ARTS_D, exist_ok=True)

    # Write article pages
    written = 0
    for a in arts:
        html = article_page(a)
        slug_ = a.get('slug', '')
        w(os.path.join(ARTS_D, f"{slug_}.html"), html)
        written += 1
        leg = a.get("legacy_slug")
        if leg and leg != a["slug"]:
            w(os.path.join(ARTS_D, f"{leg}.html"), html)
            written += 1
    print(f"  ✓ {written} article files")

    # Category pages
    by_cat = {}
    for a in arts: by_cat.setdefault(a["category"],[]).append(a)
    for cat,ca in by_cat.items():
        pages = category_page(cat, ca)
        for pg, html in pages:
            fname = f"{cat}.html" if pg==0 else f"{cat}-p{pg+1}.html"
            w(os.path.join(DOCS, fname), html)
    print(f"  ✓ {len(by_cat)} category pages")

    # Featured + index
    feat_arts = sorted(arts, key=lambda a: a["published"], reverse=True)
    fp = featured_page(feat_arts)
    w(os.path.join(DOCS,"featured.html"), fp)
    w(os.path.join(DOCS,"index.html"),    fp)
    print("  ✓ featured.html + index.html")

    # posts.html — All Articles page (links to articles/, not posts/)
    ap = all_articles_page(feat_arts)
    w(os.path.join(DOCS,"posts.html"), ap)
    w(os.path.join(ROOT,"posts.html"), ap)
    print("  ✓ posts.html (All Articles)")

    # Static pages
    # Ensure all 8 category pages exist even if some have no articles yet
    for _cat_slug in ["graphics"]:
        _cp = os.path.join(DOCS, f"{_cat_slug}.html")
        if not os.path.exists(_cp):
            _ci = CAT.get(_cat_slug, {})
            _pages = category_page(_cat_slug, [])
            for _pn, _ph in _pages:
                _fname = f"{_cat_slug}.html" if _pn==0 else f"{_cat_slug}-p{_pn+1}.html"
                w(os.path.join(DOCS, _fname), _ph)
            print(f"  ✓ {_cat_slug}.html generated (empty category placeholder)")

    w(os.path.join(DOCS,"about.html"),   about_page())
    w(os.path.join(DOCS,"contact.html"), contact_page())
    w(os.path.join(DOCS,"privacy.html"), privacy_page())
    w(os.path.join(DOCS,"terms.html"),   terms_page())
    w(os.path.join(DOCS,"howto.html"),   howto_page())
    w(os.path.join(DOCS,"how-to.html"),  howto_page())
    w(os.path.join(DOCS,"vlog.html"),    vlog_page())
    print("  ✓ static pages")

    # Sitemap + robots
    w(os.path.join(DOCS,"sitemap.xml"), sitemap(arts))
    w(os.path.join(DOCS,"robots.txt"),  f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n")

    # Copy style.css + main.js to docs/
    for f_name in ("style.css","main.js"):
        src = os.path.join(ROOT,f_name)
        if os.path.isfile(src): shutil.copy2(src, os.path.join(DOCS,f_name))
    print("  ✓ style.css + main.js → docs/")

    # Ads.txt + CNAME + .nojekyll
    w(os.path.join(DOCS,"ads.txt"), f"google.com, pub-8033069131874524, DIRECT, f08c47fec0942fa0\n")
    w(os.path.join(DOCS,"CNAME"), "thestreamic.in\n")
    open(os.path.join(DOCS,".nojekyll"),"w").close()
    w(os.path.join(ROOT,"CNAME"), "thestreamic.in\n")

    # Copy style.css + main.js to root (referenced by root articles/ fallback)
    for fn in ["style.css","main.js","ads.txt","robots.txt"]:
        src_f = os.path.join(DOCS,fn)
        if os.path.isfile(src_f): shutil.copy2(src_f, os.path.join(ROOT,fn))

    # Mirror ONLY how-to guide articles to root/articles/
    # (All other article mirrors removed — GitHub Pages serves from docs/ only)
    root_arts = os.path.join(ROOT,"articles")
    os.makedirs(root_arts, exist_ok=True)
    howto_guides = [fn for fn in os.listdir(ARTS_D) if fn.startswith("guide-") and fn.endswith(".html")]
    for fn in howto_guides:
        shutil.copy2(os.path.join(ARTS_D,fn), os.path.join(root_arts,fn))
    print(f"  ✓ {len(howto_guides)} how-to guides mirrored to root/articles/")

    # ── Prepare docs/data/ for client-side JS ──────────────────────────────
    docs_data_dir = os.path.join(DOCS, "data")
    os.makedirs(docs_data_dir, exist_ok=True)

    # 1. news.json (live RSS feed)
    news_src = os.path.join(ROOT, "data", "news.json")
    news_dst = os.path.join(docs_data_dir, "news.json")
    if os.path.exists(news_src):
        with open(news_src,encoding="utf-8") as f: raw = json.load(f)
        if isinstance(raw,list):
            out = {"featured_priority":raw[:6],"items":raw[6:]}
        elif isinstance(raw,dict) and "items" in raw:
            out = raw
        else:
            flat=[]
            for cat,lst in raw.items():
                for it in (lst or []):
                    it.setdefault("category",cat); flat.append(it)
            flat.sort(key=lambda x:x.get("pubDate",""),reverse=True)
            out = {"featured_priority":flat[:6],"items":flat[6:]}
        with open(news_dst,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False)
        print(f"  ✓ docs/data/news.json ({len(out.get('items',[]))} items)")


    # 2. CRITICAL: generated_articles.json (Groq summaries + internal URLs)
    gen_src = os.path.join(ROOT, "data", "generated_articles.json")
    if os.path.exists(gen_src):
        with open(gen_src, encoding="utf-8") as _f:
            raw_gen = json.load(_f)
        # Sort newest first
        raw_gen.sort(key=lambda a: a.get("published",""), reverse=True)
        out_gen = {
            "featured_priority": raw_gen[:6],
            "items":             raw_gen[6:]
        }
        gen_dst = os.path.join(docs_data_dir, "generated_articles.json")
        with open(gen_dst, "w", encoding="utf-8") as _f:
            json.dump(out_gen, _f, ensure_ascii=False)
        print(f"  ✓ docs/data/generated_articles.json ({len(raw_gen)} articles, Groq summaries included)")
    else:
        print("  ⚠ data/generated_articles.json not found")

    print(f"\n✅ Build complete: {len(arts)} articles, {len(by_cat)} categories")

if __name__ == "__main__":
    main()
