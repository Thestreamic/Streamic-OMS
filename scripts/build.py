"""
scripts/build.py &#8212; The Streamic site builder
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

# ── AdSense approval mode ─────────────────────────────────────────────────────
# Show curated high-quality content. Full dataset remains hidden.
MAX_ARTICLES   = 35          # raised to accommodate all 13 editorial + top RSS
VISIBLE_CAT    = "ai-post-production"  # only this category page is indexed
MIN_BODY_SCORE = 50          # minimum editorial score to appear on homepage

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
    # AdSense mode: only Home, AI Post category, and How-To visible
    cats = [
        ("featured.html", "Home"),
        ("ai-post-production.html", "AI in Broadcasting"),
        ("howto.html", "How-To Guides"),
        ("post-production-workflows.html", "Post Production Workflows"),
            ]
    def _nav_li(h, lbl, base=base, active=active):
        cls = ' class="active"' if h == active else ''
        return f'<li><a href="{base}{h}"{cls}>{lbl}</a></li>'
    lis = "".join(_nav_li(h, lbl) for h, lbl in cats)
    mob_links = "".join(
        f'<a href="{base}{h}">{lbl}</a>' for h, lbl in cats)
    return f"""<nav class="nav">
  <div class="nav-inner">
    <a href="{base}featured.html" class="nav-logo">
      <img src="{base}assets/logo.png" alt="" onerror="this.style.display='none'" aria-hidden="true">
      <span>The Streamic</span>
    </a>
    <ul class="nav-links">{lis}</ul>
    <div class="nav-right">
      <a href="{base}about.html" class="nav-desk">About</a>
      <button class="nav-toggle" aria-label="Menu" onclick="document.querySelector('.nav-mob').classList.toggle('open')">
        <span></span><span></span><span></span>
      </button>
    </div>
  </div>
  <div class="nav-mob">{mob_links}<a href="{base}about.html">About</a><a href="{base}contact.html">Contact</a></div>
</nav>"""

def catbar(active_cat="", base=""):
    # Hidden during AdSense review — only AI Post visible via nav
    return ""

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
      <a href="{base}ai-post-production.html">AI in Broadcasting</a>
      <a href="{base}howto.html">How-To Guides</a>
      <a href="{base}post-production-workflows.html">Post Production Workflows</a>
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
      <h4>Follow</h4>
      <a href="https://twitter.com/thestreamic" target="_blank" rel="noopener noreferrer">&#x1D54F; @thestreamic</a>
      <a href="https://www.linkedin.com/company/thestreamic" target="_blank" rel="noopener noreferrer">in TheStreamic</a>
    </div>
  </div>
  <div class="footer-bottom">
    <span>© {yr} The Streamic &#8212; thestreamic.in. All rights reserved.</span>
    <span>Independent broadcast technology journalism. All trademarks belong to their respective owners.</span>
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

def news_grid(arts, base=""):
    """SSR bento grid &#8212; JS hydrates from news.json, this provides SEO content."""
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
    Cards: image top, category tag, title, source + date, Read button.
    Sources are round-robin interleaved for vendor diversity.
    """
    rss_pool = [a for a in arts if not a.get("is_editorial") and not a.get("editorial")]
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



def featured_page(arts):
    """
    Editorial homepage.
    Structure: Hero(1) + Editor Picks(4) + Why Exists + Deep Dives(7) + Guides(6) + Industry News(5)
    Deep Dives explicitly shows the 7 new long-form articles.
    Hero + Editor Picks uses the 5 original editorial analyses.
    """
    import re as _re

    # ── Split editorial into two pools ────────────────────────────────────
    # DEEP_DIVE_SLUGS: the 7 new topic articles — always go to the Deep Dives section
    DEEP_DIVE_SLUGS = {
        "future-of-ai-in-broadcast-deployment-2026",
        "cloud-broadcast-workflows-remote-production-2026",
        "ai-video-post-production-editing-vfx-automation-2026",
        "ip-broadcasting-smpte-st2110-engineering-guide-2026",
        "media-asset-management-ai-era-monetisation-2026",
        "live-production-ai-automation-real-time-broadcasting-2026",
        "broadcast-automation-systems-guide-2026",
    }

    editorial_all  = [a for a in arts if a.get("is_editorial") or a.get("editorial")]
    # Original analyses: long-form signed editorial — used in Hero + Editor Picks
    editorial_orig = [a for a in editorial_all if a["slug"] not in DEEP_DIVE_SLUGS]
    # Deep dive articles: always shown in the Deep Dives section
    editorial_deep = [a for a in editorial_all if a["slug"] in DEEP_DIVE_SLUGS]

    regular   = [a for a in arts if not a.get("is_editorial") and not a.get("editorial")]
    regular_scored = sorted(regular, key=lambda a: -_score_art(a))

    # ── Slot allocation ───────────────────────────────────────────────────
    # Hero: newest original editorial (the main feature article)
    hero_art     = editorial_orig[0] if editorial_orig else (regular_scored[0] if regular_scored else None)
    # Editor Picks: next 4 original editorial articles
    editor_picks = editorial_orig[1:4] if len(editorial_orig) > 1 else regular_scored[:3]
    # Deep Dives: all 7 new topic articles
    deep_dives   = editorial_deep  # show all 7

    used_slugs   = {hero_art["slug"]} if hero_art else set()
    used_slugs  |= {a["slug"] for a in editor_picks}
    used_slugs  |= {a["slug"] for a in deep_dives}
    # Industry news: 5 most recent RSS articles not already shown
    industry_news = [a for a in regular_scored if a["slug"] not in used_slugs][:5]

    title  = "The Streamic — AI in Broadcasting & Streaming Technology"
    desc   = "Expert analysis on AI automation, cloud workflows, and operational intelligence for broadcast and streaming professionals."
    canon  = f"{BASE_URL}/index.html"
    schema = json.dumps({
        "@context":"https://schema.org","@type":"WebPage",
        "name":"The Streamic","description":desc,"url":f"{BASE_URL}/index.html",
        "publisher":{"@type":"Organization","name":"The Streamic","url":BASE_URL}
    })

    # ── Hero section ──────────────────────────────────────────────────────
    hero_html = hero_block(hero_art) if hero_art else ""

    # ── Editor's Picks (4 cards, horizontal ed_card style) ───────────────
    picks_html = ""
    if editor_picks:
        picks_cards = "\n".join(ed_card(a) for a in editor_picks)
        picks_html = f"""<section class="editorial" style="padding:52px 0;border-bottom:1px solid var(--line)">
  <div class="sec-hdr" style="margin-bottom:28px">
    <h2>Editor&#8217;s Picks</h2>
    <span style="font-size:13px;color:var(--ink4);font-weight:400">Original analysis — independent of vendor influence</span>
  </div>
  <div class="ed-list">{picks_cards}</div>
</section>"""

    # ── Why Streamic Exists ───────────────────────────────────────────────
    why_html = """<section style="background:#f5f5f7;border-radius:16px;padding:44px 48px;margin:52px 0">
  <h2 style="font-family:var(--serif);font-size:clamp(22px,2.5vw,28px);letter-spacing:-.03em;color:var(--ink);margin:0 0 18px">Why Streamic Exists</h2>
  <p style="font-size:15px;line-height:1.75;color:var(--ink2);margin-bottom:16px">Streamic exists to help broadcasters, media teams, and streaming professionals make sense of a rapidly evolving technology landscape. The industry is being reshaped by cloud workflows, AI-driven automation, and changing audience expectations &#8212; but much of the available information is either too generic, overly technical, or fragmented across sources.</p>
  <p style="font-size:15px;line-height:1.75;color:var(--ink2);margin-bottom:24px">Streamic bridges that gap by delivering clear, practical, and relevant insights focused specifically on real-world broadcast and streaming operations.</p>
  <ul style="list-style:none;padding:0;margin:0 0 24px;display:flex;flex-direction:column;gap:12px">
    <li style="display:flex;align-items:flex-start;gap:12px">
      <span style="flex-shrink:0;width:28px;height:28px;background:var(--blue);border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:700;margin-top:1px">1</span>
      <div><strong style="font-size:14px;color:var(--ink)">Practical AI in Broadcasting</strong> <span style="font-size:14px;color:var(--ink3)">&#8212; how AI is actually used in production, playout, quality control, and content workflows</span></div>
    </li>
    <li style="display:flex;align-items:flex-start;gap:12px">
      <span style="flex-shrink:0;width:28px;height:28px;background:var(--blue);border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:700;margin-top:1px">2</span>
      <div><strong style="font-size:14px;color:var(--ink)">Cost Optimisation Without Compromise</strong> <span style="font-size:14px;color:var(--ink3)">&#8212; strategies to improve efficiency and reduce operational costs without replacing critical human expertise</span></div>
    </li>
    <li style="display:flex;align-items:flex-start;gap:12px">
      <span style="flex-shrink:0;width:28px;height:28px;background:var(--blue);border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:700;margin-top:1px">3</span>
      <div><strong style="font-size:14px;color:var(--ink)">Actionable Guides &amp; Troubleshooting</strong> <span style="font-size:14px;color:var(--ink3)">&#8212; step-by-step how-tos, setup guides, and real solutions for tools and systems used in daily broadcast environments</span></div>
    </li>
  </ul>
  <p style="font-size:14px;line-height:1.7;color:var(--ink3);border-top:1px solid var(--line);padding-top:18px;margin:0">Our goal is not just to report what&#39;s happening, but to explain why it matters and how it can be applied. Streamic is built for professionals who need clarity, not noise.</p>
</section>"""

    # ── Deep Dives (4 articles, editorial card style) ─────────────────────
    dives_html = ""
    if deep_dives:
        dives_cards = "\n".join(ed_card(a) for a in deep_dives)
        dives_html = f"""<section style="padding:52px 0;border-top:1px solid var(--line)">
  <div class="sec-hdr" style="margin-bottom:28px">
    <h2>Deep Dives &amp; Analysis</h2>
    <span style="font-size:13px;color:var(--ink4);font-weight:400">Long-form technical analysis for broadcast engineers</span>
  </div>
  <div class="ed-list">{dives_cards}</div>
</section>"""

    # ── How-To Guides teaser (6 items, compact list) ─────────────────────
    guides_teaser = """<section style="padding:52px 0;border-top:1px solid var(--line)">
  <div class="sec-hdr" style="margin-bottom:24px">
    <h2>How-To Guides</h2>
    <a href="howto.html" style="font-size:13px;font-weight:600;color:var(--blue)">View all guides &rarr;</a>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px">
    <a href="articles/guide-premiere-to-avid.html" style="display:block;padding:18px 20px;background:var(--bg);border-radius:10px;text-decoration:none;border:1px solid var(--line)">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--blue)">Post-Production</span>
      <p style="font-size:14px;font-weight:600;color:var(--ink);margin:6px 0 4px;line-height:1.35">Premiere Pro to Avid Media Composer</p>
      <span style="font-size:12px;color:var(--ink4)">&#128337; 8 min read</span>
    </a>
    <a href="articles/guide-vantage-nas-transcode.html" style="display:block;padding:18px 20px;background:var(--bg);border-radius:10px;text-decoration:none;border:1px solid var(--line)">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--blue)">Encoding</span>
      <p style="font-size:14px;font-weight:600;color:var(--ink);margin:6px 0 4px;line-height:1.35">Vantage: Transcode to MP4 on NAS</p>
      <span style="font-size:12px;color:var(--ink4)">&#128337; 6 min read</span>
    </a>
    <a href="articles/guide-vantage-aws-transcode.html" style="display:block;padding:18px 20px;background:var(--bg);border-radius:10px;text-decoration:none;border:1px solid var(--line)">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--blue)">Cloud</span>
      <p style="font-size:14px;font-weight:600;color:var(--ink);margin:6px 0 4px;line-height:1.35">Vantage: Output to AWS S3</p>
      <span style="font-size:12px;color:var(--ink4)">&#128337; 6 min read</span>
    </a>
    <a href="articles/guide-avid-media-central-health-check.html" style="display:block;padding:18px 20px;background:var(--bg);border-radius:10px;text-decoration:none;border:1px solid var(--line)">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--blue)">Avid</span>
      <p style="font-size:14px;font-weight:600;color:var(--ink);margin:6px 0 4px;line-height:1.35">MediaCentral Health Check</p>
      <span style="font-size:12px;color:var(--ink4)">&#128337; 7 min read</span>
    </a>
    <a href="articles/guide-audio-conform-avid-protools.html" style="display:block;padding:18px 20px;background:var(--bg);border-radius:10px;text-decoration:none;border:1px solid var(--line)">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--blue)">Audio</span>
      <p style="font-size:14px;font-weight:600;color:var(--ink);margin:6px 0 4px;line-height:1.35">Audio Conform: Avid to Pro Tools</p>
      <span style="font-size:12px;color:var(--ink4)">&#128337; 9 min read</span>
    </a>
    <a href="articles/guide-avid-strawberry.html" style="display:block;padding:18px 20px;background:var(--bg);border-radius:10px;text-decoration:none;border:1px solid var(--line)">
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--blue)">MAM</span>
      <p style="font-size:14px;font-weight:600;color:var(--ink);margin:6px 0 4px;line-height:1.35">Strawberry PAM + Avid Workflow</p>
      <span style="font-size:12px;color:var(--ink4)">&#128337; 10 min read</span>
    </a>
  </div>
</section>"""

    # ── Industry News — 20-card round-robin from broadcast categories ─────
    # Interleave sources so no vendor dominates: Avid,Grass Valley,EVS,Harmonic,
    # Pebble,Ross,Vizrt,Maxon,MAM,IP,streaming,playout,newsroom etc.
    news_items_html = ""
    if arts:
        # Round-robin by source_domain — guarantees variety across vendors
        from collections import defaultdict
        _buckets = defaultdict(list)
        for a in arts:
            if a["slug"] in used_slugs: continue
            src = a.get("source_domain","").replace("https://","").replace("www.","").split("/")[0].lower()
            _buckets[src].append(a)
        # Sort buckets newest-first per source
        _bucket_list = sorted(_buckets.values(), key=lambda b: b[0].get("published",""), reverse=True)
        rss_cards = []
        while len(rss_cards) < 20 and _bucket_list:
            for bucket in list(_bucket_list):
                if bucket:
                    rss_cards.append(bucket.pop(0))
                    if len(rss_cards) >= 20: break
            _bucket_list = [b for b in _bucket_list if b]

        cards_html = ""
        for a in rss_cards:
            src = e(a.get("source_domain","").replace("https://","").replace("www.","").split("/")[0].upper())
            src_url = a.get("source_url") or a.get("url") or f"articles/{a['slug']}.html"
            art_url = f"articles/{a['slug']}.html"
            cat = a.get("category","featured")
            cat_color = {"streaming":"#0066cc","cloud":"#5856d6","graphics":"#FF9500",
                         "playout":"#34C759","infrastructure":"#636366",
                         "ai-post-production":"#FF2D55","newsroom":"#b8860b"}.get(cat,"#1d1d1f")
            img = eu(a.get("image_url",""))
            card_title = e(a.get("title",""))
            dt = d(a.get("published",""))
            dek_raw = smart_dek(a)
            dek = e(dek_raw)
            cards_html += f"""<a href="{e(art_url)}" class="rss-card" style="text-decoration:none">
  <div class="rss-card-img">
    <img src="{img}" alt="{card_title}" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'">
  </div>
  <div class="rss-card-body">
    <span class="rss-card-src" style="color:{cat_color}">{src}</span>
    <h3 class="rss-card-hl">{card_title}</h3>
    <p class="rss-card-dek">{dek}</p>
    <div class="rss-card-foot">
      <time>{dt}</time>
      <span class="rss-card-src-link"><a href="{e(src_url)}" target="_blank" rel="noopener noreferrer nofollow" onclick="event.stopPropagation()">Original source ↗</a></span>
    </div>
  </div>
</a>"""

        news_items_html = f"""<section class="rss-section">
  <div class="sec-hdr" style="margin-bottom:24px">
    <h2>Latest Broadcast &amp; Media Technology News</h2>
  </div>
  <div class="rss-grid">{cards_html}</div>
</section>"""

    return f"""{head(title, desc, canon, og_img=(hero_art or {}).get('image_url',''))}
<body data-category="featured">
{nav("featured.html")}
<main>
  <div class="w">
    {hero_html}
    {picks_html}
    {news_items_html}
    {dives_html}
    {guides_teaser}
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
        grid_html = news_grid(rest) if rest else ""

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

    # ── AI-enhanced articles: has h2 structure OR substantial word count ──
    # Return the full body without ANY stripping — Gemini output is complete.
    if "<h2>" in body_html or "<h3>" in body_html or word_count > 300:
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

    if len(cs_words) >= 120 and not _is_boilerplate(cs_raw):
        mid = len(cs_words) // 2
        for i in range(mid, min(mid + 25, len(cs_words))):
            if cs_words[i].endswith((".", "?")): mid = i + 1; break
        p1 = " ".join(cs_words[:mid])
        p2 = " ".join(cs_words[mid:])
        return f"<p>{p1}</p>\n" + (f"<p>{p2}</p>" if p2 else "")

    # Raw paragraphs — limit to 4, strip boilerplate
    paras = re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.DOTALL)
    clean = []
    for p in paras:
        txt = re.sub(r"<[^>]+>", " ", p).strip()
        txt = re.sub(r"\s+", " ", txt)
        if len(txt.split()) < 8: continue
        if _is_boilerplate(txt): continue
        clean.append(f"<p>{p.strip()}</p>")

    if clean:
        return "\n".join(clean[:4])   # limit raw RSS to 4 paragraphs

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
    <div class="art-body">{body}{editors_note}</div>
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
<main><div class="w" style="padding:52px 0 80px;max-width:780px">
<h1 style="font-family:var(--serif);font-size:clamp(28px,4vw,44px);margin-bottom:16px;letter-spacing:-.5px">About The Streamic</h1>
<p style="font-size:17px;color:var(--ink2);line-height:1.65;margin-bottom:20px">The Streamic is an independent broadcast and streaming technology publication covering the tools, standards, and workflows that shape modern media production and delivery.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:20px">We publish original editorial analysis on topics including IP infrastructure (SMPTE ST 2110, NMOS), cloud-native production, operational AI, real-time graphics, playout automation, and newsroom technology. Our readership includes broadcast engineers, operations managers, technology directors, and media industry professionals.</p>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">Our editorial approach</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:16px">We write original analysis &#8212; not copied content. Our industry news coverage credits and links to original reporting while adding Streamic editorial context. Long-form articles represent our editorial team&#39;s independent perspective on industry developments.</p>
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
<p style="margin-bottom:16px">Original editorial content on The Streamic is copyright © The Streamic. Industry news briefings credit and link to their original sources. All third-party trademarks are the property of their respective owners.</p>
<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Disclaimer</h2>
<p style="margin-bottom:16px">Content is provided for informational purposes. We make no warranties about accuracy or completeness. The Streamic is not responsible for third-party content linked from this site.</p>
<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">External Links</h2>
<p style="margin-bottom:16px">We link to external sources with rel="nofollow". We are not responsible for the content or privacy practices of linked websites.</p>
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
<main><div class="w" style="padding:52px 0 80px;max-width:780px">
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
        ("ai-post-production.html","daily","0.9"),
        ("howto.html","weekly","0.85"),("post-production-workflows.html","weekly","0.90"),
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
    print(f"  After dedup: {len(arts)} unique articles")

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

    print(f"  Total articles loaded: {len(arts)}")

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
    written = 0
    for a in arts:
        html  = article_page(a)
        if a["slug"] not in visible_slugs:
            html = html.replace(
                '<meta name="robots" content="index,follow">',
                '<meta name="robots" content="noindex,nofollow">'
            )
        slug_ = a.get("slug","")
        w(os.path.join(ARTS_D, f"{slug_}.html"), html)
        written += 1
        leg = a.get("legacy_slug")
        if leg and leg != slug_:
            w(os.path.join(ARTS_D, f"{leg}.html"), html)
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
    w(os.path.join(DOCS,"how-to.html"),           howto_page())
    w(os.path.join(DOCS,"vlog.html"),             vlog_page())
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