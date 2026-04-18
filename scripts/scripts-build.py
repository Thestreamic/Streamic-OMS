"""
scripts/build.py &#8212; The Streamic site builder
Apple Newsroom-style static site generator
"""
import json, os, re, shutil
from datetime import datetime, timezone

ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARTS_F    = os.path.join(ROOT, "data", "generated_articles.json")
NEWS_F    = os.path.join(ROOT, "data", "news.json")
DOCS      = os.path.join(ROOT, "docs")
ARTS_D    = os.path.join(DOCS, "articles")
BASE_URL  = os.environ.get("SITE_BASE_URL", "https://www.thestreamic.in").rstrip("/")
GA        = "G-0VSHDN3ZR6"
ADS       = "ca-pub-8033069131874524"
AUTHOR    = "The Streamic Editorial Team"

# ── Editor's Note (REMOVED — disclosure lives in editorial-policy.html) ─────
_EDITORS_NOTE_HTML = ""

PAGE_SIZE = 24

# ── AdSense approval mode ─────────────────────────────────────────────────────
# Show curated high-quality content. Full dataset remains hidden.
MAX_ARTICLES   = 120         # 78 editorial + top RSS; raised from 35
VISIBLE_CAT    = "ai-post-production"  # only this category page is indexed
MIN_BODY_SCORE = 50          # minimum editorial score to appear on homepage
MIN_ARTICLE_WORDS = 500      # hard quality gate — matches AI-upgraded output; scaffolds blocked separately by _is_ai_upgraded()

# ── Broadcast & Media IT relevance terms ──────────────────────────────────────
# Articles must contain at least 2 of these terms (case-insensitive) to pass.
# This keeps the site focused on genuine broadcast engineering content.
BROADCAST_TERMS = {
    # Vendors & products
    "avid", "media composer", "interplay", "mediacentral", "isis", "nexis",
    "adobe", "premiere", "after effects", "frame.io",
    "vizrt", "viz one", "viz engine", "viz artist", "ndn",
    "grass valley", "gv", "edius", "kameleon",
    "harmonic", "harmonic inc", "spectrum x", "polaris",
    "telestream", "vantage", "lightspeed", "wirecast",
    "pebble", "pebble beach", "lighthouse", "marina",
    "imagine communications", "selenio",
    "dalet", "dalet flex", "dalia",
    "mediageni", "mediagenix", "whats on",
    "editshare", "mediasilo",
    "cinegy", "playout", "cinegy air",
    "evertz", "dreamcatcher",
    "ross video", "xpression", "carbonite",
    "newtek", "tricaster",
    "blackmagic", "davinci resolve", "atem", "decklink",
    "playbox", "playbox neo",
    "tedial", "media it",
    "clear-com", "riedel", "bolero",
    "aveco", "astra",
    "signiant", "aspera",
    # Protocols & standards
    "smpte", "st 2110", "st2110", "st 2022", "nmos", "is-04", "is-05",
    "aes67", "dante", "ravenna",
    "scte-35", "scte 35", "bxf", "mos protocol", "mos gateway",
    "ndi", "srt", "rist", "zixi",
    "hls", "dash", "cmaf", "abr",
    "atsc", "atsc 3.0", "dvb",
    # Broadcast infrastructure
    "sdi", "12g-sdi", "ip core", "ip routing",
    "mam", "pam", "dam", "media asset management",
    "nrcs", "newsroom computer", "inews", "enps", "octopus",
    "playout", "channel in a box", "channel-in-a-box", "ciab",
    "master control", "mcr", "automation engine",
    "baseband", "embedder", "de-embedder",
    "multiviewer", "monitoring", "probe",
    "lto", "archive", "nearline", "deep archive",
    # Workflow & operations
    "broadcast", "broadcaster", "broadcast engineer",
    "post-production", "post production", "color grading", "colour grading",
    "transcode", "transcoding", "encoding", "mezzanine",
    "ingest", "capture", "record",
    "graphics", "cg", "lower third", "ticker",
    "rundown", "studio automation",
    "cloud playout", "cloud production", "remi", "remote production",
    "cdn", "content delivery", "origin server",
    "ott", "fast channel", "streaming", "live streaming",
    "drm", "conditional access", "forensic watermark",
    "qc", "quality control", "loudness", "ebu r128",
    "metadata", "metadata enrichment",
    "aaf", "edl", "xml", "mxf", "imf",
    # AI / cloud
    "ai", "artificial intelligence", "machine learning",
    "aws", "amazon web services", "elemental",
    "azure", "google cloud",
    "ai metadata", "ai enrichment", "deepva",
    "agentic", "llm",
}

CAT = {
    "featured":           {"label":"Featured",           "icon":"⭐","color":"#1d1d1f","desc":"Independent broadcast and streaming technology journalism."},
    "streaming":          {"label":"Streaming",          "icon":"&#128225;","color":"#0066cc","desc":"OTT platforms, encoding, CDN infrastructure, live streaming workflows."},
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
def eu(s): return str(s).replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")  # URL-safe: keeps & raw in src/href attrs
def d(iso):
    try: return datetime.strptime(iso[:10],"%Y-%m-%d").strftime("%B %d, %Y")
    except: return iso
def w(path, txt):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"w",encoding="utf-8") as f: f.write(txt)
def rm(wc): return f"{max(1,round(wc/200))} min read"


def smart_dek(a):
    title=(a.get("title") or "").strip()
    cat=(a.get("category") or "featured").lower()
    src=(a.get("source_domain") or "industry source").strip()
    t=title.lower()
    if "ai" in t or "automation" in t:
        return f"Why it matters: {src} highlights how AI is moving from experimentation into practical broadcast workflows and operational efficiency."
    if "cloud" in t or "openshift" in t or "aws" in t:
        return f"Why it matters: this development points to deeper cloud adoption across media infrastructure, delivery resilience, and cost-aware scaling."
    if "studio" in t or "graphics" in t or "viz" in t:
        return f"Why it matters: graphics and studio tooling decisions increasingly shape production flexibility, visual quality, and the economics of live output."
    if "sports" in t or "live" in t or "simulcast" in t:
        return f"Why it matters: live and sports workflows continue to drive investment in reliability, latency control, and multi-platform distribution."
    if "encoder" in t or "decoder" in t or "jpeg xs" in t or "ip" in t or "st 2110" in t:
        return f"Why it matters: transport and infrastructure upgrades like this directly affect signal reliability, interoperability, and engineering workload."
    if cat == "newsroom":
        return f"Why it matters: newsroom and media operations teams should watch how this affects speed, workflow coordination, and content turnaround."
    if cat == "playout":
        return f"Why it matters: playout and delivery teams should evaluate the operational impact on automation, control, and service continuity."
    if cat == "graphics":
        return f"Why it matters: design and production teams should assess how this influences graphics performance, workflow efficiency, and output quality."
    return f"Why it matters: {src} signals another shift in how broadcast and media teams are modernising tools, workflows, and delivery infrastructure."

def diversify_arts(arts, max_per_source=1):
    """
    Round-robin interleave articles so no consecutive items share the same source.
    Groups by source_domain and picks one from each group in rotation.
    Ensures feed like: Avid, Vizrt, Pebble, GV, Dalet, Harmonic, AWS, Telestream...
    """
    from collections import defaultdict
    buckets = defaultdict(list)
    for a in arts:
        src = a.get("source_domain", "").replace("https://","").replace("www.","").split("/")[0].lower()
        buckets[src].append(a)
    # Sort buckets by the newest article so freshest sources lead
    bucket_list = sorted(buckets.values(), key=lambda b: b[0].get("published",""), reverse=True)
    result = []
    while any(bucket_list):
        for bucket in bucket_list:
            if bucket:
                result.append(bucket.pop(0))
        bucket_list = [b for b in bucket_list if b]
    return result

# ── shared HTML blocks
def _consent():
    return f"""<script>
    window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}
    gtag('consent','default',{{'analytics_storage':'denied','ad_storage':'denied',
    'ad_user_data':'denied','ad_personalization':'denied','wait_for_update':500}});
  </script>
  <script async src="https://www.googletagmanager.com/gtag/js?id={GA}"></script>
  <script>gtag('js',new Date());gtag('config','{GA}');</script>"""

def _cookie_banner():
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

def _ad():
    # Ad slots removed - using Google Auto-Ads after AdSense approval
    # The AdSense script in <head> remains for approval verification
    return ""

def _fonts():
    return '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">'

def head(title, desc, canon, css="style.css", og_img="", robots="index,follow"):
    og = f'  <meta property="og:image" content="{eu(og_img)}">\n' if og_img else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  {_consent()}
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{e(title)}</title>
  <meta name="description" content="{e(desc)}">
  <meta name="robots" content="{robots}">
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
        ("/",                              "Home"),
        ("ai-post-production.html",        "AI in Broadcasting"),
        ("howto.html",                     "How-To Guides"),
        ("post-production-workflows.html", "Post Production Workflows"),
        ("insights.html",                  "Expert Insights"),
        ("editorsdesk.html",               "Editorial Insights"),
    ]
    def _nav_li(h, lbl, base=base, active=active):
        cls = ' class="active"' if h == active else ''
        href = h if h.startswith("/") else f"{base}{h}"
        return f'<li><a href="{href}"{cls}>{lbl}</a></li>'
    lis = "".join(_nav_li(h, lbl) for h, lbl in cats)
    mob_all = cats + [("about.html","About"),("contact.html","Contact")]
    mob_links = "".join(
        f'<a href="{h if h.startswith("/") else base+h}">{lbl}</a>' for h, lbl in mob_all)
    _onclick = (
        "onclick=\"(function(b,m){"
        "m.classList.toggle('open');"
        "b.setAttribute('aria-expanded',m.classList.contains('open'));"
        "document.body.classList.toggle('menu-open',m.classList.contains('open'));"
        "})(this,this.closest('nav').querySelector('.nav-mob'))\""
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
      <button class="nav-toggle" aria-label="Menu" type="button" {_onclick}>
        <span></span><span></span><span></span>
      </button>
    </div>
  </div>
  <div class="nav-gold" aria-hidden="true"></div>
  <div class="nav-mob">{mob_links}</div>
</nav>"""

def catbar(active_cat="", base=""):
    # Hidden during AdSense review — only AI Post visible via nav
    return ""

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


# ── NEWS GRID (SSR from generated_articles.json)
def _nc_img(a, base=""):
    img = eu(a.get("image_url",""))
    fb  = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    if img:
        slug_ = a.get('slug', '')
        return f'<div class="nc-img"><a href="{base}articles/{slug_}.html" tabindex="-1" aria-hidden="true"><img src="{img}" alt="{title}" loading="lazy" onerror="this.src=&apos;{fb}&apos;"></a></div>'
    return f'<div class="nc-img nc-img-ph"></div>'

def news_card(a, base="", is_first=False):
    """SSR bento-grid-item &#8212; mirrors JS buildFeatured/buildStandard structure exactly."""
    cat   = a.get("category","featured")
    cinfo = CAT.get(cat, CAT["featured"])
    slug_ = a.get('slug', '')
    href  = f"{base}articles/{slug_}.html"
    img   = eu(a.get("image_url",""))
    fb_   = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    src   = e(a.get("source_domain","").replace("https://","").replace("www.","").split("/")[0].upper())
    cat_lbl = cinfo["label"]

    if is_first:
        # Featured: vertical, large image - no summary (editorial feel)
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
        # Standard: vertical cards - no summary (clean editorial look)
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

def news_grid(arts, base="", grid_id="bentoGridLarge"):
    """SSR bento grid. Use grid_id='catGrid' on category pages to keep SSR content."""
    if not arts: return ""
    cards = "\n".join(
        news_card(a, base, is_first=(i==0))
        for i, a in enumerate(arts)
    )
    return f'<ul id="{grid_id}" class="bento-grid-large">\n{cards}\n</ul>'

# ── EDITORIAL CARD (deep-dive articles)
def ed_card(a, base=""):
    cat   = a.get("category","featured")
    cinfo = CAT.get(cat, CAT["featured"])
    slug_ = a.get('slug', '')
    href  = f"{base}articles/{slug_}.html"
    img   = eu(a.get("image_url",""))
    fb    = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    raw_dek = (a.get("dek") or a.get("meta_description",""))[:200]
    dek   = raw_dek.replace("<","&lt;").replace(">","&gt;")  # allow &mdash; etc, block tags
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
    img   = eu(a.get("image_url",""))
    fb    = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    dek   = (a.get("card_summary") or a.get("dek") or "")[:200].replace("<","&lt;").replace(">","&gt;")
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
    """
    Apple Newsroom-style card grid with images and diversity.
    Includes both pure RSS items and rewrite_feed_local scaffolds.
    """
    def _is_news_card(a):
        gen_by = (a.get("generated_by") or "").lower()
        is_scaffold = gen_by in ("", "rewrite_feed_local", "rewrite_feed")
        if not (a.get("is_editorial") or a.get("editorial")):
            return True
        if is_scaffold:
            return True
        return False

    rss_pool = [a for a in arts if _is_news_card(a)]
    rss = diversify_arts(rss_pool)[:12]
    if not rss:
        return ""

    fb_ = f"{base}assets/fallback.jpg"
    cards_html = ""
    for i, a in enumerate(rss):
        cat      = a.get("category", "featured")
        cinfo    = CAT.get(cat, CAT["featured"])
        slug_    = a.get("slug", "")
        href     = f"{base}articles/{slug_}.html"
        title    = e(a.get("title", ""))
        img      = eu(a.get("image_url", ""))
        src_dom  = e(a.get("source_domain","").replace("https://","").replace("www.","").split("/")[0])
        dt       = d(a.get("published",""))
        src_url  = e(a.get("source_url","") or a.get("url","") or "")
        cat_lbl  = cinfo["label"]
        cat_col  = cinfo["color"]
        body     = a.get("body_html","") or ""
        wc       = len(re.sub(r"<[^>]+>"," ",body).split())
        has_long = wc >= 500 and ("<h2>" in body or "<h3>" in body)
        btn_txt  = "Read Analysis" if has_long else "View Source"
        btn_href = href if has_long else (src_url or href)
        btn_tgt  = ' target="_blank" rel="noopener noreferrer nofollow"' if (not has_long and src_url) else ""

        # First card is a wide hero; rest are standard
        card_cls = "ic-card ic-card-hero" if i == 0 else "ic-card"
        img_load = "eager" if i == 0 else "lazy"

        cards_html += f"""
<article class="{card_cls}">
  <div class="ic-img-wrap">
    <a href="{href}" tabindex="-1" aria-hidden="true">
      <img src="{img}" alt="{title}" loading="{img_load}" onerror="this.onerror=null;this.src='{fb_}'">
    </a>
  </div>
  <div class="ic-body">
    <span class="ic-cat-tag" style="color:{cat_col}">{cat_lbl}</span>
    <h3 class="ic-title">
      <a href="{href}">{title}</a>
    </h3>
    <div class="ic-foot">
      <span class="ic-src">{src_dom.upper()}</span>
      <time class="ic-date">{dt}</time>
      <a href="{btn_href}"{btn_tgt} class="ic-btn">{btn_txt} &rarr;</a>
    </div>
  </div>
</article>"""

    disclosure = """<div class="ic-disclosure">
  <p><strong>Editor&rsquo;s Note:</strong> This technical briefing was prepared from source-grounded industry reporting
  with AI assistance. Reviewed and curated by <strong>The Streamic Editorial Team</strong>.</p>
</div>"""

    return f"""<section class="intel-section">
  <style>
    /* ── Intelligence Feed — Apple Newsroom Cards ─────────────────────── */
    .intel-section {{
      padding-top: 60px;
      margin: 0;
    }}
    .intel-hdr {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 6px;
      padding-bottom: 16px;
      border-bottom: 2px solid #1a1a1a;
    }}
    .intel-h2 {{
      font-family: 'DM Sans', 'Helvetica Neue', Arial, sans-serif;
      font-size: clamp(28px, 3.5vw, 42px);
      font-weight: 800;
      letter-spacing: -0.01em;
      color: #1a1a1a;
      line-height: 1.1;
      margin: 0;
    }}
    .intel-h2 span {{ color: #4a101d; }}
    .intel-view-all {{
      font-size: 13px;
      font-weight: 600;
      color: var(--blue);
      text-decoration: none;
      white-space: nowrap;
      flex-shrink: 0;
    }}
    .intel-sub {{
      font-size: 14px;
      color: var(--ink3);
      margin: 12px 0 28px;
      line-height: 1.6;
      max-width: 640px;
    }}
    /* ── Apple Newsroom 3-col grid ─────────────────────────────────────── */
    .ic-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 20px;
    }}
    @media (max-width: 1024px) and (min-width: 641px) {{
      .ic-grid {{ grid-template-columns: repeat(2, 1fr); }}
    }}
    @media (max-width: 640px) {{
      .ic-grid {{ grid-template-columns: 1fr; gap: 16px; }}
    }}
    /* ── Base card — white rounded, Apple style ────────────────────────── */
    .ic-card {{
      background: #ffffff;
      border-radius: 14px;
      box-shadow: 0 2px 8px rgba(0,0,0,.06);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transition: box-shadow .2s ease, transform .2s ease;
    }}
    .ic-card:hover {{
      box-shadow: 0 10px 32px rgba(0,0,0,.11);
      transform: translateY(-3px);
    }}
    /* Hero card spans all columns */
    .ic-card-hero {{
      grid-column: 1 / -1;
      flex-direction: row;
    }}
    .ic-card-hero .ic-img-wrap {{
      width: 52%;
      min-height: 280px;
    }}
    .ic-card-hero .ic-body {{
      flex: 1;
      padding: 32px 36px;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .ic-card-hero .ic-title {{
      font-size: clamp(18px, 2vw, 24px);
    }}
    @media (max-width: 800px) {{
      .ic-card-hero {{
        flex-direction: column;
      }}
      .ic-card-hero .ic-img-wrap {{
        width: 100%;
        min-height: 220px;
      }}
      .ic-card-hero .ic-body {{
        padding: 20px 22px;
      }}
    }}
    /* ── Card image ───────────────────────────────────────────────────── */
    .ic-img-wrap {{
      width: 100%;
      height: 190px;
      overflow: hidden;
      flex-shrink: 0;
    }}
    .ic-img-wrap a {{
      display: block;
      width: 100%;
      height: 100%;
    }}
    .ic-img-wrap img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      transition: transform 0.35s ease;
    }}
    .ic-card:hover .ic-img-wrap img {{
      transform: scale(1.04);
    }}
    /* ── Card body ────────────────────────────────────────────────────── */
    .ic-body {{
      padding: 20px 22px 18px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      flex: 1;
    }}
    .ic-cat-tag {{
      font-size: 10px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.9px;
    }}
    .ic-title {{
      font-family: var(--serif);
      font-size: 16px;
      line-height: 1.3;
      letter-spacing: -0.03em;
      color: #1a1a1a;
      margin: 0;
      flex: 1;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .ic-title a {{
      color: inherit;
      text-decoration: none;
    }}
    .ic-title a:hover {{ color: var(--blue); }}
    .ic-foot {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding-top: 10px;
      border-top: 1px solid #f0f0f0;
      flex-wrap: wrap;
      margin-top: auto;
    }}
    .ic-src {{
      font-size: 10px;
      font-weight: 700;
      color: #999;
      letter-spacing: .5px;
    }}
    .ic-date {{
      font-size: 10px;
      color: #bbb;
      flex: 1;
    }}
    .ic-btn {{
      display: inline-flex;
      align-items: center;
      padding: 6px 14px;
      background: #1a1a1a;
      color: #fff;
      border-radius: 100px;
      font-size: 11px;
      font-weight: 700;
      text-decoration: none;
      letter-spacing: .3px;
      white-space: nowrap;
      transition: background .15s ease;
      flex-shrink: 0;
    }}
    .ic-btn:hover {{ background: var(--blue); }}
    /* ── Disclosure ───────────────────────────────────────────────────── */
    .ic-disclosure {{
      grid-column: 1 / -1;
      padding: 14px 18px;
      background: #f8f8f8;
      border-radius: 8px;
      border: 1px solid #eee;
    }}
    .ic-disclosure p {{
      font-style: italic;
      font-size: 12px;
      color: #999;
      line-height: 1.5;
      margin: 0;
    }}
    .ic-disclosure strong {{ font-style: normal; color: #666; }}
  </style>

  <div class="intel-hdr">
    <h2 class="intel-h2">Latest Technical Briefings<br>&amp; <span>Industry Analysis</span></h2>
    <a href="posts.html" class="intel-view-all">View all articles &rarr;</a>
  </div>
  <p class="intel-sub">Deep-dive reporting on the intersection of cloud production, AI-driven media workflows, and global streaming infrastructure.</p>

  <div class="ic-grid">
    {cards_html}
    {disclosure}
  </div>
</section>"""


def all_articles_page(arts):
    """Generate posts.html - All Articles bento grid linking to articles/."""
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
    <section class="latest" style="margin-top:32px">
      <ul id="bentoGridLarge" class="bento-grid-large">
        {cards}
      </ul>
    </section>
  </div>
</main>
<script type="application/ld+json">{schema}</script>
{footer()}
{_cookie_banner()}
<script src="main.js" defer></script>
</body>
</html>"""


def _score_art(a):
    """Score article quality for homepage curation. Higher = better."""
    body = a.get("body_html","") or ""
    wc   = len(re.sub(r"<[^>]+>"," ",body).split())
    s = 0
    if a.get("is_editorial") or a.get("editorial"): s += 50
    if "<h2>" in body: s += 30
    if wc >= 500: s += 20
    elif wc >= 200: s += 10
    if a.get("quality_score",0) >= 75: s += 25
    return s


def _is_ai_upgraded(a):
    """AdSense compliance: return True if article was enriched by a tier-1/2/3
    AI generator (Mistral, Gemini, Groq, OpenRouter) or is a hand-authored
    editorial. Raw RSS scaffolds (rewrite_feed_local) never get indexed.
    """
    gb = (a.get("generated_by") or "").lower()
    if not gb:
        return False
    if gb in ("rewrite_feed_local", "rewrite_feed"):
        return False
    ai_markers = ("mistral", "gemini", "groq", "openrouter", "deepseek",
                  "gpt_manual_editorial", "generate_summaries")
    return any(m in gb for m in ai_markers)


def _passes_quality_gate(a):
    """Hard quality gate — ADSENSE COMPLIANCE MODE.

    An article may be indexed only when ALL of the following are true:
      1. Body word count ≥ MIN_ARTICLE_WORDS (800) OR hand-authored ≥ 400w.
      2. Article was AI-upgraded OR hand-authored (never raw RSS rewrite).
      3. At least 2 broadcast/media-IT terms present (relevance).

    Raw RSS rewrites (rewrite_feed_local) appear on the site for navigation
    but carry <meta robots="noindex,nofollow">. This is the defence against
    AdSense "Low value content" rejection.
    """
    body = a.get("body_html", "") or ""
    plain = re.sub(r"<[^>]+>", " ", body)
    plain = re.sub(r"\s+", " ", plain).strip()
    words = plain.split()
    wc = len(words)

    is_manual_editorial = a.get("generated_by") == "gpt_manual_editorial"

    if not is_manual_editorial and wc < MIN_ARTICLE_WORDS:
        return False, f"too short ({wc} words, need {MIN_ARTICLE_WORDS})"

    if is_manual_editorial and wc < 400:
        return False, f"editorial too short ({wc} words, need 400)"

    # AdSense: raw RSS rewrites never get indexed
    if not is_manual_editorial and not _is_ai_upgraded(a):
        return False, f"not AI-upgraded (gb={a.get('generated_by') or 'empty'!r})"

    # ── Broadcast relevance gate ─────────────────────────────────────────
    # Check title + body (lowercased) for BROADCAST_TERMS matches
    search_text = (a.get("title", "") + " " + plain).lower()
    matched = set()
    for term in BROADCAST_TERMS:
        if term in search_text:
            matched.add(term)
        if len(matched) >= 2:
            break  # fast exit — 2 is enough

    if len(matched) < 2:
        return False, f"low relevance (matched {len(matched)} terms: {matched})"

    return True, "ok"


def enforce_sections(body_html: str) -> bool:
    """
    AdSense quality scoring: checks for preferred editorial sections.
    Uses a SOFT score so articles are never completely excluded.

    Score >= 1 (out of 2) returns True. This means ONE section is enough.
    Articles with zero sections are still allowed on category pages
    (so pages are never blank) but receive lower _score_art() ranking.

    Scoring:
      +1 for "Why This Matters"
      +1 for "Expert Insight"
    Returns True if score >= 1 — applied OPTIONALLY, not as a hard gate.
    """
    if not body_html:
        return False
    body_lower = body_html.lower()
    score = 0
    if "why this matters" in body_lower:
        score += 1
    if "expert insight" in body_lower:
        score += 1
    return score >= 1


def is_high_value(article: dict) -> bool:
    """
    AdSense quality scoring for RSS articles.

    SAFE FILTERING DESIGN — never returns fewer than needed:
    - Editorial articles always pass (pre-validated long-form content)
    - Industry briefings score points on multiple axes; any score > 0 passes
    - This means the function always returns True for articles with ANY
      substantive content, so category pages are never blank

    The noindex/index decision in main() uses this for ranking,
    but visible_list is always padded to ensure pages have content.
    """
    # Editorial always pass — hand-written or Gemini deep-dives
    if article.get("is_editorial") or article.get("editorial"):
        return True

    body = article.get("body_html", "") or ""
    content = article.get("content") or article.get("description", "") or ""

    # Text content from body_html (strip tags)
    body_text = re.sub(r"<[^>]+>", " ", body)
    body_text  = re.sub(r"\s+", " ", body_text).strip()

    score = 0
    # Section quality — soft score
    if enforce_sections(body):
        score += 2          # Has at least one required section
    # Structural quality
    if "<h2>" in body:
        score += 1          # Has section headings
    # Length quality — any substantive content passes
    if len(body_text) > 800:
        score += 1
    elif len(body_text) > 200 or len(content) > 200:
        score += 0          # Still allowed — just lower ranked

    # Any article with a title passes (never blank)
    return bool(article.get("title", "").strip())

# ── BROADCAST IMAGE SYSTEM ──────────────────────────────────────────────────
# Curated Unsplash images: server rooms, control rooms, vision mixers, cameras,
# edit suites, studio equipment, network infrastructure. NO typewriters, newspapers.

_BAD_IMAGE_IDS = {
    "photo-1495020689067-958852a7765e",   # person reading newspaper
    "photo-1504711434969-e33886168f5c",   # newspaper stack
    "photo-1432821596592-e2c18b78144f",   # TYPEWRITER
    "photo-1453738773917-9c3eff1db985",   # old newspaper on wooden desk
    "photo-1557804506-669a67965ba0",      # generic business meeting room
}

# 30 unique broadcast/media IT images — no repeats, all relevant
_BROADCAST_IMAGES = [
    # Server rooms & data centers
    "photo-1558494949-ef010cbdcc31",      # server room blue LED racks
    "photo-1544197150-b99a580bb7a8",      # data center corridor
    "photo-1573164713988-8665fc963095",   # fiber optic cables glowing
    "photo-1504384308090-c894fdcc538d",   # server room ceiling view
    "photo-1451187580459-43490279c0fa",   # global network data visualization
    # Broadcast control rooms & production
    "photo-1598488035139-bdbb2231ce04",   # audio/broadcast mixing console
    "photo-1478737270239-2f02b77fc618",   # control room buttons & panels
    "photo-1524253482453-3fed8d2fe12b",   # video editing workstation
    "photo-1616401784845-180882ba9ba8",   # camera / video production gear
    "photo-1492619375914-88005aa9e8fb",   # video production multi-cam setup
    # Post-production & edit suites
    "photo-1535016120720-40c646be5580",   # video editing timeline on monitor
    "photo-1547658719-da2b51169166",      # multi-monitor edit workstation
    "photo-1605106702734-205df224ecce",   # VFX / tech screen
    "photo-1581092918056-0c4c3acd3789",   # tech lab equipment
    "photo-1611532736597-de2d4265fba3",   # broadcast / streaming setup
    # AI & technology
    "photo-1677442135703-1787eea5ce01",   # AI neural network visualization
    "photo-1620712943543-bcc4688e7485",   # AI / machine learning
    "photo-1593642632559-0c6d3fc62b89",   # circuit board close-up
    "photo-1518770660439-4636190af475",   # circuit board macro
    "photo-1515879218367-8466d910aaa4",   # code on dark screen
    # Network & infrastructure
    "photo-1545987796-200677ee1011",      # network fiber connections
    "photo-1551288049-bebda4e38f71",      # data analytics dashboard
    "photo-1504639725590-34d0984388bd",   # programming / code screen
    "photo-1516321497487-e288fb19713f",   # tech workspace monitors
    "photo-1497366754035-f200968a6e72",   # modern tech office
    # Streaming & media
    "photo-1586788680434-30d324b2d46f",   # live streaming / video
    "photo-1560472355-536de3962603",      # video / media content
    "photo-1561736778-92e52a7769ef",      # graphics workstation
    "photo-1516321318423-f06f85e504b3",   # monitoring screens
    "photo-1517694712202-14dd9538aa97",   # tech laptop workspace
]

def _unsplash_url(photo_id):
    return f"https://images.unsplash.com/{photo_id}?w=1200&auto=format&fit=crop&q=80"

def _is_bad_image(url):
    """Check if an image URL is in the blacklist."""
    if not url:
        return True
    return any(bad_id in url for bad_id in _BAD_IMAGE_IDS)

_POOL_IDS = set(_BROADCAST_IMAGES)

def _image_is_from_pool(url: str) -> bool:
    """True only if URL is an images.unsplash.com link to a pool photo ID."""
    if not url:
        return False
    if "images.unsplash.com" not in url:
        return False
    if "photo-" not in url:
        return False
    try:
        pid = "photo-" + url.split("photo-", 1)[1].split("?", 1)[0]
    except IndexError:
        return False
    return pid in _POOL_IDS

def _fix_article_images(arts):
    """Enforce broadcast-image policy across ALL article records.

    Copyright rule: third-party RSS thumbnails (TV Technology, Motionographer,
    Haivision, vendor PR photos, etc.) are never shipped on the live site.
    Every image_url must resolve to an entry in the curated _BROADCAST_IMAGES
    pool on images.unsplash.com, which Streamic licenses via Unsplash terms.

    Rules applied in order:
      1. Any non-pool image (RSS thumbnail, external CDN, vendor press photo,
         blacklisted ID, empty, or malformed) is replaced with a pool image.
      2. Any pool image already used in this run is replaced so the homepage
         and category pages never show the same visual twice in a row.
      3. Replacements are drawn round-robin from _BROADCAST_IMAGES for a
         stable, deterministic distribution across the ~35 visible slugs.
    """
    used_images = set()
    pool_idx = 0

    def _next_image():
        nonlocal pool_idx
        for _ in range(len(_BROADCAST_IMAGES)):
            img_id = _BROADCAST_IMAGES[pool_idx % len(_BROADCAST_IMAGES)]
            pool_idx += 1
            if img_id not in used_images:
                used_images.add(img_id)
                return _unsplash_url(img_id)
        # All pool IDs consumed — reset and continue round-robin.
        used_images.clear()
        img_id = _BROADCAST_IMAGES[pool_idx % len(_BROADCAST_IMAGES)]
        pool_idx += 1
        used_images.add(img_id)
        return _unsplash_url(img_id)

    replaced_non_pool = 0
    replaced_duplicate = 0
    taxonomy_applied = 0
    for a in arts:
        # PRIORITY 1: local taxonomy image from assign_images.py if present,
        # but only when the referenced file actually exists in docs/assets.
        # This prevents broken image boxes when the taxonomy script writes a
        # placeholder path but the corresponding local file has not been added.
        taxonomy_img = a.get("image") or ""
        if taxonomy_img and taxonomy_img.startswith("/assets/images/"):
            _rel = taxonomy_img.lstrip("/").replace("/", os.sep)
            _disk = os.path.join(DOCS, _rel)
            if os.path.exists(_disk):
                a["image_url"] = taxonomy_img
                a["image_credit"] = "The Streamic"
                a["image_license"] = "Site License"
                a["image_license_url"] = ""
                taxonomy_applied += 1
                continue

        img = a.get("image_url", "") or ""

        if not _image_is_from_pool(img):
            # Non-pool image (RSS/vendor/bad/empty) — force replacement.
            a["image_url"] = _next_image()
            # Attribution: pool images are Unsplash-licensed.
            a["image_credit"] = "Unsplash"
            a["image_license"] = "Unsplash License"
            a["image_license_url"] = "https://unsplash.com/license"
            replaced_non_pool += 1
            continue

        # Pool image — track uniqueness; replace if already used in this run.
        try:
            photo_id = "photo-" + img.split("photo-", 1)[1].split("?", 1)[0]
        except IndexError:
            photo_id = ""

        if photo_id and photo_id in used_images:
            a["image_url"] = _next_image()
            a["image_credit"] = "Unsplash"
            a["image_license"] = "Unsplash License"
            a["image_license_url"] = "https://unsplash.com/license"
            replaced_duplicate += 1
        elif photo_id:
            used_images.add(photo_id)

    total = replaced_non_pool + replaced_duplicate
    if total:
        print(f"  Image fixer: {total} images normalized to broadcast pool "
              f"({replaced_non_pool} non-pool/RSS, {replaced_duplicate} duplicates)")


def _hp_img(a, base=""):
    img = eu(a.get("image_url", "") or a.get("image", ""))
    if img:
        return img
    cat = (a.get("category") or "featured").lower()
    fallbacks = {
        "featured": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=1200&auto=format&fit=crop&q=80",
        "newsroom": "https://images.unsplash.com/photo-1598488035139-bdbb2231ce04?w=1200&auto=format&fit=crop&q=80",
        "cloud": "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?w=1200&auto=format&fit=crop&q=80",
        "infrastructure": "https://images.unsplash.com/photo-1545987796-200677ee1011?w=1200&auto=format&fit=crop&q=80",
        "graphics": "https://images.unsplash.com/photo-1547658719-da2b51169166?w=1200&auto=format&fit=crop&q=80",
        "streaming": "https://images.unsplash.com/photo-1598488035139-bdbb2231ce04?w=1200&auto=format&fit=crop&q=80",
        "ai-post-production": "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=1200&auto=format&fit=crop&q=80",
        "playout": "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=1200&auto=format&fit=crop&q=80",
    }
    return fallbacks.get(cat, fallbacks["featured"])

def _hp_tag(a):
    cinfo = CAT.get(a.get("category", "featured"), CAT["featured"])
    return f"{cinfo['icon']} {cinfo['label']}"

def _hp_insight_card(a):
    href = f"articles/{a['slug']}.html"
    title = e(a.get("title", ""))
    dek = e((a.get("dek") or a.get("meta_description") or a.get("card_summary") or "")[:150])
    dt = d(a.get("published", ""))
    return f'''<a href="{href}" class="hp-insight-card">
  <div class="hp-insight-media"><img src="{_hp_img(a)}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'"></div>
  <div class="hp-insight-body">
    <span class="hp-insight-tag">{e(_hp_tag(a))}</span>
    <span class="hp-insight-hl">{title}</span>
    <span class="hp-insight-dek">{dek}</span>
    <span class="hp-insight-meta">{dt}</span>
    <span class="hp-insight-read">Read analysis &#8594;</span>
  </div>
</a>'''

def _hp_guide_card(a, sub):
    href = f"articles/{a['slug']}.html"
    title = e(a.get("title", ""))
    return f'''<a href="{href}" class="hp-guide-card">
  <div class="hp-guide-card-img-wrap">
    <img src="{_hp_img(a)}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'">
    <span class="hp-guide-card-sub">{e(sub)}</span>
  </div>
  <div class="hp-guide-card-overlay">
    <span class="hp-guide-card-label">{title}</span>
  </div>
</a>'''


def _source_name(val):
    return (val or '').replace('https://','').replace('http://','').replace('www.','').split('/')[0]

def load_homepage_feed(arts, limit=14):
    """Use fresh data/news.json for homepage and map to internal articles.
    
    Only returns items that map to an internal article (has slug) so all
    homepage links go to our own analysis pages, never to external sources.
    Prefers articles with more body content (longer = higher quality).
    """
    by_url, by_title = {}, {}
    for a in arts:
        for key in (a.get('source_url'), a.get('url'), a.get('link')):
            if key:
                by_url[key] = a
        title = (a.get('title') or '').strip().lower()
        if title:
            by_title[title] = a

    feed_items = []
    if os.path.exists(NEWS_F):
        with open(NEWS_F, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        if isinstance(raw, dict) and 'items' in raw:
            feed_items = (raw.get('featured_priority') or []) + (raw.get('items') or [])
        elif isinstance(raw, list):
            feed_items = raw
        else:
            flat = []
            for cat, lst in (raw or {}).items():
                for it in (lst or []):
                    if isinstance(it, dict):
                        item = dict(it)
                        item.setdefault('category', cat)
                        flat.append(item)
            feed_items = sorted(flat, key=lambda x: x.get('pubDate',''), reverse=True)

    mapped = []
    seen = set()
    for item in feed_items:
        url = item.get('link') or item.get('url') or item.get('guid')
        title_key = (item.get('title') or '').strip().lower()
        art = by_url.get(url) or by_title.get(title_key)
        if not art or not art.get('slug'):
            continue  # skip items without internal article — no external links
        merged = dict(art)
        merged.update({
            'title': item.get('title') or merged.get('title',''),
            'category': item.get('category') or merged.get('category','featured'),
            'source_domain': item.get('source') or item.get('source_domain') or _source_name(url) or merged.get('source_domain',''),
            'published': item.get('pubDate') or item.get('published') or merged.get('published',''),
            'source_url': url or merged.get('source_url',''),
            'url': url or merged.get('url',''),
            # COPYRIGHT FIX: prefer the article's pool-normalized image_url
            # over the raw RSS thumbnail in news.json. The previous order
            # shipped copyrighted vendor PR photos into Breaking News,
            # bypassing _fix_article_images() entirely.
            'image_url': merged.get('image_url') or item.get('image') or '',
            'slug': art['slug'],
        })
        key = merged['slug']
        if key not in seen:
            seen.add(key)
            mapped.append(merged)

    # Sort: newest first, then by body length (prefer longer articles)
    def _feed_sort(a):
        body = a.get('body_html','') or ''
        wc = len(re.sub(r'<[^>]+>',' ',body).split())
        return (a.get('published',''), wc)
    mapped.sort(key=_feed_sort, reverse=True)

    if not mapped:
        mapped = sorted([a for a in arts if not a.get('is_editorial') and not a.get('editorial')], key=lambda a: a.get('published',''), reverse=True)[:limit]
    return mapped[:limit]

def _item_href(a):
    slug = a.get('slug')
    if slug:
        return f"articles/{slug}.html"
    return a.get('source_url') or a.get('url') or '#'

def _item_target(a):
    href = _item_href(a)
    if href.startswith('http://') or href.startswith('https://'):
        return ' target="_blank" rel="noopener noreferrer nofollow"'
    return ''

def _hp_news_item(a):
    slug = a.get("slug","")
    analysis_href = f"articles/{slug}.html" if slug else "#"
    src_url = e(a.get("source_url","") or a.get("url","") or "")
    title = e(a.get("title", ""))
    src = e(_source_name(a.get("source_domain", a.get("source", ""))))
    dt = d(a.get("published", ""))
    dek = e((a.get("dek") or a.get("card_summary") or a.get("meta_description") or "")[:120])
    # Source link — only if we have a real URL
    src_link = ""
    if src_url and src:
        src_link = f'<a href="{src_url}" target="_blank" rel="noopener noreferrer nofollow" class="hp-news-src-link">Source: {src} &#8599;</a>'
    return f'''<div class="hp-news-item">
  <div class="hp-news-thumb"><img src="{_hp_img(a)}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'"></div>
  <div class="hp-news-body">
    <span class="hp-news-src">{src}</span>
    <a href="{analysis_href}" class="hp-news-title">{title}</a>
    <span class="hp-news-dek">{dek}</span>
    <div class="hp-news-foot">
      <time class="hp-news-date">{dt}</time>
      <a href="{analysis_href}" class="hp-news-read">Read Streamic Analysis &#8594;</a>
    </div>
    {src_link}
  </div>
</div>'''
def _hp_sidebar_pick(a):
    href = f"articles/{a['slug']}.html"
    title = e(a.get("title", ""))
    return f'''<a href="{href}" class="hp-sb-img-card">
  <img src="{_hp_img(a)}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'">
  <div class="hp-sb-img-overlay"><span class="hp-sb-img-title">{title}</span></div>
</a>'''

def _hp_sidebar_news(a):
    slug = a.get("slug","")
    analysis_href = f"articles/{slug}.html" if slug else "#"
    src_url = e(a.get("source_url","") or a.get("url","") or "")
    title = e(a.get("title", ""))
    src = e(_source_name(a.get("source_domain", a.get("source", ""))))
    dt = d(a.get("published", ""))
    src_link = ""
    if src_url and src:
        src_link = f'<a href="{src_url}" target="_blank" rel="noopener noreferrer nofollow" style="font-size:10px;color:var(--ink4);text-decoration:none;margin-top:2px;display:block">Source: {src} &#8599;</a>'
    return f'''<div class="hp-sb-news-item">
  <div class="hp-sb-news-thumb"><img src="{_hp_img(a)}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'"></div>
  <div class="hp-sb-news-body">
    <span class="hp-sb-news-src">{src}</span>
    <a href="{analysis_href}" class="hp-sb-news-title">{title}</a>
    <time class="hp-sb-news-date">{dt}</time>
    {src_link}
  </div>
</div>'''
def featured_page(arts):
    """Homepage built from generated_articles.json with premium magazine layout."""
    editorial_all = sorted([a for a in arts if a.get("is_editorial") or a.get("editorial")], key=lambda a: a.get("published", ""), reverse=True)
    regular_all = sorted([a for a in arts if not a.get("is_editorial") and not a.get("editorial")], key=lambda a: a.get("published", ""), reverse=True)

    preferred_hero = "ai-reducing-broadcast-operational-costs-2026"
    hero_art = next((a for a in editorial_all if a.get("slug") == preferred_hero), editorial_all[0] if editorial_all else (regular_all[0] if regular_all else None))

    guide_slug_order = [
        "broadcast-automation-systems-guide-2026",
        "ip-broadcasting-smpte-st2110-engineering-guide-2026",
        "cloud-broadcast-workflows-remote-production-2026",
        "media-asset-management-ai-era-monetisation-2026",
    ]
    guide_map = {a.get("slug"): a for a in editorial_all}
    guide_arts = [guide_map[s] for s in guide_slug_order if s in guide_map]

    # ── Latest Insights: ALL quality articles, newest first ────────────
    #    Must be 400+ words + 2 broadcast terms (lower than the 800-word
    #    SEO gate so latest daily articles always appear on the homepage).
    #    Manual editorials bypass word count entirely.
    #    First 20 visible on load; rest behind "Load More" button.
    MIN_INSIGHT_WORDS = 400
    used_slugs = {a.get("slug") for a in guide_arts} | ({hero_art.get("slug")} if hero_art else set())
    # Merge editorial + regular into ONE list sorted by date (not editorial-first)
    insight_pool = sorted(
        [a for a in arts if a.get("slug") not in used_slugs],
        key=lambda a: a.get("published", ""), reverse=True
    )
    _seen_ins = set()
    insight_arts = []
    for a in insight_pool:
        s = a.get("slug")
        if not s or s in _seen_ins:
            continue
        # ── Quality gate: 400+ words (manual editorials bypass) ──
        _body = a.get("body_html", "") or ""
        _plain = re.sub(r"<[^>]+>", " ", _body)
        _wc = len(re.sub(r"\s+", " ", _plain).strip().split())
        is_manual_ed = a.get("generated_by") == "gpt_manual_editorial"
        if not is_manual_ed and _wc < MIN_INSIGHT_WORDS:
            continue
        # ── Broadcast relevance: 2+ terms ──
        _search = (a.get("title", "") + " " + _plain).lower()
        _hits = sum(1 for t in BROADCAST_TERMS if t in _search)
        if _hits < 2:
            continue
        _seen_ins.add(s)
        insight_arts.append(a)
    # No cap — all quality articles included

    sidebar_picks = [a for a in editorial_all if a.get("slug") != (hero_art or {}).get("slug")][:3]
    fresh_feed = load_homepage_feed(arts, limit=16)
    breaking_news = fresh_feed[:4]
    homepage_news = fresh_feed[4:12]
    if not homepage_news:
        homepage_news = fresh_feed[:8]

    title = "NAB Show 2026 Broadcast Technology Updates — The Streamic"
    desc = "Independent analysis of NAB Show 2026 announcements: Avid Content Core, Dalet Dalia AI, Telestream OCI, BCNEXXT Vipe HDR, and more. Expert broadcast engineering editorial."
    canon = f"{BASE_URL}/"
    schema = json.dumps({
        "@context": "https://schema.org", "@type": "WebPage",
        "name": "The Streamic", "description": desc, "url": f"{BASE_URL}/index.html",
        "publisher": {"@type": "Organization", "name": "The Streamic", "url": BASE_URL}
    })

    custom_hero_path = os.path.join(DOCS, 'assets', 'hero-broadcast-male.png')
    hero_img = f"{BASE_URL}/assets/hero-broadcast-male.png" if os.path.exists(custom_hero_path) else (_hp_img(hero_art) if hero_art else '')
    homepage_head = head(title, desc, canon, og_img=hero_img).replace('</head>', '  <link rel="stylesheet" href="homepage-layout.css">\n</head>')

    cinfo = CAT.get((hero_art or {}).get("category", "featured"), CAT["featured"])
    # Hero title overrides — edit here to control displayed title without touching JSON
    HERO_TITLE_OVERRIDES = {
        "ai-reducing-broadcast-operational-costs-2026": "Beyond Automation: How AI Can Optimize Broadcast Costs and Scale Human Potential in 2026",
    }

    hero_html = ""
    if hero_art:
        _hero_title = HERO_TITLE_OVERRIDES.get(hero_art.get("slug", ""), hero_art.get("title", ""))
        _hero_img_src = 'assets/hero-broadcast-male.png' if os.path.exists(custom_hero_path) else _hp_img(hero_art)
        _hero_img_alt = "Broadcast production switcher in a modern control room with illuminated buttons and blurred monitoring screens" if os.path.exists(custom_hero_path) else e(_hero_title)
        hero_html = f'''<section class="hp-hero" aria-label="Featured story">
  <a href="articles/{hero_art['slug']}.html" class="hp-hero-img-link" tabindex="-1" aria-hidden="true">
    <img class="hp-hero-img" src="{_hero_img_src}" alt="{_hero_img_alt}" loading="eager" onerror="this.onerror=null;this.src='assets/fallback.jpg'">
  </a>
  <div class="hp-hero-overlay" aria-hidden="true"></div>
  <div class="hp-hero-body">
    <span class="hp-hero-tag">{e(cinfo['icon'])} {e(cinfo['label'])}</span>
    <h1 class="hp-hero-hl"><a href="articles/{hero_art['slug']}.html">{e(_hero_title)}</a></h1>
    <div class="hp-hero-meta"><span>By {AUTHOR}</span><span>&#124;</span><span>{d(hero_art.get("published", ""))}</span><span>&#124;</span><span>{rm(hero_art.get("word_count", 1000))}</span></div>
    <a href="articles/{hero_art['slug']}.html" class="hp-hero-cta">View Analysis <span class="hp-hero-cta__arrow">→</span></a>
  </div>
</section>'''

    guide_subs = ["2026 Engineering Edition", "Complete Technical Reference", "Distributed Production Playbook", "Metadata, Search & Monetisation"]
    guides_html = ''.join(_hp_guide_card(a, guide_subs[i] if i < len(guide_subs) else "Technical Guide") for i, a in enumerate(guide_arts))
    # First 6 visible, rest hidden — revealed by Load More button
    INSIGHT_INITIAL = 20
    _insight_cards = []
    for i, a in enumerate(insight_arts):
        card_html = _hp_insight_card(a)
        if i >= INSIGHT_INITIAL:
            # Add hidden class to the <a> tag
            card_html = card_html.replace('class="hp-insight-card"', 'class="hp-insight-card hp-insight-hidden"', 1)
        _insight_cards.append(card_html)
    insights_html = ''.join(_insight_cards)
    # Load More — self-contained component (inline CSS + HTML + JS)
    _hidden_count = max(0, len(insight_arts) - INSIGHT_INITIAL)
    insights_loadmore = ""
    if _hidden_count > 0:
        insights_loadmore = f'''<style>
.hp-insight-hidden{{display:none!important}}
@keyframes insightReveal{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:translateY(0)}}}}
.hp-insight-reveal{{animation:insightReveal .4s cubic-bezier(.25,.46,.45,.94) both}}
.hp-lm-wrap{{display:flex;justify-content:center;padding:36px 0 12px}}
.hp-lm{{position:relative;display:inline-flex;align-items:center;gap:14px;padding:0;background:none;border:none;cursor:pointer;font-family:var(--font);-webkit-tap-highlight-color:transparent;outline:none}}
.hp-lm-ring{{position:relative;width:52px;height:52px;flex-shrink:0}}
.hp-lm-ring svg{{width:52px;height:52px;transform:rotate(-90deg)}}
.hp-lm-ring .ring-track{{fill:none;stroke:var(--line);stroke-width:2}}
.hp-lm-ring .ring-fill{{fill:none;stroke:var(--blue);stroke-width:2.5;stroke-linecap:round;stroke-dasharray:150;stroke-dashoffset:150;transition:stroke-dashoffset .6s cubic-bezier(.4,0,.2,1)}}
.hp-lm:hover .ring-fill{{stroke-dashoffset:0}}
.hp-lm-icon{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.hp-lm-icon svg{{width:18px;height:18px;stroke:var(--ink);stroke-width:2;fill:none;transition:transform .35s cubic-bezier(.4,0,.2,1),stroke .2s}}
.hp-lm:hover .hp-lm-icon svg{{transform:rotate(180deg);stroke:var(--blue)}}
.hp-lm-text{{display:flex;flex-direction:column;align-items:flex-start;gap:2px}}
.hp-lm-label{{font-size:14px;font-weight:600;color:var(--ink);letter-spacing:-.01em;transition:color .2s}}
.hp-lm:hover .hp-lm-label{{color:var(--blue)}}
.hp-lm-sub{{font-size:11px;font-weight:500;color:var(--ink4);transition:color .2s}}
.hp-lm:hover .hp-lm-sub{{color:var(--blue)}}
.hp-lm-bar{{position:absolute;bottom:-10px;left:0;width:100%;height:1.5px;background:var(--line);border-radius:2px;overflow:hidden}}
.hp-lm-bar span{{display:block;width:0;height:100%;background:var(--blue);border-radius:2px;transition:width .5s cubic-bezier(.4,0,.2,1)}}
.hp-lm:hover .hp-lm-bar span{{width:100%}}
</style>
<div class="hp-lm-wrap">
  <button id="insightLoadMore" type="button" class="hp-lm" aria-label="Load more insights">
    <div class="hp-lm-ring">
      <svg viewBox="0 0 52 52"><circle class="ring-track" cx="26" cy="26" r="24"/><circle class="ring-fill" cx="26" cy="26" r="24"/></svg>
      <div class="hp-lm-icon"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg></div>
    </div>
    <div class="hp-lm-text">
      <span class="hp-lm-label">Load More</span>
      <span class="hp-lm-sub" id="lmCount">{_hidden_count} more articles</span>
    </div>
    <div class="hp-lm-bar"><span></span></div>
  </button>
</div>
<script>
(function(){{
  var btn=document.getElementById('insightLoadMore'),B=6;
  if(!btn)return;
  btn.addEventListener('click',function(){{
    var h=document.querySelectorAll('.hp-insight-hidden'),c=0,i;
    for(i=0;i<h.length&&c<B;i++,c++){{h[i].classList.remove('hp-insight-hidden');h[i].classList.add('hp-insight-reveal');}}
    var left=document.querySelectorAll('.hp-insight-hidden').length;
    if(left<1)btn.parentElement.style.display='none';
    else document.getElementById('lmCount').textContent=left+' more articles';
  }});
}})();
</script>'''
    news_html = ''.join(_hp_news_item(a) for a in homepage_news)
    picks_html = ''.join(_hp_sidebar_pick(a) for a in sidebar_picks)
    sb_news_html = ''.join(_hp_sidebar_news(a) for a in breaking_news)
    howto_html = '''<div class="hp-sb-guides-grid">
          <a href="articles/guide-premiere-to-avid.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">Post-Production</span><span class="hp-sb-guide-title">Premiere Pro to Avid Media Composer</span><span class="hp-sb-guide-time">&#128337; 8 min</span></a>
          <a href="articles/guide-vantage-nas-transcode.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">Encoding</span><span class="hp-sb-guide-title">Vantage: Transcode to MP4 on NAS</span><span class="hp-sb-guide-time">&#128337; 6 min</span></a>
          <a href="articles/guide-vantage-aws-transcode.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">Cloud</span><span class="hp-sb-guide-title">Vantage: Output to AWS S3</span><span class="hp-sb-guide-time">&#128337; 6 min</span></a>
          <a href="articles/guide-avid-media-central-health-check.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">Avid</span><span class="hp-sb-guide-title">MediaCentral Health Check</span><span class="hp-sb-guide-time">&#128337; 7 min</span></a>
          <a href="articles/guide-audio-conform-avid-protools.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">Audio</span><span class="hp-sb-guide-title">Audio Conform: Avid to Pro Tools</span><span class="hp-sb-guide-time">&#128337; 9 min</span></a>
          <a href="articles/guide-avid-strawberry.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">MAM</span><span class="hp-sb-guide-title">Strawberry PAM + Avid Workflow</span><span class="hp-sb-guide-time">&#128337; 10 min</span></a>
        </div>'''

    return f'''{homepage_head}
<body data-category="featured">
{nav("/")}
<main>
  <div class="w">
    {hero_html}
    <section class="hp-flagship-section">
      <div class="w">
        <div class="hp-flagship-section__hdr">
          <div class="hp-sec-hdr">
            <h2>Latest Insights</h2>
            <a href="ai-post-production.html">View all &#8594;</a>
          </div>
          <p class="hp-section-intro">Original Streamic analysis on broadcast automation, IP infrastructure, cloud production, and editorial operations — selected for depth, not noise.</p>
        </div>
        <a href="articles/quic-http3-video-delivery-streaming-2026.html" class="hp-flagship" aria-label="Read full insight: Beyond TCP">
  <div class="hp-flagship__body">
    <div class="hp-flagship__eyebrow">
      <span class="hp-flagship__label">Latest Insight</span>
    </div>
    <span class="hp-flagship__tag">📡 Infrastructure &amp; Streaming</span>
    <h2 class="hp-flagship__hl">Beyond TCP: Why QUIC Is Redefining Video Delivery</h2>
    <p class="hp-flagship__summary">Faster video start, fewer buffering issues, and smoother playback — even on weak networks. HTTP/3 and QUIC are quietly improving streaming performance across OTT platforms and live broadcasting.</p>
    <p class="hp-flagship__body-text">For years, streaming relied on TCP — the same technology behind web browsing. It works, but it struggles with modern mobile and high-demand video traffic. QUIC improves this by enabling faster connections, better handling of network issues, and smoother playback — even when users switch between Wi-Fi and mobile networks.</p>
    <div class="hp-flagship__usecases">
      <div class="hp-flagship__usecase"><span class="hp-flagship__usecase-icon">🏟️</span><span><strong>Live Sports</strong> — smoother playback during peak traffic moments</span></div>
      <div class="hp-flagship__usecase"><span class="hp-flagship__usecase-icon">📺</span><span><strong>OTT Platforms</strong> — faster video start reduces viewer drop-off</span></div>
      <div class="hp-flagship__usecase"><span class="hp-flagship__usecase-icon">📱</span><span><strong>Mobile Viewing</strong> — stable playback when switching networks</span></div>
      <div class="hp-flagship__usecase"><span class="hp-flagship__usecase-icon">⚡</span><span><strong>Live Events</strong> — lower latency for near real-time streaming</span></div>
    </div>
    <div class="hp-flagship__footer">
      <div class="hp-flagship__meta">
        <span class="hp-flagship__author">Prerak K Mehta</span>
        <span class="hp-flagship__role">Broadcast Technology and Media IT Analyst</span>
        <span class="hp-flagship__readtime">⏱ 5 min read</span>
      </div>
      <span class="hp-flagship__cta">Read Full Insight <span class="hp-flagship__cta-arrow">→</span></span>
    </div>
  </div>
  <div class="hp-flagship__image-wrap">
    <img class="hp-flagship__img" src="assets/insight-quic-infographic.jpg" alt="QUIC vs TCP: streaming performance comparison infographic" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'">
  </div>
</a>
      </div>
    </section>
    {_nab_bento_section()}
    <div class="hp-outer">
      <div class="hp-main">
        <section class="hp-insights hp-insights-premium">
          <div class="hp-insights-grid">{insights_html}</div>
          {insights_loadmore}
        </section>
        <section class="hp-guide">
          <div class="hp-guide-banner"><span>Professional Media Systems Guide</span></div>
          <div class="hp-guide-grid">{guides_html}</div>
        </section>
        <section class="hp-news">
          <div class="hp-sec-hdr"><h2>The Streamic Intelligence</h2><p class="hp-sec-sub">In-depth coverage of playout, MAM/PAM, archive, cloud production, Adobe workflows, SMPTE standards, and AI-driven media operations.</p></div>
          <div class="hp-news-list">{news_html}</div>
        </section>
      </div>
      <aside class="hp-sidebar" aria-label="Sidebar">
        <div class="hp-sb-section hp-sb-featured">
          <div class="hp-sb-hdr">Editor&#8217;s Picks <a href="editorsdesk.html" class="hp-sb-hdr-link">View page &#8594;</a></div>
          {picks_html}
        </div>
        <div class="hp-sb-section">
          <div class="hp-sb-hdr">How-To Guides <a href="howto.html" class="hp-sb-hdr-link">View all &#8594;</a></div>
          {howto_html}
        </div>
        <div class="hp-sb-section">
          <div class="hp-sb-hdr">Breaking Media Tech News</div>
          {sb_news_html}
        </div>
      </aside>
    </div>
  </div>
</main>
<script type="application/ld+json">{schema}</script>
{footer()}
{_cookie_banner()}
<script src="main.js" defer></script>
</body>
</html>'''

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
    # Rest: news grid with source diversity
    editorial = [a for a in arts if a.get("is_editorial") or a.get("editorial")]
    regular   = [a for a in arts if not a.get("is_editorial") and not a.get("editorial")]
    # Sort regular by date then diversify
    regular.sort(key=lambda a: a.get("published",""), reverse=True)
    regular = diversify_arts(regular)
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
        grid_html = news_grid(rest, grid_id="catGrid") if rest else ""

        pag = _pag_html(cat, pg, total_pages)

        pg_title = title_base if pg==0 else f"{title_base} — Page {pg+1}"
        cinfo_icon = cinfo.get('icon','')
        cinfo_label = cinfo.get('label','')
        pg_canon = canon if pg==0 else f"{BASE_URL}/{cat}-p{pg+1}.html"
        pg_robots = "index,follow" if pg==0 else "noindex,follow"

        latest_section = f'<section class="latest">{grid_html}</section>' if grid_html else ""
        html = f"""{head(pg_title, desc, pg_canon, og_img=(first[0].get('image_url','') if first else ''), robots=pg_robots)}
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
    Return clean article body for rendering.

    Anti-truncation rule:
    - If body_html has <h2> OR word_count > 300 → return the FULL body_html untouched.
      Gemini-generated articles are complete. Truncating them strips the analysis.
    - Fallback: only strip/limit for raw RSS teasers with no AI enhancement.
    """
    is_ed = a.get("is_editorial") or a.get("editorial")

    # ── Full editorial articles — always return complete body ─────────────
    if is_ed:
        body = a.get("body_html", "")
        if body and len(body) > 300:
            return body

    body_html  = a.get("body_html", "") or ""
    word_count = a.get("word_count", 0)
    # Also check actual body length — metadata word_count may be missing
    actual_wc  = len(re.sub(r"<[^>]+>", " ", body_html).split())

    # ── AI-enhanced articles: has h2 structure OR substantial word count ──
    # Return the full body without ANY stripping — Gemini output is complete.
    if "<h2>" in body_html or "<h3>" in body_html or word_count > 300 or actual_wc > 300:
        # Only strip accidental markdown fences Gemini occasionally produces
        body_clean = re.sub(r"```html?\n?|```\n?", "", body_html).strip()
        # Remove boilerplate filler sentences while keeping all structure
        paras = re.findall(r"<p[^>]*>(.*?)</p>", body_clean, re.DOTALL)
        clean_paras = []
        for p in paras:
            txt = re.sub(r"<[^>]+>", " ", p).strip()
            txt = re.sub(r"\s+", " ", txt)
            if len(txt.split()) < 5:
                continue   # skip truly empty placeholders
            if _is_boilerplate(txt):
                continue   # strip known filler sentences
            clean_paras.append(p)
        # Reconstruct: non-paragraph blocks (h2, h3, ul, ol, table, div) pass through untouched
        # Strategy: replace only the <p> tags we cleaned, keep everything else
        result = body_clean
        for orig_p, clean_p in zip(paras, clean_paras):
            pass  # we'll use a simpler approach below
        # Simpler: just strip boilerplate paragraphs from the full HTML
        for p_content in paras:
            txt = re.sub(r"<[^>]+>", " ", p_content).strip()
            txt = re.sub(r"\s+", " ", txt)
            if _is_boilerplate(txt):
                result = result.replace(f"<p>{p_content}</p>", "", 1)
                result = result.replace(f"<p>{p_content.strip()}</p>", "", 1)
        return result.strip() or body_clean

    # ── Fallback: raw RSS teaser with no AI enhancement ───────────────────
    # card_summary is the Groq/Gemini 120-150 word intel card — show it in full
    cs_raw = re.sub(r"<[^>]+>", " ", a.get("card_summary", "") or "").strip()
    cs_raw = re.sub(r"\s+", " ", cs_raw)
    cs_words = cs_raw.split()

    if len(cs_words) >= 50 and not _is_boilerplate(cs_raw):
        mid = len(cs_words) // 2
        for i in range(mid, min(mid + 25, len(cs_words))):
            if cs_words[i].endswith((".", "?")): mid = i + 1; break
        p1 = " ".join(cs_words[:mid])
        p2 = " ".join(cs_words[mid:])
        return f"<p>{p1}</p>\n" + (f"<p>{p2}</p>" if p2 else "")

    # Raw paragraphs — keep ALL that pass quality check (no arbitrary limit)
    paras = re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.DOTALL)
    clean = []
    for p in paras:
        txt = re.sub(r"<[^>]+>", " ", p).strip()
        txt = re.sub(r"\s+", " ", txt)
        if len(txt.split()) < 8: continue
        if _is_boilerplate(txt): continue
        clean.append(f"<p>{p.strip()}</p>")

    if clean:
        return "\n".join(clean)   # no truncation — article passed quality gate

    # Last resort: dek + short teaser
    dek    = (a.get("dek") or "").strip()
    teaser = (a.get("meta_description") or a.get("teaser") or "").strip()
    parts  = []
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

    # Clean body - card_summary as 2-para analysis (not boilerplate filler)
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
    source_banner = ""
    # Derive source domain from URL if field is missing
    if not src_dom and src_url:
        src_dom = src_url.replace("https://","").replace("http://","").replace("www.","").split("/")[0]
    # Show source attribution for ALL articles with a source_url,
    # EXCEPT truly hand-written editorials (gpt_manual_editorial).
    # rewrite_feed_local articles have is_editorial=True but ARE sourced from news.
    _is_original = a.get("generated_by") == "gpt_manual_editorial"
    if src_url and not _is_original:
        _src_name = e(src_dom) if src_dom else "Original Source"
        _pub_date = a.get("published","")
        _pub_month = ""
        if _pub_date:
            try:
                from datetime import datetime as _dt
                _pub_month = _dt.strptime(_pub_date, "%Y-%m-%d").strftime("%B %Y")
            except Exception:
                _pub_month = _pub_date

        # ── TOP: Source attribution banner ──
        source_banner = f"""<div style="background:#f0f4ff;border:1px solid #d0daf0;border-radius:10px;padding:16px 20px;margin-bottom:28px;font-size:13.5px;color:var(--ink2);line-height:1.6">
  <span style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:1px;color:var(--blue);display:block;margin-bottom:6px">Source Attribution</span>
  This analysis is based on publicly available reporting from:
  <strong style="color:var(--ink)"><a href="{e(src_url)}" target="_blank" rel="noopener noreferrer nofollow" style="color:var(--blue);text-decoration:none">{_src_name}</a></strong>{f" ({_pub_month})" if _pub_month else ""}.
  <br>This article provides independent technical interpretation by The Streamic.
</div>"""

        # ── BOTTOM: Sources & Further Reading ──
        source_credit = f"""<div style="background:var(--bg);border-radius:12px;padding:22px 24px;margin-top:36px;border-top:3px solid var(--blue)">
  <h4 style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:1px;color:var(--blue);margin:0 0 14px">Sources &amp; Further Reading</h4>
  <ul style="margin:0;padding-left:18px;list-style:disc">
    <li style="font-size:13.5px;color:var(--ink2);line-height:1.6;margin-bottom:6px">
      <strong style="color:var(--ink)">{_src_name}</strong> &mdash;
      <a href="{e(src_url)}" target="_blank" rel="noopener noreferrer nofollow" style="color:var(--blue);text-decoration:none">Read the original article &rarr;</a>
    </li>
  </ul>
  <p style="margin:12px 0 0;font-size:12px;color:var(--ink4);line-height:1.5">
    The Streamic provides independent editorial commentary. All source material is credited and linked above. External links carry <code style="font-size:11px;background:#e8e8ed;padding:1px 5px;border-radius:3px">rel="nofollow noopener"</code>.
  </p>
</div>"""

    about_txt = "Original analysis and commentary by The Streamic Editorial Team. Independent broadcast technology journalism for engineers and media professionals." if is_ed else "Editorial commentary and analysis by The Streamic Editorial Team. For the original source, see the attribution above."
    # Use professional bio block if body_html already contains one from AI generation;
    # otherwise render the default author box for editorial articles and the bio for RSS-sourced ones.
    has_bio = "art-author-bio" in body_raw
    if has_bio:
        author_box = ""   # bio already embedded in body_html by the AI prompt
    elif is_ed:
        author_box = f"""<div class="art-author">
  <strong>About this article</strong>
  {about_txt}
  <a href="/about.html" style="color:var(--blue);margin-left:6px;">About The Streamic &rarr;</a>
</div>"""
    else:
        author_box = f"""<div class="art-author-bio">
  <div class="bio-avatar">S</div>
  <div class="bio-body">
    <strong class="bio-name">Prerak K Mehta</strong>
    <span class="bio-title">Founder, The Streamic &middot; Dublin, Ireland</span>
    <p class="bio-text">Broadcast technology professional with total 25+ years of IT and 20 years of Media/Post Production &amp; Broadcast IT systems experience. He covers broadcast engineering, streaming, infrastructure, and media technology trends for The Streamic.</p>
  </div>
</div>"""

    # ── Editor's Note with generated_by attribution (AdSense transparency) ──
    gen_by    = a.get("generated_by", "") or ""
    gen_label = {
        "gemini-2.5-pro":       "Gemini 2.5 Pro (Google)",
        "gemini-2.5-flash-lite":"Gemini 2.5 Flash-Lite (Google)",
        "groq-fallback":        "Groq / Llama (fallback)",
    }.get(gen_by, gen_by if gen_by else "AI-assisted")

    if is_ed:
        editors_note = ""
    else:
        editors_note = (
            '<hr style="margin-top:40px;border:0;border-top:1px solid #eee;">'
            '<p style="font-style:italic;font-size:0.85rem;color:#666;line-height:1.5;margin-top:20px;">'
            '<strong>Editor&#39;s Note:</strong> This technical analysis was synthesised from '
            'industry sources and constructed with the assistance of AI tools '
            f'(<strong>{gen_label}</strong>). '
            'It has been reviewed and formatted by <strong>The Streamic Editorial Team</strong> '
            'to ensure accuracy and relevance for broadcast professionals.'
            '</p>'
        )
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
    <p class="art-dek">{dek.replace(chr(60),"&lt;").replace(chr(62),"&gt;")}</p>
    <div class="art-byline">
      <strong>{AUTHOR}</strong>
      <time datetime="{a.get("published","")}" style="color:var(--ink4);font-size:13px">{dt}</time>
      <span>{wc:,} words · {rm(wc)}</span>
      {analysis_badge}
    </div>
    <figure>
      <img src="{eu(img)}" alt="{e(title)}" loading="eager">
      <figcaption>{e(a.get("image_credit","Photo via Unsplash &#8212; free to use under the Unsplash License"))} &#8212; <a href="{lic_url}" rel="nofollow noopener" target="_blank" style="color:var(--ink4)">{lic_label}</a></figcaption>
    </figure>
    <div class="art-body">{source_banner}{body}{editors_note}</div>
    {source_credit}
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
<main><div class="w" style="padding:52px 24px 80px;max-width:780px">
<h1 style="font-family:var(--serif);font-size:clamp(28px,4vw,44px);margin-bottom:16px;letter-spacing:-.5px">About The Streamic</h1>
<p style="font-size:17px;color:var(--ink2);line-height:1.65;margin-bottom:20px">The Streamic is an independent broadcast and streaming technology publication covering the tools, standards, and workflows that shape modern media production and delivery. Published from Dublin, Ireland, we focus on the engineering reality behind the marketing &#8212; what actually ships, what actually works, and what broadcast teams actually need to verify before they deploy.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:20px">Our coverage spans IP infrastructure (SMPTE ST 2110, NMOS IS-04/IS-05, AES67, SCTE-35), cloud-native production, operational AI in newsroom and post workflows, real-time graphics, playout automation, MAM / PAM integration, and disaster-recovery architectures. Readers include broadcast engineers, media operations leads, technology directors, post-production supervisors, and broadcast IT architects at networks, streamers, and production facilities worldwide.</p>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">Our editorial approach</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:16px">We write original analysis &#8212; not copied content, not press-release rewrites. Our industry news coverage credits and links to original reporting while adding Streamic editorial context: what the announcement actually means for an integration, what specifications are missing, and what deployment factors teams must verify before they commit capex. Long-form articles represent our editorial team&#39;s independent perspective on industry developments.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:16px">Every technical article is grounded in verifiable source material. Where a vendor has not disclosed a specification, we say so explicitly rather than inventing detail. Where two sources conflict, we note the discrepancy. This is the editorial discipline that separates broadcast trade journalism from marketing re-circulation.</p>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">What we cover</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:12px">Day-to-day Streamic coverage falls into five practice areas:</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li><strong>Infrastructure &amp; standards</strong> &#8212; ST 2110 rollouts, NMOS deployments, PTP timing, IP fabric design, SDI-to-IP migration roadmaps.</li>
  <li><strong>Cloud &amp; hybrid production</strong> &#8212; remote production (REMI), cloud playout, CDN architecture, egress cost optimisation, edge media services.</li>
  <li><strong>AI in broadcasting</strong> &#8212; automated captioning and QC, metadata extraction, newsroom AI, AI-assisted editing, generative tools for post.</li>
  <li><strong>Post-production workflows</strong> &#8212; Media Composer / Resolve / Premiere interoperability, PAM / MAM integration, proxy pipelines, archive strategies.</li>
  <li><strong>Newsroom technology</strong> &#8212; NRCS platforms, MOS integration, rundown automation, social-media ingest, fast-turn graphics.</li>
</ul>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">Editor &amp; Founder</h2>
<div style="display:flex;align-items:flex-start;gap:20px;background:var(--bg);border-radius:14px;padding:24px;margin-bottom:28px">
  <div style="flex-shrink:0;width:56px;height:56px;border-radius:50%;background:var(--blue);display:flex;align-items:center;justify-content:center;font-size:22px;color:#fff;font-family:var(--serif)">P</div>
  <div>
    <strong style="font-size:16px;color:var(--ink)">Prerak K Mehta</strong>
    <p style="font-size:13px;color:var(--ink4);margin:2px 0 8px">Founder &amp; Editor-in-Chief, The Streamic · Dublin, Ireland</p>
    <p style="font-size:14px;color:var(--ink3);line-height:1.7;margin:0">Broadcast technology professional with total 25+ years of IT and 20 years of Media/Post Production &amp; Broadcast IT systems experience. He covers broadcast engineering, streaming, infrastructure, and media technology trends for The Streamic.</p>
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
<main><div class="w" style="padding:52px 24px 80px;max-width:680px">
<h1 style="font-family:var(--serif);font-size:clamp(28px,4vw,40px);margin-bottom:8px">Contact</h1>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:24px">We welcome editorial feedback, story tips, corrections, and advertising enquiries from broadcast engineers, vendors, and media technology professionals. Our Dublin-based editorial team responds to genuine enquiries within two working days.</p>

<h2 style="font-family:var(--serif);font-size:20px;margin:24px 0 10px">What to expect</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Every message is read by the editorial team. Story tips and corrections are prioritised. Press releases are considered for coverage when they align with our practice areas (infrastructure, cloud production, AI in broadcasting, post-production workflows, newsroom technology). We do not publish paid-placement articles, syndicated content, or sponsored posts disguised as editorial. We will not reply to generic SEO link-building requests, guest-post pitches from content farms, or mass outreach unrelated to broadcast technology.</p>

<h2 style="font-family:var(--serif);font-size:20px;margin:24px 0 10px">Editorial enquiries</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Have a story tip or seen something we should cover? Email us directly with a short description and any relevant links. Broadcast engineers, integration teams, and vendor technical staff often see announcements, standards drafts, or operational incidents worth flagging before the wider trade press picks them up &#8212; we value these tips and protect sources on request.</p>

<h2 style="font-family:var(--serif);font-size:20px;margin:24px 0 10px">Press &amp; vendor enquiries</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">For product announcements, roadmap updates, or briefings, please include: (a) a one-paragraph summary of what is being announced, (b) any relevant technical specifications (codecs, protocols, standards compliance), (c) the embargo date if any, and (d) the best technical contact for follow-up questions. We write for broadcast engineers, so marketing-led pitches without technical substance rarely convert to coverage.</p>

<h2 style="font-family:var(--serif);font-size:20px;margin:24px 0 10px">Corrections</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:24px">If you spot a factual error in a published article &#8212; an incorrect specification, a misidentified product category, a missing standards reference &#8212; please let us know. Include the article URL and the specific correction. Significant factual corrections are acknowledged inline on the corrected article, consistent with our <a href="editorial-policy.html" style="color:var(--blue)">Editorial Policy</a>.</p>

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
<form action="https://formsubmit.co/technodate3@gmail.com" method="POST" style="display:flex;flex-direction:column;gap:16px">
  <input type="hidden" name="_subject" value="New contact form enquiry from The Streamic">
  <input type="hidden" name="_template" value="table">
  <input type="hidden" name="_next" value="https://www.thestreamic.in/contact.html?sent=1">
  <input type="text" name="_honey" style="display:none" tabindex="-1" autocomplete="off">
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
    <input id="cf-subject" type="text" name="topic" placeholder="Editorial feedback / Story tip / Advertising"
      style="width:100%;padding:10px 14px;border:1px solid var(--line);border-radius:8px;font-size:14px;color:var(--ink);background:#fff;box-sizing:border-box">
  </div>
  <div>
    <label for="cf-message" style="display:block;font-size:13px;font-weight:600;color:var(--ink);margin-bottom:6px">Message</label>
    <textarea id="cf-message" name="message" required rows="5" placeholder="Your message..."
      style="width:100%;padding:10px 14px;border:1px solid var(--line);border-radius:8px;font-size:14px;color:var(--ink);background:#fff;box-sizing:border-box;resize:vertical"></textarea>
  </div>
  <button type="submit"
    style="align-self:flex-start;padding:11px 28px;background:var(--blue);color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;transition:background .15s ease">
    Send Message
  </button>
</form>
<p style="font-size:12px;color:var(--ink4);margin-top:14px;line-height:1.6">On first use, FormSubmit sends a one-time activation email to <strong>technodate3@gmail.com</strong>. After you confirm it once, future submissions go directly to your inbox.</p>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def privacy_page():
    yr = datetime.now().year
    return f"""{head("Privacy Policy — The Streamic","Privacy Policy for thestreamic.in",f"{BASE_URL}/privacy.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 24px 80px;max-width:760px">
<h1 style="font-family:var(--serif);font-size:clamp(24px,4vw,38px);margin-bottom:20px">Privacy Policy</h1>
<p style="font-size:12px;color:var(--ink4);margin-bottom:28px">Last updated: March 2026</p>
<div style="font-size:15px;color:var(--ink3);line-height:1.75">
<p style="margin-bottom:16px">This Privacy Policy explains how The Streamic (&quot;we&quot;, &quot;us&quot;, &quot;our&quot;) collects, uses, and protects information when you visit thestreamic.in. We respect your privacy and are committed to processing any personal data lawfully and transparently under the UK GDPR, EU GDPR, and Irish Data Protection Act 2018.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">What information we collect</h2>
<p style="margin-bottom:16px">We collect a minimal set of information necessary to operate the site and understand how visitors use it:</p>
<ul style="padding-left:22px;line-height:1.9;margin-bottom:16px">
  <li><strong>Analytics data</strong> &#8212; anonymised page views, session duration, referrer, approximate city-level geography, device type, and browser. Collected only if you accept analytics cookies.</li>
  <li><strong>Contact form submissions</strong> &#8212; if you choose to email us or submit the contact form, we receive your email address and the content of your message. We use this solely to reply to your enquiry.</li>
  <li><strong>Advertising data</strong> &#8212; processed by Google AdSense under their own privacy policy. We do not receive personally identifiable advertising data.</li>
</ul>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Cookies and Analytics</h2>
<p style="margin-bottom:16px">We use Google Analytics (GA4) to understand how visitors use our site &#8212; which articles are read, how readers arrive (search, social, direct), and which pages load slowly. Analytics cookies are only placed after you click &quot;Accept all&quot; on our cookie banner. Until you consent, no analytics cookies are set and no data is collected. You can withdraw consent at any time by clearing your browser cookies, using the browser&#39;s privacy controls, or using a GA4 opt-out browser extension.</p>
<p style="margin-bottom:16px">We do not use cross-site tracking cookies, fingerprinting, session replay, or third-party analytics beyond Google Analytics and AdSense.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Advertising</h2>
<p style="margin-bottom:16px">We display advertisements via Google AdSense (publisher ID: {ADS}). Google may use cookies to show you personalised ads based on your browsing history across sites that use Google&#39;s ad services. You can opt out of personalised advertising at <a href="https://adssettings.google.com" rel="nofollow" style="color:var(--blue)">adssettings.google.com</a>. Google&#39;s use of advertising cookies is governed by their <a href="https://policies.google.com/technologies/ads" rel="nofollow" style="color:var(--blue)">advertising policies</a>.</p>
<p style="margin-bottom:16px">If you prefer to see non-personalised ads, your browser or device may offer a &quot;Limit Ad Tracking&quot; setting. Google AdSense honours these signals where technically possible.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Data we do not collect</h2>
<p style="margin-bottom:16px">We do not collect names, postal addresses, phone numbers, payment details, or other personal data unless you voluntarily provide it by contacting us directly. We do not sell, rent, or trade any data we hold. We do not maintain a marketing mailing list.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Your rights under GDPR</h2>
<p style="margin-bottom:16px">If you are located in the UK or EU, you have the right to access, rectify, erase, restrict, or object to the processing of any personal data we hold about you. To exercise any of these rights, email <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a>. We will respond within 30 days. You also have the right to lodge a complaint with the Irish Data Protection Commission at <a href="https://www.dataprotection.ie" rel="nofollow" style="color:var(--blue)">dataprotection.ie</a>.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Data retention</h2>
<p style="margin-bottom:16px">Analytics data is retained for up to 14 months as configured in Google Analytics 4. Email correspondence is retained for as long as is reasonably necessary to handle the enquiry, typically no more than 24 months.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Changes to this policy</h2>
<p style="margin-bottom:16px">We may update this Privacy Policy to reflect changes to our data processing practices or to comply with new regulatory requirements. Substantive changes will be noted at the top of this page with an updated &quot;last modified&quot; date.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Contact</h2>
<p>Privacy queries, data access requests, or correction requests: <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a></p>
</div>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def terms_page():
    return f"""{head("Terms of Use — The Streamic","Terms of Use for thestreamic.in",f"{BASE_URL}/terms.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 24px 80px;max-width:760px">
<h1 style="font-family:var(--serif);font-size:clamp(24px,4vw,38px);margin-bottom:20px">Terms of Use</h1>
<p style="font-size:12px;color:var(--ink4);margin-bottom:28px">Last updated: March 2026</p>
<div style="font-size:15px;color:var(--ink3);line-height:1.75">
<p style="margin-bottom:16px">By accessing thestreamic.in, browsing articles, using our contact form, or interacting with the site in any way, you agree to these Terms of Use. If you do not agree with any part of these terms, please do not use the site. These terms are governed by the laws of Ireland. Any dispute arising from use of the site is subject to the exclusive jurisdiction of the courts of Ireland.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Use of the site</h2>
<p style="margin-bottom:16px">You are granted a limited, non-exclusive, non-transferable licence to access and view the content on thestreamic.in for personal and professional reference purposes. Automated scraping, large-scale content harvesting, or use of the site to train AI models without express written permission is prohibited. You may not attempt to gain unauthorised access to any part of the site, its servers, or any connected systems.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Content ownership</h2>
<p style="margin-bottom:16px">Original editorial content on The Streamic &#8212; including article text, headlines, data visualisations, and editorial analysis &#8212; is copyright &copy; The Streamic. All rights reserved. You may quote short excerpts with attribution and a link back to the original article, consistent with standard journalistic practice. You may not republish, mirror, or redistribute full articles without written permission.</p>
<p style="margin-bottom:16px">Industry news briefings credit and link to their original sources. Where we quote or summarise a third-party press release or vendor announcement, we do so under standard journalistic fair-dealing principles. All third-party trademarks, product names, and logos are the property of their respective owners.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Editorial disclaimer</h2>
<p style="margin-bottom:16px">Content on The Streamic is provided for informational and educational purposes only. While we take reasonable care to ensure accuracy, we make no warranties &#8212; express or implied &#8212; regarding the completeness, timeliness, or reliability of any article. Technical specifications, product capabilities, and vendor roadmaps change over time; always verify critical integration details directly with the manufacturer before making purchasing or architectural decisions.</p>
<p style="margin-bottom:16px">Articles should not be construed as professional advice. The Streamic is not responsible for business decisions made based solely on our editorial content.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">External Links</h2>
<p style="margin-bottom:16px">We link to external sources &#8212; vendor websites, news publications, standards bodies &#8212; using <code>rel=&quot;nofollow noopener noreferrer&quot;</code> where appropriate. We are not responsible for the content, availability, privacy practices, or terms of service of any linked website. Inclusion of an external link does not constitute endorsement.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">User conduct</h2>
<p style="margin-bottom:16px">When contacting us via email or the contact form, you agree not to send abusive, threatening, defamatory, or unlawful messages. We reserve the right to ignore or report communications that violate these conditions. Spam, promotional pitches unrelated to editorial topics, and SEO-link-building requests will not receive a reply.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Availability</h2>
<p style="margin-bottom:16px">We aim to keep thestreamic.in available at all times but make no warranty of continuous availability. The site may be unavailable during maintenance, migration, or due to factors beyond our control (CDN outages, DNS issues, hosting-provider incidents). We are not liable for any loss arising from site unavailability.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Changes to these terms</h2>
<p style="margin-bottom:16px">We may update these Terms of Use from time to time. Continued use of the site after changes are published constitutes acceptance of the revised terms. Substantive changes will be noted at the top of this page with an updated &quot;last modified&quot; date.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Contact</h2>
<p style="margin-bottom:16px">For questions about these Terms, please email <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a>.</p>
</div>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def editorial_policy_page():
    yr = datetime.now().year
    return f"""{head("Editorial Policy — The Streamic","How The Streamic produces, reviews, and attributes broadcast technology content.",f"{BASE_URL}/editorial-policy.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 24px 80px;max-width:780px">
<h1 style="font-family:var(--serif);font-size:clamp(26px,4vw,42px);margin-bottom:16px;letter-spacing:-.5px">Editorial Policy</h1>
<p style="font-size:13px;color:var(--ink4);margin-bottom:32px">Last updated: {yr}</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:0 0 12px">Our Editorial Mission</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">The Streamic is an independent broadcast and streaming technology publication. Our mission is to provide clear, practical analysis for broadcast engineers, media operations teams, and streaming professionals — not press release rewrites, and not generic AI summaries.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">How We Use AI Tools</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Some articles on The Streamic are produced with the assistance of AI language models (Google Gemini and Groq/Llama). These tools are used to:</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li>Draft initial analysis from source-grounded industry news</li>
  <li>Identify domain-specific technical signals and implications</li>
  <li>Structure content into our editorial framework (domain extraction, technology intelligence, engineering takeaways)</li>
</ul>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">AI-generated drafts are reviewed against our quality standards. Articles that pass a minimum word count, structural depth, and domain terminology threshold are published. Those that do not are regenerated or withheld.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Human Review Process</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">All published editorial content is reviewed by Prerak K Mehta, Founder and Editor-in-Chief, or a designated editorial team member. Review covers factual accuracy relative to the source material, domain relevance, and tone. Articles found to contain generic or misleading content are not published.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Source Attribution</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">Industry news briefings always credit and link to their original source. We do not reproduce original articles verbatim. All external links to source material carry <code>rel="nofollow noopener"</code>. Source-grounded briefs are differentiated from original long-form editorial analysis.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Corrections Policy</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">We correct factual errors promptly. If you identify an error, please contact us at <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a> with the article URL and the specific correction. Significant corrections are noted inline on the article.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Independence &amp; Advertising</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">The Streamic is independently owned. Advertising (served via Google AdSense) does not influence editorial decisions. We do not accept sponsored articles or paid coverage. Vendor mentions reflect genuine editorial relevance, not commercial arrangements.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Contact the Editor</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75">Editorial enquiries, corrections, and feedback: <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a> &nbsp;|&nbsp; <a href="contact.html" style="color:var(--blue)">Use our contact form &rarr;</a></p>

</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def insights_page():
    """Expert Insights landing page — AdSense-compliant substantive content (~650w)."""
    return f"""{head("Expert Insights — The Streamic","Long-form broadcast technology analysis: ST 2110 rollouts, cloud production, AI in broadcasting, and operational engineering for media teams.",f"{BASE_URL}/insights.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 24px 80px;max-width:820px">
<h1 style="font-family:var(--serif);font-size:clamp(28px,4vw,44px);margin-bottom:16px;letter-spacing:-.5px">Expert Insights</h1>
<p style="font-size:17px;color:var(--ink2);line-height:1.65;margin-bottom:24px">Long-form broadcast and media technology analysis from the Streamic editorial team. These are the pieces we write when a topic needs more than a news briefing &#8212; standards deep-dives, architectural playbooks, vendor-neutral integration patterns, and field reports from broadcast engineers working in live production and post facilities.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">What Expert Insights covers</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Expert Insights articles are written for broadcast engineers, technology directors, and media operations leads who need to evaluate &#8212; not just read about &#8212; new technology. Every piece is grounded in verifiable source material, quotes technical specifications accurately, and calls out what vendors have not disclosed. Topics we return to repeatedly:</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li><strong>IP infrastructure deep-dives</strong> &#8212; SMPTE ST 2110 rollouts, NMOS IS-04 / IS-05 registry patterns, AES67 audio-over-IP, PTP timing validation, redundant media networks, and migration strategies from SDI to IP.</li>
  <li><strong>Cloud production &amp; playout</strong> &#8212; REMI architectures, cloud-based channel origination, CDN strategies, egress cost management, edge media caching, and multi-region disaster-recovery models.</li>
  <li><strong>Operational AI</strong> &#8212; how newsroom and post teams are actually using AI in production today, beyond the demo reel: automated QC, metadata extraction, rough-cut generation, compliance logging, and the integration burden each imposes.</li>
  <li><strong>Post-production workflows</strong> &#8212; Avid Media Composer / DaVinci Resolve / Premiere Pro interoperability, MAM and PAM integration, proxy pipelines, archive architectures, and the practical trade-offs between on-prem, hybrid, and cloud post.</li>
  <li><strong>Engineering playbooks</strong> &#8212; reference architectures for ingest-to-playout chains, integration patterns for vendor-neutral newsrooms, and honest post-mortems of standards-migration projects.</li>
</ul>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Editorial standard</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Expert Insights pieces go through a stricter review pass than our daily industry news briefings. We do not publish press-release rewrites under this banner. Where an article analyses a vendor&#39;s technology, we disclose what the vendor has stated, what our editorial team has verified independently, and what remains uncertain. Technical claims that cannot be traced to a primary source are either removed or flagged.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">AI tools assist with drafting on some Insights articles &#8212; primarily for structuring source material and initial analysis &#8212; but every published piece is reviewed by a human editor before going live. See our <a href="editorial-policy.html" style="color:var(--blue)">Editorial Policy</a> for the full methodology on AI-assisted drafting, source attribution, and corrections.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Who writes for us</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Streamic editorial is led by Prerak K Mehta, with 25+ years of IT experience and 20 years in media / post-production / broadcast IT systems. Guest contributions from broadcast engineers, vendor technical staff, and media operations leaders are welcome &#8212; email <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a> with a short pitch outline and any relevant technical credentials.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Read our latest analysis</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Browse our complete archive on the <a href="index.html" style="color:var(--blue)">homepage</a>, our AI-focused coverage on the <a href="ai-post-production.html" style="color:var(--blue)">AI in Broadcasting</a> page, practical guides on the <a href="howto.html" style="color:var(--blue)">How-To Guides</a> page, or curated editorial picks on the <a href="editorsdesk.html" style="color:var(--blue)">Editor&#39;s Desk</a>.</p>

<p style="font-size:13px;color:var(--ink4);line-height:1.7;margin-top:36px;padding-top:20px;border-top:1px solid var(--line)">Have a story tip or a topic we should cover in depth? Reach the editorial team at <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a> or via our <a href="contact.html" style="color:var(--blue)">contact form</a>.</p>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""


def post_production_workflows_page():
    """Post Production Workflows landing page — AdSense-compliant (~700w)."""
    return f"""{head("Post Production Workflows — The Streamic","Practical post-production workflow analysis: NLE interoperability, MAM / PAM integration, proxy pipelines, codec compatibility, and cloud collaboration for broadcast post teams.",f"{BASE_URL}/post-production-workflows.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 24px 80px;max-width:820px">
<h1 style="font-family:var(--serif);font-size:clamp(28px,4vw,44px);margin-bottom:16px;letter-spacing:-.5px">Post Production Workflows</h1>
<p style="font-size:17px;color:var(--ink2);line-height:1.65;margin-bottom:24px">Practical analysis of post-production workflows for broadcast, streaming, and film teams. We cover what actually works in production &#8212; NLE handoffs that survive round-trip, proxy pipelines that don&#39;t break at the storage boundary, MAM integrations that don&#39;t trap metadata, and cloud collaboration patterns that respect the realities of bandwidth, security, and editorial sovereignty.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">What we cover</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:12px">Streamic post-production coverage focuses on the integration seams where workflows most often break:</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li><strong>NLE interoperability</strong> &#8212; AAF, OMF, XML, EDL, and Direct Link handoffs between Avid Media Composer, DaVinci Resolve, Premiere Pro, and Final Cut Pro. Where audio maps cleanly, where effects translate, where timecode gets mangled.</li>
  <li><strong>Codec &amp; container strategy</strong> &#8212; ProRes, DNxHD/HR, XAVC, AVC-Intra, IMF packaging, and the codec-choice decisions that determine whether a finish survives delivery QC on the first pass.</li>
  <li><strong>MAM &amp; PAM integration</strong> &#8212; Avid Nexis and MediaCentral, EditShare EFS, Strawberry, Primestream, Dalet Flex. Which asset models travel, which metadata schemas survive a vendor migration, and where API parity fails.</li>
  <li><strong>Proxy pipelines</strong> &#8212; when to generate proxies at ingest vs. at check-out, codec selection for proxy masters (DNx36 / ProRes Proxy / H.264), and how to keep proxy-to-full conform reliable across distributed teams.</li>
  <li><strong>Cloud &amp; hybrid post</strong> &#8212; Frame.io, EditShare Cloud, Blackmagic Cloud, Avid Edit On Demand, and the bandwidth / latency / security trade-offs of each. Real-world remote editing vs. marketing-reel remote editing.</li>
  <li><strong>Archive &amp; restore</strong> &#8212; LTO strategies, object-storage archive tiers, cold-retrieval SLAs, and the dark art of conforming an archived project 18 months later when the original NLE has moved on three versions.</li>
</ul>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Our approach</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Post-production technology is drowning in marketing. Every NLE claims seamless interchange, every MAM claims universal metadata, every cloud-collaboration platform claims security-first architecture. Our job is to separate what actually ships from what is still a product roadmap, and to call out the integration gotchas that only surface at 02:00 on a delivery night.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Every Streamic article in this area is grounded in real workflow analysis, not vendor-supplied slideware. Where a vendor claims compatibility, we verify by checking against shipping documentation, public API specs, and &#8212; where possible &#8212; the experience of engineering teams running it in production. Where compatibility is partial or conditional, we say so.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Who this is for</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Post-production supervisors, assistant editors, technical operators, broadcast IT leads supporting post facilities, and technology directors evaluating MAM / NLE / cloud-post decisions. If you have ever argued with a vendor rep about whether AAF round-trips EQ automation in version 2024.8, this section is for you.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Related Streamic sections</h2>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li><a href="howto.html" style="color:var(--blue)">How-To Guides</a> &#8212; step-by-step technical guides: Premiere-to-Avid handoff, Vantage transcoding recipes, MediaCentral health checks, audio conform workflows.</li>
  <li><a href="ai-post-production.html" style="color:var(--blue)">AI in Broadcasting</a> &#8212; AI-assisted editing tools, automated QC, generative tools for post, and operational integration patterns.</li>
  <li><a href="insights.html" style="color:var(--blue)">Expert Insights</a> &#8212; long-form analysis and architectural reference material.</li>
  <li><a href="editorsdesk.html" style="color:var(--blue)">Editor&#39;s Desk</a> &#8212; curated editorial picks across the Streamic archive.</li>
</ul>

<p style="font-size:13px;color:var(--ink4);line-height:1.7;margin-top:36px;padding-top:20px;border-top:1px solid var(--line)">Post team working on an integration we should cover? Tell us: <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a> or <a href="contact.html" style="color:var(--blue)">contact form</a>.</p>
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
            "desc": "Run a full pre-air health check &#8212; verify MCPS services, Interplay and iNEWS connections, licensing, and system logs before going on air.",
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

def _nab_bento_section():
    """
    NAB 2026 Highlights — premium cinematic banner header + bento-grid cards.

    Banner design: dark deep-space purple/indigo (matches NAB_SHOW_BANNER image
    palette) with the image as a blended background layer, heavy overlay so text
    is always legible, and a large high-contrast H2.

    Image path: /assets/NAB_SHOW_BANNER_NEWS_HEADLINE_HERO.png
    Fallback: pure CSS gradient so layout never breaks if image is missing.

    Build-safe: pure string, no disk I/O, no external dependencies.
    AdSense-safe: semantic HTML5, no deceptive elements, descriptive alt text.
    CSS-safe: all classes prefixed nab- — zero collision with existing hp- classes.
    """
    cards = [
        {
            "cat": "AI & Post-Production",
            "cat_color": "#ff6b8a",
            "slug": "2026-04-17-ai-post-production-avid-google-cloud-agentic-ai-media-produ",
            "title": "Avid & Google Cloud: Agentic AI and Content Core",
            "img_alt": "Avid Content Core SaaS platform integrating Google Vertex AI and Gemini with Media Composer for agentic broadcast post-production",
            "summary": "Avid launches Content Core — a cloud-native intelligence layer embedding Google Gemini directly into Media Composer. Agentic assistants handle B-roll sourcing, natural-language archive search, and temp shot generation. Hybrid architecture preserves existing NEXIS storage. Available April 2026.",
            "tag": "🎬",
            "is_hero": True,
        },
        {
            "cat": "Cloud Production",
            "cat_color": "#a89bff",
            "slug": "2026-04-01-cloud-tedial-agentic-ai-media-lifecycle-nab-2026",
            "title": "Dalet Dalia: Conversational AI Across the Media Supply Chain",
            "img_alt": "Dalet Dalia agentic AI interface orchestrating media workflows across Dalet Flex, Pyramid, and Galaxy five broadcast platforms",
            "summary": "Dalia is a multi-agent framework acting as a conversational orchestration layer across Dalet Flex, Pyramid, and Galaxy five. Natural language triggers structured workflows — tagging, clipping, social packaging. Early data shows 60% reduction in repetitive task time. Commercially available April 8, 2026.",
            "tag": "☁️",
            "is_hero": False,
        },
        {
            "cat": "Playout",
            "cat_color": "#5dde8a",
            "slug": "2026-04-01-playout-harmonic-spectrum-x-plus-playout-economics",
            "title": "BCNEXXT Vipe: Live UHD HLG HDR and BCE Media-as-a-Service",
            "img_alt": "BCNEXXT Vipe cloud-native playout platform supporting UHD 2160p BT.2100 HLG live ingest with parallel SDR output for broadcast distribution",
            "summary": "BCNEXXT adds UHD 2160p BT.2100 HLG live playout to Vipe with simultaneous SDR output. Integrated into BCE Media-as-a-Service. Pay-per-play model removes infrastructure overhead. Channel launch drops to days. Pre-rendered HLG pre-processing keeps commercial files in sync with live HDR feeds.",
            "tag": "▶️",
            "is_hero": False,
        },
        {
            "cat": "Newsroom",
            "cat_color": "#ffd166",
            "slug": "2026-04-01-newsroom-dalet-flex-2512-semantic-search-dalia-ai",
            "title": "Mediagenix: Semantic Intelligence for FAST Channel Scheduling",
            "img_alt": "Mediagenix Scheduling Artist AI generating automated linear channel schedules using semantic content intelligence and audience behaviour signals",
            "summary": "Mediagenix deploys a Semantic Intelligence layer — combining Spideo AI with rights metadata — to automate scheduling and discovery. Scheduling Artist cuts manual scheduling effort by 80%, playlist prep by 85%. Humanized Semantic Search interprets intent, not keywords. Won 2025 NAB Product of Year.",
            "tag": "📰",
            "is_hero": False,
        },
        {
            "cat": "AI & Post-Production",
            "cat_color": "#ff6b8a",
            "slug": "2026-04-01-ai-post-production-telestream-adobe-frameio-creative-delive",
            "title": "Telestream: Oracle OCI Multi-Cloud and Adobe Frame.io V4",
            "img_alt": "Telestream Vantage workflow panel inside Adobe Premiere Pro submitting to Oracle Cloud Infrastructure OCI for multi-cloud broadcast media processing",
            "summary": "Telestream optimises Vantage, UP platform, and SENTRY QoS for Oracle Cloud Infrastructure, cutting egress costs. New Premiere Pro panel submits sequences directly to Vantage pipelines. Frame.io V4 connector ensures seamless API migration. Hybrid, on-prem, and multi-cloud deployments supported.",
            "tag": "🎬",
            "is_hero": False,
        },
        {
            "cat": "Streaming",
            "cat_color": "#60b4ff",
            "slug": "2026-04-01-cloud-tedial-agentic-ai-media-lifecycle-nab-2026",
            "title": "Vubiquity & Eluvio: Zero-Copy Distribution Economics",
            "img_alt": "Eluvio Content Fabric protocol showing zero-copy just-in-time media packaging eliminating CDN duplication costs for global streaming distribution",
            "summary": "Vubiquity and Eluvio replace fragmented file pipelines with a single Content Fabric object — one source, global reach. Zero-copy JIT packaging eliminates per-region duplication. EVIE AI enables frame-accurate archive search without file movement. Sub-500ms global latency replaces satellite links.",
            "tag": "📡",
            "is_hero": False,
        },
    ]

    hero = next((c for c in cards if c["is_hero"]), cards[0])
    others = [c for c in cards if not c["is_hero"]]
    fb = "assets/fallback.jpg"

    # ── Hero card — wide horizontal ───────────────────────────────────────
    hero_html = f'''<article class="nab-card nab-card-hero" itemprop="itemListElement" itemscope itemtype="https://schema.org/Article">
  <a href="articles/{hero["slug"]}.html" class="nab-card-link" aria-label="Read full NAB 2026 analysis: {hero["title"]}">
    <div class="nab-card-img nab-card-img-hero" aria-hidden="true">
      <div class="nab-card-img-placeholder nab-card-img-placeholder--ai"></div>
    </div>
    <div class="nab-card-body">
      <span class="nab-featured-badge">&#9733; Lead Story</span>
      <span class="nab-cat" style="--nab-cat-c:{hero["cat_color"]}">{hero["tag"]} {hero["cat"]}</span>
      <h3 class="nab-title" itemprop="headline">{hero["title"]}</h3>
      <p class="nab-summary" itemprop="description">{hero["summary"]}</p>
      <span class="nab-cta">Read Full Analysis <span class="nab-cta-arrow" aria-hidden="true">&#8594;</span></span>
    </div>
  </a>
</article>'''

    # ── Standard cards ────────────────────────────────────────────────────
    std_cards = ""
    placeholders = ["--ai", "--cloud", "--playout", "--news", "--stream"]
    for i, c in enumerate(others):
        ph = placeholders[i % len(placeholders)]
        std_cards += f'''<article class="nab-card nab-card-std" itemprop="itemListElement" itemscope itemtype="https://schema.org/Article">
  <a href="articles/{c["slug"]}.html" class="nab-card-link" aria-label="NAB 2026: {c["title"]}">
    <div class="nab-card-img nab-card-img-std" aria-hidden="true">
      <div class="nab-card-img-placeholder nab-card-img-placeholder{ph}"></div>
    </div>
    <div class="nab-card-body">
      <span class="nab-cat" style="--nab-cat-c:{c["cat_color"]}">{c["tag"]} {c["cat"]}</span>
      <h3 class="nab-title" itemprop="headline">{c["title"]}</h3>
      <p class="nab-summary" itemprop="description">{c["summary"]}</p>
      <span class="nab-cta">Read Analysis <span class="nab-cta-arrow" aria-hidden="true">&#8594;</span></span>
    </div>
  </a>
</article>
'''

    return f'''<section class="nab-section" aria-labelledby="nab-h2" itemscope itemtype="https://schema.org/ItemList">
  <meta itemprop="name" content="NAB Show 2026 Broadcast Technology Updates — The Streamic">

  <!-- ── CINEMATIC BANNER HEADER ──────────────────────────────────── -->
  <header class="nab-banner" role="banner" aria-label="NAB Show 2026 section header">
    <div class="nab-banner-bg" aria-hidden="true">
      <img
        class="nab-banner-img"
        src="assets/NAB_SHOW_BANNER_NEWS_HEADLINE_HERO.png"
        alt=""
        loading="lazy"
        onerror="this.style.display=&apos;none&apos;"
      >
      <div class="nab-banner-overlay" aria-hidden="true"></div>
      <div class="nab-banner-grain" aria-hidden="true"></div>
    </div>
    <div class="nab-banner-content">
      <div class="nab-banner-eyebrow">
        <span class="nab-live-pulse" aria-hidden="true"></span>
        <span class="nab-banner-label">LIVE COVERAGE</span>
        <span class="nab-banner-sep" aria-hidden="true">&middot;</span>
        <span class="nab-banner-location">Las Vegas &bull; April 18&ndash;22, 2026</span>
      </div>
      <h2 id="nab-h2" class="nab-banner-h2">
        <span class="nab-banner-h2-nab">NAB 2026</span>
        <span class="nab-banner-h2-hl">Highlights</span>
      </h2>
      <p class="nab-banner-sub">Independent editorial analysis of the technology announcements that will reshape broadcast infrastructure, AI-driven production, and streaming distribution through 2027.</p>
      <a href="ai-post-production.html" class="nab-banner-cta" aria-label="View all NAB 2026 coverage">
        View all coverage <span aria-hidden="true">&#8594;</span>
      </a>
    </div>
  </header>
  <!-- ── END BANNER ────────────────────────────────────────────────── -->

  <div class="nab-bento">
    {hero_html}
    <div class="nab-std-grid">
      {std_cards}
    </div>
  </div>

</section>'''


def editorsdesk_page():
    """Editor's Desk landing page.

    Safety rules (this function must NEVER break the live site):
      1. CSS is injected INSIDE <head> by splitting head()'s output at </head>,
         so styles land in the right place and cascade AFTER style.css.
      2. All class names are prefixed `strmc-ed-` to guarantee zero collision
         with existing CSS in style.css.
      3. Explicit hex colors are used (not CSS variables) so cards render
         even if style.css hasn't loaded or var(--ink) is undefined.
      4. Each card's target article file is checked on disk BEFORE the card
         is rendered. Missing articles produce no card — never a broken link.
      5. If zero cards survive the existence check, we fall back to the old
         simple "what we're watching" layout so the page is never empty.
      6. nav() and footer() are always included so the page has the site
         header and footer regardless of content state.
    """
    editorial_cards = [
        ("INFRASTRUCTURE", "st-2110-7-seamless-protection-redundancy-math-2026",
         "ST 2110-7 Seamless Protection: The Redundancy Math Every IP Broadcaster Gets Wrong",
         "Hitless failover is the headline promise of ST 2110-7. The Red/Blue network math, PTP boundary clock placement, and the control plane gap are where 2026 IP migrations quietly fail."),
        ("CLOUD PRODUCTION", "cloud-playout-tco-trap-medialive-economics-2026",
         "The Cloud Playout TCO Trap: Why AWS MediaLive Looks Cheap Until It Isn't",
         "Cloud playout pricing looks linear on the slide deck and exponential on the invoice. The real cost curve for MediaLive + MediaPackage, and where the break-even with Grass Valley Ignite actually sits."),
        ("AI IN BROADCASTING", "ai-metadata-mam-accuracy-broadcast-2026",
         "AI Metadata in the MAM: Why 95% Accuracy Is Still a Failing Grade",
         "Every MAM vendor ships AI auto-tagging in 2026. The accuracy numbers describe benchmarks editors never hit. The gap between '95% correct' and 'useful for an editor on deadline' is where these systems still fail."),
        ("INFRASTRUCTURE", "ndi-6-vs-st-2110-india-mid-market-2026",
         "NDI 6 vs ST 2110 for India's Mid-Market Broadcasters: The Pragmatic Read",
         "ST 2110 is the standard. NDI 6 is what most Indian regional broadcasters will actually deploy. The honest engineering comparison — latency, compression, network cost, and where each earns its place."),
        ("AI IN BROADCASTING", "c2pa-provenance-newsroom-broadcast-mandate-2027",
         "C2PA in the Newsroom: The Provenance Standard Nobody Can Afford to Ignore by 2027",
         "C2PA content provenance has been a compliance side-project since 2023. Synthetic media incidents and EU regulation mean 2026 is the last year it stays a side-project."),
        ("EDITORIAL", "beyond-the-chatbot-operational-ai-newsroom-2026",
         "Beyond the Chatbot: Operational AI in the Newsroom",
         "The interesting AI in newsrooms isn't the one writing copy. It's the one routing video, tagging rushes, and quietly replacing three roles in the ingest workflow."),
        ("EDITORIAL", "green-broadcast-cloud-carbon-footprint-sustainability-2026",
         "Green Broadcast: The Cloud Carbon Footprint Conversation Nobody's Having Honestly",
         "The industry's sustainability numbers are almost all scope-1 and scope-2. Scope-3 is where the real emissions hide."),
        ("EDITORIAL", "ai-reducing-broadcast-operational-costs-2026",
         "AI as an OpEx Lever: Where the Savings Are Real and Where They're Theatre",
         "Vendors are selling AI as cost reduction. Some claims are real. Some are creative accounting. Here's how to tell which is which."),
    ]

    # Only render cards whose target article actually exists on disk.
    rendered = []
    for cat, slug, title, dek in editorial_cards:
        if os.path.exists(os.path.join(DOCS, "articles", f"{slug}.html")):
            rendered.append((cat, slug, title, dek))

    # Build CSS block — scoped, explicit colors, !important on critical props
    # so nothing in style.css can hide the title or link.
    extra_css = """
<style>
.strmc-ed-hero{max-width:920px;margin:40px auto 16px;padding:0 24px}
.strmc-ed-hero h1{font-family:'DM Serif Display',Georgia,serif;font-size:48px;line-height:1.1;margin:0 0 10px;color:#111 !important}
.strmc-ed-hero p.lede{font-size:18px;color:#555;line-height:1.55;max-width:700px;margin:0}
.strmc-ed-watching{max-width:920px;margin:24px auto 32px;padding:22px 26px;background:#f6f3ec;border-left:4px solid #D4AF37;border-radius:6px}
.strmc-ed-watching strong{display:block;font-family:'DM Serif Display',Georgia,serif;font-size:20px;color:#111 !important;margin-bottom:8px;font-weight:normal}
.strmc-ed-watching p{margin:0;font-size:15px;color:#555;line-height:1.65}
.strmc-ed-grid{max-width:1100px;margin:0 auto 72px;padding:0 24px;display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px}
.strmc-ed-card{display:block;background:#fff;border:1px solid #e5e0d1;border-radius:8px;padding:26px 24px;text-decoration:none !important;transition:border-color .2s,transform .2s,box-shadow .2s}
.strmc-ed-card:hover{border-color:#D4AF37;transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.06)}
.strmc-ed-card .cat{display:block;font-size:11px;letter-spacing:1.4px;color:#D4AF37 !important;font-weight:700;text-transform:uppercase;margin:0 0 12px}
.strmc-ed-card .title{display:block;font-family:'DM Serif Display',Georgia,serif;font-size:22px;line-height:1.28;color:#111 !important;margin:0 0 12px;font-weight:normal}
.strmc-ed-card:hover .title{color:#D4AF37 !important}
.strmc-ed-card .dek{display:block;font-size:14px;color:#555 !important;line-height:1.6;margin:0 0 14px}
.strmc-ed-card .read{display:inline-block;font-size:13px;color:#D4AF37 !important;font-weight:600}
</style>
"""
    # Inject the style block INSIDE <head>, right before </head>, so it
    # cascades after style.css and wins on specificity ties.
    raw_head = head("Editor's Desk — The Streamic",
                    "Commentary, perspective, and engineering analysis from the editorial team at The Streamic.",
                    f"{BASE_URL}/editorsdesk.html")
    head_with_css = raw_head.replace("</head>", extra_css + "</head>")

    if rendered:
        cards_html = "".join(
            f'''<a class="strmc-ed-card" href="articles/{slug}.html">
<span class="cat">{cat}</span>
<span class="title">{title}</span>
<span class="dek">{dek}</span>
<span class="read">Read the analysis &rarr;</span>
</a>''' for (cat, slug, title, dek) in rendered
        )
        main_html = f"""<main>
<section class="strmc-ed-hero">
  <h1>Editor's Desk</h1>
  <p class="lede">Commentary, perspective, and engineering analysis from the editorial team at The Streamic. Technical reads that go beyond the news cycle &mdash; honest trade-off analysis for broadcast engineers, CTOs, and media IT architects who actually have to deploy this stuff.</p>
</section>
<section class="strmc-ed-watching">
  <strong>What we're watching in 2026</strong>
  <p>The ST 2110 adoption curve in small-market broadcasters. The real TCO of cloud playout post-NAB 2026. How C2PA is quietly becoming a newsroom compliance surface. The gap between AI-tagged MAMs in demos and AI-tagged MAMs in production.</p>
</section>
<section class="strmc-ed-grid">
{cards_html}
</section>
</main>"""
    else:
        # Fallback: no hand-authored articles on disk yet. Show the old
        # simple layout so the page is never blank and has zero broken links.
        main_html = """<main><div class="w" style="padding:52px 24px 80px;max-width:760px">
<div class="cat-hdr">
  <h1>Editor's Desk</h1>
  <p>Commentary, perspective, and notes from the editorial team at The Streamic.</p>
</div>
<p style="font-size:15px;color:#555;line-height:1.7;margin-bottom:24px">The Streamic covers broadcast and streaming technology with a focus on what matters operationally to engineers and technology leaders. This is where we share perspective beyond the news cycle.</p>
<div style="background:#f6f3ec;border-radius:14px;padding:28px;font-size:14px;color:#555;line-height:1.7">
  <strong style="color:#111;display:block;margin-bottom:8px">What we're watching in 2026</strong>
  The ST 2110 adoption curve in small-market broadcasters. The economics of cloud production post-NAB 2026. How C2PA is changing newsroom verification workflows. The quiet revolution of operational AI inside MAM systems.
</div>
</div></main>"""

    return f"""{head_with_css}
<body>
{nav("editorsdesk.html")}
{main_html}
{footer()}
{_cookie_banner()}
</body></html>"""

# Backwards-compatibility alias — in case any other call site still calls vlog_page().
vlog_page = editorsdesk_page

# ── SITEMAP
def sitemap(arts):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    statics = [
        ("",           "daily","1.0"),("featured.html","daily","0.98"),
        ("ai-post-production.html","daily","0.9"),
        ("howto.html","weekly","0.85"),("post-production-workflows.html","weekly","0.90"),
        ("insights.html","weekly","0.88"),
        ("editorsdesk.html","weekly","0.88"),
        ("about.html","monthly","0.6"),("contact.html","monthly","0.5"),
        ("editorial-policy.html","monthly","0.6"),
        ("privacy.html","yearly","0.3"),("terms.html","yearly","0.3"),
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

    # ── Deduplicate by slug ───────────────────────────────────────────────
    seen_slugs, deduped = set(), []
    for a in arts:
        if a["slug"] not in seen_slugs:
            seen_slugs.add(a["slug"])
            deduped.append(a)
    arts = deduped
    print(f"  After slug dedup: {len(arts)} unique articles")

    # ── Jaccard near-duplicate cleanup (retroactive) ──────────────────────
    # Catches cross-feed story re-runs that slipped through rewrite_feed.py
    # before the 3-pass dedup was introduced. E.g. "Bitcentral to Showcase
    # Connected Media Workflows" and "Bitcentral To Feature Connected
    # Media Workflows" both about the same NAB press release.
    #
    # For each group of near-duplicates (>=70% token overlap), we keep:
    #   1. HAND_AUTHORED articles first (immutable protection)
    #   2. Then longest body (best content wins)
    #   3. Then newest published date as tiebreaker
    import re as _dd_re
    def _dd_tokens(title):
        if not title: return set()
        t = _dd_re.sub(r"[^a-zA-Z0-9\s]", " ", title.lower())
        return {w for w in t.split() if len(w) >= 4 and w not in {
            "with","from","that","this","will","show","2026","2025","2024",
            "announced","launches","introduces","unveils","debuts","nabs",
            "nab","ibc","new","the","and","for","are","into",
            "showcase","showcases","showcased","feature","features","featured",
            "to","at","on","in","by","of","a","an","is","its",
            # Broadcast-industry boilerplate that inflates false-positive splits:
            "intelligent","automation","solution","solutions","platform","technology",
            "workflow","workflows","system","systems","broadcast","media",
            "company","companies","announces","announcing",
        }}
    def _is_hand_authored(a):
        # Look up the file on disk; presence of <!-- HAND_AUTHORED --> wins.
        slug = a.get("slug", "")
        if not slug: return False
        try:
            fp = os.path.join(DOCS, "articles", slug + ".html")
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    head = fh.read(400)
                return "HAND_AUTHORED" in head
        except Exception:
            pass
        return False

    JACCARD_THRESHOLD = 0.70
    kept = []
    dropped_near_dup = 0
    for candidate in arts:
        cand_tokens = _dd_tokens(candidate.get("title", ""))
        if not cand_tokens or len(cand_tokens) < 2:
            kept.append(candidate)
            continue
        merged = False
        for idx, existing in enumerate(kept):
            ex_tokens = _dd_tokens(existing.get("title", ""))
            if not ex_tokens: continue
            union = len(cand_tokens | ex_tokens)
            if union == 0: continue
            similarity = len(cand_tokens & ex_tokens) / union
            if similarity >= JACCARD_THRESHOLD:
                # Found a near-duplicate. Decide which to keep.
                cand_hand = _is_hand_authored(candidate)
                ex_hand   = _is_hand_authored(existing)
                cand_len  = len((candidate.get("body_html") or candidate.get("body") or "") or "")
                ex_len    = len((existing.get("body_html") or existing.get("body") or "") or "")
                # Tiebreak: hand-authored > longer body > newer
                if cand_hand and not ex_hand:
                    winner = candidate
                elif ex_hand and not cand_hand:
                    winner = existing
                elif cand_len > ex_len * 1.10:
                    winner = candidate
                elif ex_len > cand_len * 1.10:
                    winner = existing
                else:
                    winner = candidate if (candidate.get("date", "") > existing.get("date", "")) else existing
                loser = existing if winner is candidate else candidate
                print(f"  [DEDUP] '{loser.get('title','')[:55]}' "
                      f"≈ '{winner.get('title','')[:55]}' ({similarity:.0%}) — keeping winner")
                if winner is candidate:
                    kept[idx] = candidate
                dropped_near_dup += 1
                merged = True
                break
        if not merged:
            kept.append(candidate)
    arts = kept
    print(f"  After near-dup dedup: {len(arts)} unique articles "
          f"(removed {dropped_near_dup} near-duplicates)")

    # ── Ensure all articles have a slug ──────────────────────────────────
    def _slugify(title):
        return re.sub(r"[^a-z0-9]+", "-", (title or "article").lower()).strip("-")
    for a in arts:
        if not a.get("slug"):
            a["slug"] = _slugify(a.get("title", "untitled"))

    # ── Ensure all articles have body content field ───────────────────────
    for a in arts:
        if not a.get("body_html"):
            # Fall back to card_summary or description so pages aren't empty
            fallback = a.get("card_summary") or a.get("description") or ""
            if fallback:
                a["body_html"] = f"<p>{fallback}</p>"

    # ── QUALITY GATE — TWO-TIER SYSTEM ─────────────────────────────────────
    #
    # Tier 1 (page exists, internal link works): 400+ words + 2 broadcast terms
    #   → article HTML page is generated, used by Intelligence section, etc.
    #   → gets noindex,nofollow (not visible to Google)
    #
    # Tier 2 (SEO-visible, fully indexed): 800+ words OR gpt_manual_editorial
    #   → gets index,follow — the high-quality articles Google sees
    #
    # HOMEPAGE PROTECTION: articles hardcoded into the homepage layout
    # (hero, Latest Insights, Professional Media Systems Guide) always survive.
    # ─────────────────────────────────────────────────────────────────────────

    MIN_FEED_WORDS = 400   # Word-count floor only.
                           # Kept at 400 because Groq TPM rate limits cause
                           # scaffold upgrades to lag — raising the gate
                           # before upgrades complete strips ~120 articles
                           # from the visible site (verified in pipeline log
                           # 2026-04-11 13:22 UTC: 62 pass / 122 rejected).
                           # The 180-term BROADCAST_TERMS relevance gate
                           # below is unchanged and remains the primary
                           # quality protection.

    HOMEPAGE_PROTECTED_SLUGS = {
        # Hero
        "ai-reducing-broadcast-operational-costs-2026",
        # Professional Media Systems Guide
        "broadcast-automation-systems-guide-2026",
        "ip-broadcasting-smpte-st2110-engineering-guide-2026",
        "cloud-broadcast-workflows-remote-production-2026",
        "media-asset-management-ai-era-monetisation-2026",
        # Latest Insights
        "beyond-the-chatbot-operational-ai-newsroom-2026",
        "st-2110-small-market-hybrid-ip-broadcasters-2026",
        "paris-2024-cloud-production-legacy-global-events-2026",
        "c2pa-deepfake-news-credibility-digital-provenance-2026",
        # Flagship / pillar articles
        "studio-grade-video-workflow-post-production-2026",
        "green-broadcast-cloud-carbon-footprint-sustainability-2026",
    }

    quality_pass, quality_fail = [], []
    for a in arts:
        slug = a.get("slug", "")

        # Homepage-protected articles always pass
        if slug in HOMEPAGE_PROTECTED_SLUGS:
            quality_pass.append(a)
            continue

        # Manual editorials: 400-word floor (they're hand-curated)
        is_manual = a.get("generated_by") == "gpt_manual_editorial"
        body = a.get("body_html", "") or ""
        plain = re.sub(r"<[^>]+>", " ", body)
        plain = re.sub(r"\s+", " ", plain).strip()
        wc = len(plain.split())

        if is_manual and wc < MIN_FEED_WORDS:
            quality_fail.append((slug, f"editorial too short ({wc}w, need {MIN_FEED_WORDS})"))
            continue

        # Auto-generated: need MIN_FEED_WORDS (400) to get a page at all
        if not is_manual and wc < MIN_FEED_WORDS:
            quality_fail.append((slug, f"too short ({wc}w, need {MIN_FEED_WORDS})"))
            continue

        # Broadcast relevance: need 2+ matching terms
        search_text = (a.get("title", "") + " " + plain).lower()
        matched = set()
        for term in BROADCAST_TERMS:
            if term in search_text:
                matched.add(term)
            if len(matched) >= 2:
                break
        if len(matched) < 2:
            quality_fail.append((slug, f"low relevance ({len(matched)} terms)"))
            continue

        quality_pass.append(a)

    if quality_fail:
        print(f"  Quality gate: {len(quality_pass)} pass, {len(quality_fail)} rejected")
        for slug, reason in quality_fail[:10]:
            print(f"    ✗ {slug[:60]}  — {reason}")
        if len(quality_fail) > 10:
            print(f"    … and {len(quality_fail)-10} more")
    arts = quality_pass

    print(f"  Total articles after quality gate: {len(arts)}")

    # ── Fix images: replace typewriters/newspapers with broadcast visuals ──
    _fix_article_images(arts)

    # ── Select top MAX_ARTICLES by quality — editorial always first ───────
    # SAFE DESIGN: AdSense quality affects index/noindex status, NOT visibility.
    # Category pages always show articles. Only the robots meta tag differs.
    # This means cloud.html, streaming.html etc always have content.

    ed_arts  = [a for a in arts if a.get("is_editorial") or a.get("editorial")]
    rss_pool = [a for a in arts if not a.get("is_editorial") and not a.get("editorial")]

    # Score all RSS articles — high scorers get indexed, others get noindex
    # but are still rendered on category pages (never blank)
    rss_pool.sort(key=lambda a: -_score_art(a))

    # Top RSS by score — these get index,follow
    # Use a per-category quota to ensure diversity: 3 per cat max
    cat_quota = {}
    rss_indexed = []
    for a in rss_pool:
        cat = a.get("category", "featured")
        if cat_quota.get(cat, 0) < 3:
            rss_indexed.append(a)
            cat_quota[cat] = cat_quota.get(cat, 0) + 1
        if len(rss_indexed) >= 22:   # max 22 industry briefing indexed slots
            break

    visible_list  = (ed_arts + rss_indexed)[:MAX_ARTICLES]
    visible_slugs = {a["slug"] for a in visible_list}

    # Diagnostic
    rss_indexed_count = len(rss_indexed)
    rss_noindex_count = len(rss_pool) - rss_indexed_count
    print(f"  Visible (indexed): {len(visible_slugs)} | Hidden (noindex): {len(arts)-len(visible_slugs)}")
    print(f"  RSS: {rss_indexed_count} indexed + {rss_noindex_count} noindex (appear on pages, not in search)")

    os.makedirs(ARTS_D, exist_ok=True)

    # ── Article pages — visible indexed, rest noindex ─────────────────────
    # Any article file containing <!-- HAND_AUTHORED --> is never overwritten.
    # Add that comment to any article you edit manually to protect it permanently.
    written = 0
    for a in arts:
        slug_ = a.get("slug","")
        leg   = a.get("legacy_slug")
        dest  = os.path.join(ARTS_D, f"{slug_}.html")

        # Skip if file exists and is hand-authored
        if os.path.exists(dest):
            with open(dest, encoding="utf-8") as _fh:
                if "<!-- HAND_AUTHORED -->" in _fh.read():
                    written += 1
                    continue

        html  = article_page(a)
        if a["slug"] not in visible_slugs:
            html = html.replace(
                '<meta name="robots" content="index,follow">',
                '<meta name="robots" content="noindex,nofollow">'
            )
        w(dest, html)
        written += 1
        if leg and leg != slug_:
            leg_dest = os.path.join(ARTS_D, f"{leg}.html")
            if not (os.path.exists(leg_dest) and "<!-- HAND_AUTHORED -->" in open(leg_dest, encoding="utf-8").read()):
                w(leg_dest, html)
                written += 1
    print(f"  &#10003; {written} article files ({len(visible_slugs)} indexed, {written-len(visible_slugs)} noindex)")

    # ── Category pages ────────────────────────────────────────────────────
    # ALL category pages now show REAL articles (never blank "coming soon").
    # Only the robots meta tag differs: VISIBLE_CAT is indexed, others are noindex.
    # This means cloud.html, streaming.html etc always have content for visitors
    # and for AdSense crawlers — they just don't appear in Google search results
    # until we're ready to index them.
    by_cat = {}
    for a in arts:
        by_cat.setdefault(a["category"], []).append(a)

    cat_page_counts = {}
    for cat, ca in by_cat.items():
        # All articles for this category, sorted by date
        ca_sorted = sorted(ca, key=lambda a: a.get("published", ""), reverse=True)

        if cat == VISIBLE_CAT:
            # ai-post-production: indexed, pin relevant deep-dives
            cat_vis = ca_sorted[:]
            PINNED_TO_AI_POST = {
                "ai-video-post-production-editing-vfx-automation-2026",
                "media-asset-management-ai-era-monetisation-2026",
                "future-of-ai-in-broadcast-deployment-2026",
            }
            pinned_slugs = {a["slug"] for a in cat_vis}
            for a in arts:
                if a["slug"] in PINNED_TO_AI_POST and a["slug"] not in pinned_slugs:
                    cat_vis.append(a)
            cat_vis.sort(key=lambda a: a.get("published", ""), reverse=True)
            pages = category_page(cat, cat_vis)
            for pg, html in pages:
                if pg > 0:
                    html = html.replace(
                        '<meta name="robots" content="index,follow">',
                        '<meta name="robots" content="noindex,follow">'
                    )
                fname = f"{cat}.html" if pg == 0 else f"{cat}-p{pg+1}.html"
                w(os.path.join(DOCS, fname), html)
            cat_page_counts[cat] = len(cat_vis)

        else:
            # All other categories: noindex BUT show real articles (not placeholder)
            # Fallback: if somehow empty, use top articles from any category
            cat_articles = ca_sorted if ca_sorted else arts[:10]
            if not cat_articles:
                cat_articles = arts[:10]

            pages = category_page(cat, cat_articles)
            for pg, html in pages:
                # Force noindex on all pages for non-VISIBLE_CAT categories
                html = html.replace(
                    '<meta name="robots" content="index,follow">',
                    '<meta name="robots" content="noindex,follow">'
                )
                fname = f"{cat}.html" if pg == 0 else f"{cat}-p{pg+1}.html"
                w(os.path.join(DOCS, fname), html)
            cat_page_counts[cat] = len(cat_articles)

    indexed_cats  = [c for c in cat_page_counts if c == VISIBLE_CAT]
    noindex_cats  = [c for c in cat_page_counts if c != VISIBLE_CAT]
    print(f"  &#10003; {VISIBLE_CAT} indexed | {len(noindex_cats)} other categories noindex (with real articles)")
    for cat, n in sorted(cat_page_counts.items()):
        print(f"      {cat}: {n} articles")

    # ── Homepage ──────────────────────────────────────────────────────────
    feat_arts = sorted(arts, key=lambda a: a["published"], reverse=True)
    fp = featured_page(feat_arts)
    w(os.path.join(DOCS,"featured.html"), fp)
    w(os.path.join(DOCS,"index.html"),    fp)
    w(os.path.join(ROOT,"index.html"),    fp)   # Also at root — fixes 404 when Pages serves from branch root
    w(os.path.join(ROOT,"featured.html"), fp)  # Mirror at root so /featured.html resolves everywhere
    print("  &#10003; featured.html + index.html")

    # ── posts.html — noindex (preserve links, hide from Google) ──────────
    ap = all_articles_page(feat_arts)
    ap = ap.replace(
        '<meta name="robots" content="index,follow">',
        '<meta name="robots" content="noindex,follow">'
    )
    w(os.path.join(DOCS,"posts.html"), ap)
    w(os.path.join(ROOT,"posts.html"), ap)
    print("  &#10003; posts.html (noindex)")

    # ── Static pages ──────────────────────────────────────────────────────
    w(os.path.join(DOCS,"about.html"),            about_page())
    w(os.path.join(DOCS,"contact.html"),          contact_page())
    w(os.path.join(DOCS,"privacy.html"),          privacy_page())
    w(os.path.join(DOCS,"terms.html"),            terms_page())
    w(os.path.join(DOCS,"editorial-policy.html"), editorial_policy_page())
    w(os.path.join(DOCS,"howto.html"),            howto_page())
    w(os.path.join(DOCS,"insights.html"),         insights_page())
    w(os.path.join(DOCS,"post-production-workflows.html"), post_production_workflows_page())
    # Write Editor's Desk to editorsdesk.html (new canonical name).
    w(os.path.join(DOCS, "editorsdesk.html"), editorsdesk_page())

    # ── AdSense compliance: delete thin redirect stubs + template junk ────
    # AdSense flags 4-word <meta refresh> redirect pages as "low-value
    # content." Soft-redirect stubs and thin template pages have no unique
    # content — they must return 404, not render with AdSense scripts.
    _ADSENSE_PURGE = [
        "vlog.html",                   # redirect stub (old)
        "how-to.html",                 # redirect stub → howto.html
        "broadcast-systems-hub.html",  # 4-word redirect stub → index.html
        "featured_priority.html",      # 276w template junk (data-layer artifact)
        "thank-you.html",              # 19w form-submission landing (thin)
    ]
    for _stale in _ADSENSE_PURGE:
        _path = os.path.join(DOCS, _stale)
        if os.path.exists(_path):
            try:
                os.remove(_path)
                print(f"  &#10003; purged thin page: {_stale}")
            except Exception:
                pass
    print("  &#10003; static pages")

    # ── Sitemap — only visible articles + core pages ──────────────────────
    w(os.path.join(DOCS,"sitemap.xml"), sitemap([a for a in arts if a["slug"] in visible_slugs]))
    w(os.path.join(DOCS,"robots.txt"),
      f"User-agent: *\nAllow: /\nDisallow: /posts.html\n\nSitemap: {BASE_URL}/sitemap.xml\n")

    # ── Assets ────────────────────────────────────────────────────────────
    for f_name in ("style.css","main.js"):
        src = os.path.join(ROOT, f_name)
        if os.path.isfile(src): shutil.copy2(src, os.path.join(DOCS, f_name))
    print("  &#10003; style.css + main.js -> docs/")

    w(os.path.join(DOCS,"ads.txt"),  "google.com, pub-8033069131874524, DIRECT, f08c47fec0942fa0\n")
    w(os.path.join(DOCS,"CNAME"),    "thestreamic.in\n")
    open(os.path.join(DOCS,".nojekyll"),"w").close()
    open(os.path.join(ROOT,".nojekyll"),"w").close()  # Also at root — prevents Jekyll from running at all
    w(os.path.join(ROOT,"CNAME"),    "thestreamic.in\n")

    for fn in ["style.css","main.js","ads.txt","robots.txt"]:
        src_f = os.path.join(DOCS, fn)
        if os.path.isfile(src_f): shutil.copy2(src_f, os.path.join(ROOT, fn))

    # ── How-to guides to root/articles/ ──────────────────────────────────
    root_arts = os.path.join(ROOT,"articles")
    os.makedirs(root_arts, exist_ok=True)
    howto_guides = [fn for fn in os.listdir(ARTS_D) if fn.startswith("guide-") and fn.endswith(".html")]
    for fn in howto_guides:
        shutil.copy2(os.path.join(ARTS_D,fn), os.path.join(root_arts,fn))
    print(f"  &#10003; {len(howto_guides)} how-to guides mirrored to root/articles/")

    # ── Copy root-level hand-authored articles to docs/articles/ ──────────
    # These are manually created articles that live at repo root and must
    # also be served from docs/articles/ for GitHub Pages to find them.
    _root_html_articles = [
        "studio-grade-video-workflow-post-production-2026.html",
    ]
    for _fn in _root_html_articles:
        _src_path = os.path.join(ROOT, _fn)
        _dst_path = os.path.join(ARTS_D, _fn)
        if os.path.isfile(_src_path) and not os.path.exists(_dst_path):
            shutil.copy2(_src_path, _dst_path)
            print(f"  &#10003; {_fn} copied to docs/articles/")
        elif os.path.isfile(_src_path):
            # Always update — root is the source of truth for hand-authored articles
            shutil.copy2(_src_path, _dst_path)
            print(f"  &#10003; {_fn} synced to docs/articles/")

    # ── docs/data/ for client-side JS — only visible articles ────────────
    docs_data_dir = os.path.join(DOCS, "data")
    os.makedirs(docs_data_dir, exist_ok=True)

    news_src = os.path.join(ROOT, "data", "news.json")
    if os.path.exists(news_src):
        with open(news_src,encoding="utf-8") as f: raw = json.load(f)
        if isinstance(raw,list):
            out = {"featured_priority":raw[:6],"items":raw[6:]}
        elif isinstance(raw,dict) and "items" in raw:
            out = raw
        else:
            flat=[]
            for cat,lst in raw.items():
                for it in (lst or []): it.setdefault("category",cat); flat.append(it)
            flat.sort(key=lambda x:x.get("pubDate",""),reverse=True)
            out = {"featured_priority":flat[:6],"items":flat[6:]}
        with open(os.path.join(docs_data_dir,"news.json"),"w",encoding="utf-8") as f:
            json.dump(out,f,ensure_ascii=False)
        print(f"  &#10003; docs/data/news.json ({len(out.get('items',[]))} items)")

    gen_src = os.path.join(ROOT, "data", "generated_articles.json")
    if os.path.exists(gen_src):
        with open(gen_src,encoding="utf-8") as _f: raw_gen = json.load(_f)
        vis_gen = [a for a in raw_gen if a.get("slug") in visible_slugs]
        vis_gen.sort(key=lambda a: a.get("published",""), reverse=True)
        out_gen = {"featured_priority":vis_gen[:6],"items":vis_gen[6:]}
        gen_dst = os.path.join(docs_data_dir,"generated_articles.json")
        with open(gen_dst,"w",encoding="utf-8") as _f: json.dump(out_gen,_f,ensure_ascii=False)
        print(f"  &#10003; docs/data/generated_articles.json ({len(vis_gen)} visible articles)")

    print(f"\n✅ Build complete: {len(visible_slugs)}/{len(arts)} articles visible | AdSense mode ON")

if __name__ == "__main__":
    main()