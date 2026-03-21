/* ═══════════════════════════════════════════════════════════════
   THE STREAMIC · main.js  v3
   ─────────────────────────────────────────────────────────────
   DATA FLOW:
     1. Fetch data/news.json  → raw RSS items (title, url, teaser, source)
     2. For EACH item, check  data/summaries/<slug>.json
        • If found  → use card_summary (330-word Groq analysis)
        • If absent → fall back to item.teaser
     3. Render into #bentoGridLarge (12-col Apple bento grid)
        • First card  → 8 col, vertical (big image top + full summary)
        • Other cards → 4 col, horizontal (image left, text right)
   ─────────────────────────────────────────────────────────────
   All external links: rel="noopener noreferrer nofollow"
   CTA copy: "Read Technical Analysis →"
═══════════════════════════════════════════════════════════════ */
(() => {
  'use strict';

  const BUST    = Date.now();
  const BATCH   = 12;
  const SUM_MAX = 1950;   // clip Groq summaries
  const TEAS_MAX= 320;    // clip raw teasers

  const FALLBACK = {
    featured:            'https://images.unsplash.com/photo-1598488035139-bdbb2231ce04?w=900&q=80',
    newsroom:            'https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=900&q=80',
    playout:             'https://images.unsplash.com/photo-1478737270239-2f02b77fc618?w=900&q=80',
    infrastructure:      'https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=900&q=80',
    graphics:            'https://images.unsplash.com/photo-1504639725590-34d0984388bd?w=900&q=80',
    cloud:               'https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=900&q=80',
    streaming:           'https://images.unsplash.com/photo-1499364615650-ec38552f4f34?w=900&q=80',
    'ai-post-production':'https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=900&q=80',
  };

  let allItems     = [];
  let shownCount   = 0;
  let lazyObserver = null;
  let sumCache     = {};   // slug → data | null

  // ── utils ──────────────────────────────────────────────────
  function fb(cat) {
    return FALLBACK[(cat||'').toLowerCase().trim()] || FALLBACK.featured;
  }
  function isUrl(u) {
    u = (u||'').trim().toLowerCase();
    return u.startsWith('http://') || u.startsWith('https://');
  }
  function pickImg(item) { return isUrl(item.image) ? item.image : fb(item.category); }
  function clip(s, max) {
    if (!s) return '';
    s = s.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
    return s.length > max ? s.slice(0,max).replace(/\s+\S*$/,'')+'…' : s;
  }
  function slugify(title, pub) {
    const d = (pub||'').slice(0,10);
    const t = (title||'').toLowerCase().replace(/[^a-z0-9\s]/g,'').replace(/\s+/g,'-').slice(0,60);
    return d ? d+'-'+t : t;
  }

  // ── MODULE 1: summary merge ────────────────────────────────
  async function enrichItem(item) {
    const slug = item.slug || slugify(item.title, item.published || item.pubDate);

    if (sumCache[slug] !== undefined) {
      const c = sumCache[slug];
      return { ...item, displayText: c ? clip(c.card_summary||'', SUM_MAX) : clip(item.teaser||'', TEAS_MAX), hasGroq: !!c };
    }

    try {
      const r = await fetch('data/summaries/'+slug+'.json?v='+BUST);
      if (r.ok) {
        const d = await r.json();
        sumCache[slug] = d;
        return { ...item, displayText: clip(d.card_summary||'', SUM_MAX), hasGroq: true };
      }
    } catch(_) {}

    sumCache[slug] = null;
    return { ...item, displayText: clip(item.teaser||'', TEAS_MAX), hasGroq: false };
  }

  async function enrichBatch(items) {
    return Promise.all(items.map(enrichItem));
  }

  // ── lazy images ─────────────────────────────────────────────
  function setupObserver() {
    if (!('IntersectionObserver' in window)) return null;
    return new IntersectionObserver((entries, obs) => {
      entries.forEach(e => {
        if (e.isIntersecting && e.target.dataset.src) {
          e.target.src = e.target.dataset.src;
          e.target.classList.remove('lz');
          obs.unobserve(e.target);
        }
      });
    }, { rootMargin:'80px', threshold:0.01 });
  }

  function makeImg(url, alt) {
    const img = document.createElement('img');
    img.alt = alt||'';
    if (lazyObserver) {
      img.dataset.src = url;
      img.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
      img.classList.add('lz');
      lazyObserver.observe(img);
    } else { img.src=url; img.loading='lazy'; }
    return img;
  }

  // ── MODULE 2: card builders ─────────────────────────────────

  /* FEATURED CARD — 8/12 cols, vertical layout */
  function buildFeatured(item) {
    const li = document.createElement('li');
    li.className = 'bento-grid-item';

    const url   = isUrl(item.url) ? item.url : (isUrl(item.link) ? item.link : '#');
    const title = (item.title||'Untitled').trim();
    const cat   = (item.category||'featured').toLowerCase().trim();
    const src   = (item.source||'').trim();
    const text  = item.displayText || clip(item.teaser||'', SUM_MAX);
    const catLbl= cat.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase());

    const imgWrap = el('div','bento-img-wrap bento-img-featured');
    const ia = link(url); ia.setAttribute('tabindex','-1'); ia.setAttribute('aria-hidden','true');
    ia.appendChild(makeImg(pickImg(item),title)); imgWrap.appendChild(ia);

    const body = el('div','bento-body bento-body-featured');

    const tagEl = el('span','bento-cat-tag'); tagEl.textContent = catLbl;
    body.appendChild(tagEl);

    const h2 = el('h2','bento-hl bento-hl-featured');
    const ha = link(url); ha.textContent = title; h2.appendChild(ha);
    body.appendChild(h2);

    if (item.hasGroq) {
      const badge = el('span','bento-groq-badge'); badge.textContent = '✦ Technical Analysis';
      body.appendChild(badge);
    }

    if (text) {
      const p = el('p','bento-sum bento-sum-featured'); p.textContent = text;
      body.appendChild(p);
    }

    const foot = buildFooter(src, url, true);
    body.appendChild(foot);

    li.appendChild(imgWrap);
    li.appendChild(body);
    return li;
  }

  /* STANDARD CARD — 4/12 cols, horizontal layout */
  function buildStandard(item) {
    const li = document.createElement('li');
    li.className = 'bento-grid-item bento-standard';

    const url   = isUrl(item.url) ? item.url : (isUrl(item.link) ? item.link : '#');
    const title = (item.title||'Untitled').trim();
    const cat   = (item.category||'featured').toLowerCase().trim();
    const src   = (item.source||'').trim();
    const text  = item.displayText || clip(item.teaser||'', TEAS_MAX);
    const catLbl= cat.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase());

    const imgWrap = el('div','bento-img-wrap bento-img-std');
    const ia = link(url); ia.setAttribute('tabindex','-1'); ia.setAttribute('aria-hidden','true');
    ia.appendChild(makeImg(pickImg(item),title)); imgWrap.appendChild(ia);

    const body = el('div','bento-body bento-body-std');
    const tagEl = el('span','bento-cat-tag'); tagEl.textContent = catLbl;
    body.appendChild(tagEl);

    const h3 = el('h3','bento-hl bento-hl-std');
    const ha = link(url); ha.textContent = title; h3.appendChild(ha);
    body.appendChild(h3);

    if (text) {
      const p = el('p','bento-sum bento-sum-std'); p.textContent = text;
      body.appendChild(p);
    }

    const foot = buildFooter(src, url, false);
    body.appendChild(foot);

    li.appendChild(imgWrap);
    li.appendChild(body);
    return li;
  }

  function buildFooter(src, url, featured) {
    const foot = el('div','bento-foot');
    if (src) {
      const s = el('span','bento-source');
      s.textContent = src.replace(/https?:\/\//,'').replace('www.','').split('/')[0].toUpperCase();
      foot.appendChild(s);
    }
    if (url !== '#') {
      const btn = link(url);
      btn.className   = featured ? 'bento-cta-featured' : 'bento-cta';
      btn.textContent = 'Read Technical Analysis \u2192';
      foot.appendChild(btn);
    }
    return foot;
  }

  // helpers
  function el(tag, cls) { const e=document.createElement(tag); if(cls)e.className=cls; return e; }
  function link(url) {
    const a = document.createElement('a');
    a.href=''+url; a.target='_blank'; a.rel='noopener noreferrer nofollow';
    return a;
  }

  // ── render ──────────────────────────────────────────────────
  async function renderBatch(grid) {
    const slice = allItems.slice(shownCount, shownCount+BATCH);
    if (!slice.length) { hideMore(); return; }
    const enriched = await enrichBatch(slice);
    const frag = document.createDocumentFragment();
    enriched.forEach((item, idx) => {
      frag.appendChild(
        (shownCount+idx === 0) ? buildFeatured(item) : buildStandard(item)
      );
    });
    grid.appendChild(frag);
    shownCount += slice.length;
    if (shownCount >= allItems.length) hideMore();
  }

  function hideMore() {
    const b = document.getElementById('ts-more');
    if (b && b.parentElement) b.parentElement.style.display='none';
  }

  function addMoreBtn(grid) {
    if (document.getElementById('ts-more')) return;
    const wrap = el('div',''); wrap.style.cssText='margin:40px 0;text-align:center';
    const btn  = el('button',''); btn.id='ts-more';
    btn.textContent='Load More Stories';
    btn.style.cssText='padding:13px 40px;border-radius:999px;border:1.5px solid var(--line);background:var(--white);color:var(--ink);font-size:14px;font-weight:600;cursor:pointer;font-family:var(--font);letter-spacing:-0.02em;transition:all .15s';
    btn.onmouseover=()=>{btn.style.background='var(--ink)';btn.style.color='#fff';};
    btn.onmouseout =()=>{btn.style.background='var(--white)';btn.style.color='var(--ink)';};
    btn.onclick    =()=>renderBatch(grid);
    wrap.appendChild(btn); grid.parentElement.appendChild(wrap);
  }

  // ── data ────────────────────────────────────────────────────
  async function loadNews() {
    for (const p of ['data/news.json?v='+BUST, '/data/news.json?v='+BUST]) {
      try {
        const r = await fetch(p); if (!r.ok) continue;
        const raw = await r.json();
        if (Array.isArray(raw)) return { featured_priority:raw.slice(0,6), items:raw.slice(6) };
        if (raw.items!==undefined) return raw;
        const flat=[];
        Object.entries(raw).forEach(([cat,lst])=>(lst||[]).forEach(it=>flat.push({...it,category:it.category||cat})));
        flat.sort((a,b)=>(b.pubDate||b.published||'').localeCompare(a.pubDate||a.published||''));
        return { featured_priority:flat.slice(0,6), items:flat.slice(6) };
      } catch(_) {}
    }
    throw new Error('news.json not reachable');
  }

  function filterCat(items, cat) {
    if (!cat||cat==='featured') return items;
    return items.filter(it=>(it.category||'').toLowerCase().trim()===cat);
  }

  function interleave(items) {
    const g={};
    items.forEach(it=>{(g[it.source||'x']=g[it.source||'x']||[]).push(it);});
    const groups=Object.values(g); const out=[];
    for(let i=0;out.length<items.length;i++){let ok=false;groups.forEach(a=>{if(i<a.length){out.push(a[i]);ok=true;}});if(!ok)break;}
    return out;
  }

  // ── mobile nav ──────────────────────────────────────────────
  function initNav() {
    const tog=document.querySelector('.nav-toggle');
    const mob=document.querySelector('.nav-mob');
    if (!tog||!mob) return;
    tog.addEventListener('click', e=>{e.stopPropagation();mob.classList.toggle('open');});
    document.addEventListener('click', e=>{if(!mob.contains(e.target)&&!tog.contains(e.target))mob.classList.remove('open');});
    mob.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>mob.classList.remove('open')));
  }

  // ── boot ────────────────────────────────────────────────────
  async function boot() {
    lazyObserver = setupObserver();
    initNav();

    const grid = document.getElementById('bentoGridLarge');
    if (!grid) return;

    const cat = (document.body.dataset.category||'').toLowerCase().trim();
    grid.innerHTML = '<li class="bento-loading">Loading latest broadcast news\u2026</li>';

    try {
      const data  = await loadNews();
      const pool  = [...(data.featured_priority||[]),...(data.items||[])];
      const valid = pool.filter(it=>isUrl(it.url||it.link));
      allItems = (!cat||cat==='featured') ? valid : interleave(filterCat(valid,cat));

      if (!allItems.length) {
        grid.innerHTML='<li class="bento-loading">No live feed items yet. Editorial content above.</li>';
        return;
      }
      grid.innerHTML='';
      await renderBatch(grid);
      if (allItems.length>BATCH) addMoreBtn(grid);
    } catch(err) {
      console.error('[Streamic]',err);
      grid.innerHTML='<li class="bento-loading">Live feed unavailable.</li>';
    }
  }

  document.readyState==='loading'
    ? document.addEventListener('DOMContentLoaded',boot)
    : boot();
})();
