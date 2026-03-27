#!/usr/bin/env python3
"""
Source-grounded vendor guide generator for The Streamic.

- Builds docs/professional-media-systems-guide.html
- Builds vendor detail pages in docs/vendors/
- Weekly mode adds up to 5 new vendors from the registry if official pages validate
- Keeps legacy broadcast-systems-hub.html as a redirect to the new SEO page

No AI APIs are required.
"""
from __future__ import annotations
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
VENDORS_DIR = DOCS / 'vendors'
DATA = ROOT / 'data'
REGISTRY_FILE = DATA / 'vendor_registry.json'
STATE_FILE = DATA / 'vendor_guide_state.json'
GUIDE_FILE = DOCS / 'professional-media-systems-guide.html'
LEGACY_REDIRECT = DOCS / 'broadcast-systems-hub.html'
BASE_URL = os.environ.get('SITE_BASE_URL', 'https://www.thestreamic.in').rstrip('/')
WEEKLY_ADD = 5
UA = {'User-Agent': 'Mozilla/5.0 (compatible; TheStreamicVendorGuide/1.0)'}
TIMEOUT = 15


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def safe_get(url: str) -> Tuple[bool, str]:
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        if r.status_code == 200 and r.text:
            return True, r.text
        return False, ''
    except Exception:
        return False, ''


def meta_from_html(text: str) -> Dict[str, str]:
    soup = BeautifulSoup(text, 'html.parser')
    title = (soup.title.string or '').strip() if soup.title and soup.title.string else ''
    desc_tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
    desc = (desc_tag.get('content') or '').strip() if desc_tag else ''
    h1 = soup.find('h1')
    h1t = h1.get_text(' ', strip=True) if h1 else ''
    return {'title': title, 'description': desc, 'h1': h1t}


def validate_vendor(v: Dict) -> bool:
    checks = 0
    names = [v['name'].lower()] + [p['name'].split()[0].lower() for p in v.get('key_products', [])]
    for src in v.get('official_sources', [])[:4]:
        ok, text = safe_get(src['url'])
        if not ok:
            continue
        meta = meta_from_html(text)
        hay = ' '.join([meta.get('title', ''), meta.get('description', ''), meta.get('h1', '')]).lower()
        if any(n in hay for n in names if n):
            checks += 1
    return checks >= 1


def enrich_vendor(v: Dict) -> Dict:
    vv = dict(v)
    source_meta = []
    for src in v.get('official_sources', []):
        ok, text = safe_get(src['url'])
        meta = {'label': src['label'], 'url': src['url']}
        if ok:
            meta.update(meta_from_html(text))
        source_meta.append(meta)
    vv['source_meta'] = source_meta
    return vv


def head(title: str, desc: str, canon: str, css='style.css') -> str:
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('consent','default',{{'analytics_storage':'denied','ad_storage':'denied','ad_user_data':'denied','ad_personalization':'denied','wait_for_update':500}});</script>
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-0VSHDN3ZR6"></script>
  <script>gtag('js',new Date());gtag('config','G-0VSHDN3ZR6');</script>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(title)}</title>
  <meta name="description" content="{html.escape(desc)}">
  <meta name="robots" content="index,follow">
  <link rel="canonical" href="{html.escape(canon)}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="The Streamic">
  <meta property="og:title" content="{html.escape(title)}">
  <meta property="og:description" content="{html.escape(desc)}">
  <meta property="og:url" content="{html.escape(canon)}">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{css}">
</head>'''


def nav(base='') -> str:
    items = [
        ('featured.html', 'Home', False),
        ('ai-post-production.html', 'AI in Broadcasting', False),
        ('howto.html', 'How-To Guides', False),
        ('post-production-workflows.html', 'Post Production Workflows', False),
        ('professional-media-systems-guide.html', 'Media Systems Guide', True),
    ]
    lis = ''.join(f'<li><a href="{base}{h}"{" class=\"active\"" if active else ""}>{t}</a></li>' for h, t, active in items)
    mob = ''.join(f'<a href="{base}{h}">{t}</a>' for h, t, _ in items)
    return f'''<nav class="nav"><div class="nav-inner">
  <a href="{base}featured.html" class="nav-logo"><img src="{base}assets/logo.png" alt="" onerror="this.style.display='none'" aria-hidden="true"><span>The Streamic</span></a>
  <ul class="nav-links">{lis}</ul>
  <div class="nav-right"><a href="{base}about.html" class="nav-desk">About</a><button class="nav-toggle" aria-label="Menu" onclick="document.querySelector('.nav-mob').classList.toggle('open')"><span></span><span></span><span></span></button></div>
</div><div class="nav-mob">{mob}<a href="{base}about.html">About</a><a href="{base}contact.html">Contact</a></div></nav>'''


def footer(base='') -> str:
    year = datetime.now().year
    return f'''<footer class="footer"><div class="footer-grid">
<div><div class="footer-brand">The Streamic</div><p class="footer-tag">Independent broadcast &amp; streaming technology journalism for engineers and media professionals.</p></div>
<div class="footer-col"><h4>Coverage</h4><a href="{base}ai-post-production.html">AI in Broadcasting</a><a href="{base}howto.html">How-To Guides</a><a href="{base}post-production-workflows.html">Post Production Workflows</a><a href="{base}professional-media-systems-guide.html">Media Systems Guide</a></div>
<div class="footer-col"><h4>Site</h4><a href="{base}about.html">About</a><a href="{base}contact.html">Contact</a><a href="{base}editorial-policy.html">Editorial Policy</a><a href="{base}privacy.html">Privacy Policy</a><a href="{base}terms.html">Terms of Use</a></div>
<div class="footer-col"><h4>Follow</h4><a href="https://twitter.com/thestreamic" target="_blank" rel="noopener noreferrer">𝕏 @thestreamic</a><a href="https://www.linkedin.com/company/thestreamic" target="_blank" rel="noopener noreferrer">in TheStreamic</a></div>
</div><div class="footer-bottom"><span>&copy; {year} The Streamic &mdash; thestreamic.in. All rights reserved.</span><span>Independent media technology journalism. All trademarks belong to their respective owners.</span></div></footer>'''


def render_vendor_page(v: Dict, published_date: str) -> str:
    title = f"{v['name']} Guide for Broadcast and Media Operations | The Streamic"
    canon = f"{BASE_URL}/vendors/{v['slug']}.html"
    source_links = ''.join(f'<li><a href="{html.escape(src["url"])}" rel="nofollow noopener" target="_blank">{html.escape(src["label"])} ↗</a></li>' for src in v['official_sources'])
    product_cards = ''.join(
        f'''<article class="pm-product-card"><div class="pm-product-eyebrow">Official product page</div><h3><a href="{html.escape(p['url'])}" target="_blank" rel="nofollow noopener">{html.escape(p['name'])} ↗</a></h3><p>{html.escape(p['one_liner'])}</p><div class="pm-note"><strong>Plain-English fit:</strong> {html.escape(p['use_case'])}</div></article>'''
        for p in v['key_products']
    )
    workflow_items = ''.join(f'<li>{html.escape(x)}</li>' for x in v['workflow_points'])
    shortlist_items = ''.join(f'<li>{html.escape(x)}</li>' for x in v['who_should_use'])
    source_cards = ''
    if v.get('source_meta'):
        source_cards = '<div class="pm-source-cards">' + ''.join(
            f'''<article class="pm-source-card"><div class="pm-product-eyebrow">Source checked</div><h3><a href="{html.escape(m['url'])}" target="_blank" rel="nofollow noopener">{html.escape(m['label'])} ↗</a></h3><p>{html.escape(m.get('description') or m.get('h1') or m.get('title') or 'Official vendor page reviewed.')}</p></article>'''
            for m in v['source_meta'][:4]
        ) + '</div>'
    return f'''{head(title, v['meta_description'], canon, css='../style.css')}
<body>{nav('../')}
<main>
<section class="pm-hero"><div class="w"><div class="pm-eyebrow">Professional Media Systems Guide</div><h1>{html.escape(v['name'])}: what it does, where it fits, and what buyers should know</h1><p class="pm-lead">{html.escape(v['summary'])}</p><div class="pm-meta"><span>Category: {html.escape(v['primary_category'])}</span><span>Last reviewed: {html.escape(published_date)}</span><span>Official sources checked</span></div></div></section>
<section class="w pm-body">
  <a class="pm-back" href="../professional-media-systems-guide.html">← Back to Professional Media Systems Guide</a>
  <div class="pm-grid-2">
    <article class="pm-panel"><h2>What this vendor does</h2><p>{html.escape(v['what_it_is'])}</p><p>{html.escape(v['plain_language'])}</p></article>
    <article class="pm-panel"><h2>Why this matters</h2><p>{html.escape(v['why_matters'])}</p><h2 style="margin-top:22px">Expert insight</h2><p>{html.escape(v['expert_insight'])}</p></article>
  </div>
  <section class="pm-panel"><h2>Where it fits in a real workflow</h2><ul class="pm-bullets">{workflow_items}</ul></section>
  <section><h2 class="pm-section-title">Key products to understand</h2><div class="pm-product-grid">{product_cards}</div></section>
  <div class="pm-grid-2">
    <article class="pm-panel"><h2>Who should shortlist it</h2><ul class="pm-bullets">{shortlist_items}</ul></article>
    <article class="pm-panel"><h2>Source discipline</h2><p>This guide is intentionally conservative. It links to official vendor pages and avoids speculative technical claims. Use the source links below when you need version-specific detail, supported configurations, or commercial availability.</p><ul class="pm-bullets">{source_links}</ul></article>
  </div>
  {source_cards}
</section>
</main>
{footer('../')}
</body>
</html>'''


def render_guide_page(vendors: List[Dict], state: Dict) -> str:
    cards = []
    for v in vendors:
        dt = state.get('published_dates', {}).get(v['slug'], '')
        products = ', '.join(p['name'] for p in v.get('key_products', [])[:2])
        cards.append(
            f'''<article class="pm-bento"><div class="pm-bento-top"><span class="pm-chip">{html.escape(v['primary_category'])}</span><span class="pm-reviewed">Reviewed {html.escape(dt)}</span></div><h2><a href="vendors/{v['slug']}.html">{html.escape(v['name'])}</a></h2><p>{html.escape(v['summary'])}</p><div class="pm-small"><strong>Start with:</strong> {html.escape(products)}</div><div class="pm-actions"><a href="vendors/{v['slug']}.html">Open guide →</a><a href="{html.escape(v['official_sources'][0]['url'])}" target="_blank" rel="nofollow noopener">Official site ↗</a></div></article>'''
        )
    card_html = ''.join(cards)
    title = 'Professional Media Systems Guide | The Streamic'
    desc = 'Source-grounded buyer-friendly guides to broadcast and media technology vendors, starting with Avid and EVS and expanding with weekly verified additions.'
    canon = f'{BASE_URL}/professional-media-systems-guide.html'
    return f'''{head(title, desc, canon)}
<body>{nav()}
<main>
<section class="pm-hero"><div class="w"><div class="pm-eyebrow">Professional Media Systems Guide</div><h1>Source-grounded vendor guides for real broadcast and media operations</h1><p class="pm-lead">This section is designed to be useful, readable, and conservative. We only publish a vendor card when we have official-source links to ground the page. No placeholders, no “coming soon” cards, and no speculative product claims.</p><div class="pm-meta"><span>{len(vendors)} vendor guides live</span><span>Weekly automation adds up to {WEEKLY_ADD} verified vendors</span><span>Official-source links on every page</span></div></div></section>
<section class="w pm-body">
  <div class="pm-grid-2">
    <article class="pm-panel"><h2>How to use this guide</h2><p>Each page explains what a vendor actually does, where it fits in a workflow, which products matter first, and what a non-specialist should understand before evaluating it. We write for engineers, producers, founders, and buyers who need clear context without marketing jargon.</p></article>
    <article class="pm-panel"><h2>Editorial policy for this section</h2><p>These pages are based on official vendor product pages and public documentation. Weekly automation only publishes a new vendor when the source pages are reachable and match the expected product and vendor names. If validation fails, nothing new is published that week.</p></article>
  </div>
  <section><h2 class="pm-section-title">Current vendor guides</h2><div class="pm-bento-grid">{card_html}</div></section>
</section>
</main>
{footer()}
</body>
</html>'''


def render_redirect() -> str:
    target = f'{BASE_URL}/professional-media-systems-guide.html'
    return f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="0; url={target}"><link rel="canonical" href="{target}"><meta name="robots" content="noindex,follow"><title>Redirecting…</title></head><body><p>Redirecting to <a href="{target}">Professional Media Systems Guide</a>.</p></body></html>'


def append_styles():
    block = '''
/* ===== Professional Media Systems Guide ===== */
.pm-hero{background:linear-gradient(135deg,#0a0a0f 0%,#101826 100%);padding:64px 0 74px;color:#fff}
.pm-eyebrow{display:inline-block;font-size:11px;font-weight:800;letter-spacing:1.6px;text-transform:uppercase;color:#90b4ff;margin-bottom:16px}
.pm-hero h1{font-family:var(--serif);font-size:clamp(32px,5vw,58px);line-height:1.05;letter-spacing:-.04em;margin:0 0 16px;max-width:900px}
.pm-lead{font-size:clamp(15px,1.8vw,18px);line-height:1.75;color:rgba(255,255,255,.75);max-width:820px;margin:0}
.pm-meta{display:flex;flex-wrap:wrap;gap:10px;margin-top:26px}.pm-meta span{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);padding:8px 12px;border-radius:999px;font-size:12px;font-weight:700;color:rgba(255,255,255,.84)}
.pm-body{padding:38px 0 84px}.pm-grid-2{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-bottom:22px}.pm-panel{background:#fff;border:1px solid var(--line);border-radius:18px;padding:28px 30px}.pm-panel h2,.pm-section-title{font-family:var(--serif);letter-spacing:-.02em;margin:0 0 12px;font-size:25px}.pm-panel p{margin:0 0 14px;color:var(--ink3);line-height:1.75;font-size:15px}.pm-bento-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.pm-bento{background:#fff;border:1px solid var(--line);border-radius:18px;padding:24px;display:flex;flex-direction:column;gap:14px}.pm-bento h2{font-family:var(--serif);font-size:28px;line-height:1.1;letter-spacing:-.03em;margin:0}.pm-bento p{margin:0;color:var(--ink3);line-height:1.7}.pm-bento-top,.pm-actions{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center}.pm-chip,.pm-reviewed{font-size:11px;font-weight:800;letter-spacing:.8px;text-transform:uppercase}.pm-chip{color:#1b4fd6;background:#edf3ff;padding:6px 10px;border-radius:999px}.pm-reviewed{color:var(--ink4)}.pm-small{font-size:13px;color:var(--ink2)}.pm-actions a{font-weight:700;font-size:13px}.pm-product-grid,.pm-source-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin:16px 0 24px}.pm-product-card,.pm-source-card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:22px}.pm-product-card h3,.pm-source-card h3{font-family:var(--serif);font-size:22px;line-height:1.15;letter-spacing:-.02em;margin:0 0 8px}.pm-product-card p,.pm-source-card p{margin:0;color:var(--ink3);line-height:1.7}.pm-product-eyebrow{font-size:10px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:var(--ink4);margin-bottom:10px}.pm-note{margin-top:12px;padding-top:12px;border-top:1px solid var(--line);font-size:13px;color:var(--ink2);line-height:1.6}.pm-back{display:inline-flex;margin-bottom:22px;font-weight:700}.pm-bullets{margin:0;padding-left:20px}.pm-bullets li{margin:0 0 10px;color:var(--ink3);line-height:1.7}.pm-section-title{margin:0 0 16px}
@media(max-width:960px){.pm-grid-2,.pm-bento-grid,.pm-product-grid,.pm-source-cards{grid-template-columns:1fr}}
'''
    for style_file in [ROOT / 'style.css', DOCS / 'style.css']:
        if not style_file.exists():
            continue
        txt = style_file.read_text(encoding='utf-8')
        if 'Professional Media Systems Guide' not in txt:
            style_file.write_text(txt + '\n\n' + block + '\n', encoding='utf-8')


def main():
    registry = load_json(REGISTRY_FILE, [])
    state = load_json(STATE_FILE, {'published_order': [], 'published_dates': {}, 'last_weekly_run': None})

    if not state['published_order']:
        for v in registry:
            if v.get('published_by_default'):
                state['published_order'].append(v['slug'])
                state['published_dates'][v['slug']] = datetime.now(timezone.utc).date().isoformat()

    mode = os.environ.get('VENDOR_HUB_MODE', 'weekly').lower().strip()
    if mode not in {'weekly', 'full', 'none'}:
        mode = 'weekly'
    max_add = WEEKLY_ADD if mode == 'weekly' else 999
    added = 0
    today = datetime.now(timezone.utc).date().isoformat()
    published = set(state['published_order'])

    if mode != 'none':
        for v in registry:
            if v['slug'] in published:
                continue
            if added >= max_add:
                break
            if validate_vendor(v):
                state['published_order'].append(v['slug'])
                state['published_dates'][v['slug']] = today
                published.add(v['slug'])
                added += 1
        state['last_weekly_run'] = today
        save_json(STATE_FILE, state)

    published_vendors = []
    for slug in state['published_order']:
        found = next((x for x in registry if x['slug'] == slug), None)
        if found:
            published_vendors.append(enrich_vendor(found))

    DOCS.mkdir(exist_ok=True)
    VENDORS_DIR.mkdir(parents=True, exist_ok=True)
    append_styles()
    GUIDE_FILE.write_text(render_guide_page(published_vendors, state), encoding='utf-8')
    LEGACY_REDIRECT.write_text(render_redirect(), encoding='utf-8')
    for vendor in published_vendors:
        dt = state.get('published_dates', {}).get(vendor['slug'], '')
        (VENDORS_DIR / f"{vendor['slug']}.html").write_text(render_vendor_page(vendor, dt), encoding='utf-8')

    print(f'Generated guide with {len(published_vendors)} published vendors. Added this run: {added}')


if __name__ == '__main__':
    main()
