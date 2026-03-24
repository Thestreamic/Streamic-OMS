/* THE STREAMIC · main.js  (Data-Desync Fix)
   ────────────────────────────────────────────────────────────────
   DATA SOURCE: docs/data/generated_articles.json
     • Contains card_summary (330-word Groq analysis)
     • Contains slug → links to internal article pages
     • Sorted newest-first by build.py

   CARD LAYOUT:
     First card  → 8/12 col, vertical (large image top, full summary)
     Other cards → 4/12 col, vertical (image top, text below) — Apple style
     All links   → internal articles/slug.html first, source URL fallback
   ────────────────────────────────────────────────────────────────
   Links: rel="noopener noreferrer nofollow" on all external URLs
*/
(() => {
  'use strict';

  const BUST    = Date.now();
  const BATCH   = 12;

  let allItems   = [];
  let shownCount = 0;
  let lazyObs    = null;

  // ── Fallback images (broadcast-safe Unsplash, no warehouse/food) ──
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

  function getImg(item) {
    const src = item.image_url || item.image || '';
    if (src && src.startsWith('http')) return src;
    const cat = (item.category || 'featured').toLowerCase().trim();
    return FALLBACK[cat] || FALLBACK.featured;
  }

  function getUrl(item) {
    // Internal article page (has full analysis + source credit)
    if (item.slug) return `articles/${item.slug}.html`;
    return item.url || item.link || item.source_url || '#';
  }

  function getSourceUrl(item) {
    // Direct link to original RSS source (for title click)
    return item.source_url || item.url || item.link || '#';
  }

  function isExternal(url) {
    return url.startsWith('http://') || url.startsWith('https://');
  }

  // ── Lazy image observer ──────────────────────────────────────
  function setupLazy() {
    if (!('IntersectionObserver' in window)) return null;
    return new IntersectionObserver((entries, obs) => {
      entries.forEach(e => {
        if (e.isIntersecting && e.target.dataset.src) {
          e.target.src = e.target.dataset.src;
          e.target.removeAttribute('data-src');
          obs.unobserve(e.target);
        }
      });
    }, { rootMargin: '80px', threshold: 0.01 });
  }

  function makeImgTag(url, alt, eager) {
    if (eager) return `<img src="${url}" alt="${alt}" loading="eager">`;
    if (lazyObs) {
      return `<img data-src="${url}" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" alt="${alt}" loading="lazy" class="lz">`;
    }
    return `<img src="${url}" alt="${alt}" loading="lazy">`;
  }

  // After appending, observe all lazy images in the new fragment
  function observeImgs(container) {
    if (!lazyObs) return;
    container.querySelectorAll('img.lz').forEach(img => lazyObs.observe(img));
  }

  // ── CARD BUILDERS ────────────────────────────────────────────

  /* FEATURED (first card): 8/12 col, full-width image top, full Groq summary */
  function buildFeatured(item) {
    const li       = document.createElement('li');
    li.className   = 'bento-grid-item';

    const internalUrl = getUrl(item);            // articles/slug.html OR source
    const srcUrl      = getSourceUrl(item);      // original RSS source URL
    const imgUrl      = getImg(item);
    const title       = (item.title || 'Untitled').trim();
    const cat         = (item.category || 'featured').toLowerCase().trim();
    const catLbl      = cat.replace(/-/g,' ').replace(/\b\w/g, c => c.toUpperCase());
    const srcTxt      = (item.source_domain || item.source || '').replace(/https?:\/\//,'').replace('www.','').split('/')[0].toUpperCase();
    const text        = item.card_summary || item.dek || item.meta_description || item.teaser || '';
    // Title links to SOURCE, CTA links to internal analysis page
    const titleHref   = isExternal(srcUrl) ? srcUrl : internalUrl;
    const titleTarget = isExternal(titleHref) ? ' target="_blank"' : '';
    const titleRel    = isExternal(titleHref) ? ' rel="noopener noreferrer nofollow"' : '';
    const ctaHref     = item.slug ? internalUrl : srcUrl;
    const ctaTarget   = isExternal(ctaHref) ? ' target="_blank"' : '';
    const ctaRel      = isExternal(ctaHref) ? ' rel="noopener noreferrer nofollow"' : '';

    li.innerHTML = `
      <div class="bento-img-wrap bento-img-featured">
        <a href="${ctaHref}"${ctaTarget}${ctaRel} tabindex="-1" aria-hidden="true">
          ${makeImgTag(imgUrl, title, true)}
        </a>
      </div>
      <div class="bento-body bento-body-featured">
        <span class="bento-cat-tag">${catLbl}</span>
        <h2 class="bento-hl bento-hl-featured">
          <a href="${titleHref}"${titleTarget}${titleRel}>${title}</a>
        </h2>
        ${item.card_summary && item.slug ? `<a href="articles/${item.slug}.html" class="bento-groq-badge">✦ Read Technical Analysis</a>` : ''}
        <div class="bento-foot">
          ${srcTxt ? `<span class="bento-source">${srcTxt}</span>` : ''}
          <a href="${ctaHref}"${ctaTarget}${ctaRel} class="bento-cta-featured">
            ${item.slug ? 'Read Full Analysis →' : 'View Original →'}
          </a>
        </div>
      </div>
    `;
    return li;
  }

  /* STANDARD (all others): 4/12 col, vertical — image top, text below */
  function buildStandard(item) {
    const li       = document.createElement('li');
    li.className   = 'bento-grid-item bento-standard';

    const internalUrl = getUrl(item);
    const srcUrl      = getSourceUrl(item);
    const imgUrl      = getImg(item);
    const title       = (item.title || 'Untitled').trim();
    const cat         = (item.category || 'featured').toLowerCase().trim();
    const catLbl      = cat.replace(/-/g,' ').replace(/\b\w/g, c => c.toUpperCase());
    const srcTxt      = (item.source_domain || item.source || '').replace(/https?:\/\//,'').replace('www.','').split('/')[0].toUpperCase();
    const text        = item.card_summary || item.dek || item.meta_description || item.teaser || '';
    const titleHref   = isExternal(srcUrl) ? srcUrl : internalUrl;
    const titleTarget = isExternal(titleHref) ? ' target="_blank"' : '';
    const titleRel    = isExternal(titleHref) ? ' rel="noopener noreferrer nofollow"' : '';
    const ctaHref     = item.slug ? internalUrl : srcUrl;
    const ctaTarget   = isExternal(ctaHref) ? ' target="_blank"' : '';
    const ctaRel      = isExternal(ctaHref) ? ' rel="noopener noreferrer nofollow"' : '';

    li.innerHTML = `
      <div class="bento-img-wrap bento-img-std">
        <a href="${ctaHref}"${ctaTarget}${ctaRel} tabindex="-1" aria-hidden="true">
          ${makeImgTag(imgUrl, title, false)}
        </a>
      </div>
      <div class="bento-body bento-body-std">
        <span class="bento-cat-tag">${catLbl}</span>
        <h3 class="bento-hl bento-hl-std">
          <a href="${titleHref}"${titleTarget}${titleRel}>${title}</a>
        </h3>
        <div class="bento-foot">
          ${srcTxt ? `<span class="bento-source">${srcTxt}</span>` : ''}
          <a href="${ctaHref}"${ctaTarget}${ctaRel} class="bento-cta">
            ${item.slug ? 'Read Full Article →' : 'View Source →'}
          </a>
        </div>
      </div>
    `;
    return li;
  }

  // ── RENDER ───────────────────────────────────────────────────
  function renderBatch(grid) {
    const slice = allItems.slice(shownCount, shownCount + BATCH);
    if (!slice.length) { hideMore(); return; }

    const frag = document.createDocumentFragment();
    slice.forEach((item, idx) => {
      frag.appendChild(
        (shownCount + idx === 0) ? buildFeatured(item) : buildStandard(item)
      );
    });
    grid.appendChild(frag);
    observeImgs(grid);
    shownCount += slice.length;
    if (shownCount >= allItems.length) hideMore();
  }

  function hideMore() {
    const b = document.getElementById('ts-more');
    if (b && b.parentElement) b.parentElement.style.display = 'none';
  }

  function addMoreBtn(grid) {
    if (document.getElementById('ts-more')) return;
    const wrap = document.createElement('div');
    wrap.style.cssText = 'margin:40px 0;text-align:center';
    const btn  = document.createElement('button');
    btn.id = 'ts-more';
    btn.textContent = 'Load More Stories';
    btn.style.cssText = 'padding:13px 44px;border-radius:999px;border:1.5px solid var(--line);background:var(--white);color:var(--ink);font-size:14px;font-weight:600;cursor:pointer;font-family:var(--font);letter-spacing:-0.02em;transition:all .15s';
    btn.onmouseover = () => { btn.style.background='var(--ink)'; btn.style.color='#fff'; btn.style.borderColor='var(--ink)'; };
    btn.onmouseout  = () => { btn.style.background='var(--white)'; btn.style.color='var(--ink)'; btn.style.borderColor='var(--line)'; };
    btn.onclick     = () => renderBatch(grid);
    wrap.appendChild(btn);
    grid.parentElement.appendChild(wrap);
  }

  // ── DATA LOADER (MODULE 2 FIX) ───────────────────────────────
  /**
   * CRITICAL FIX: Load generated_articles.json (has Groq summaries + slugs)
   * NOT news.json (which only has short RSS teasers, no internal links)
   */
  async function loadNews() {
    const paths = [
      'data/generated_articles.json?v=' + BUST,
      '/data/generated_articles.json?v=' + BUST,
    ];
    for (const p of paths) {
      try {
        const r = await fetch(p);
        if (!r.ok) continue;
        const raw = await r.json();
        // Handle both flat array and {featured_priority, items} formats
        if (Array.isArray(raw)) {
          return { featured_priority: raw.slice(0, 6), items: raw.slice(6) };
        }
        if (raw.items !== undefined || raw.featured_priority !== undefined) {
          return raw;
        }
        return { featured_priority: raw.slice ? raw.slice(0,6) : [], items: raw.slice ? raw.slice(6) : [] };
      } catch (_) {}
    }
    // Graceful fallback to news.json (RSS teasers only)
    for (const p of ['data/news.json?v='+BUST, '/data/news.json?v='+BUST]) {
      try {
        const r = await fetch(p);
        if (!r.ok) continue;
        const raw = await r.json();
        if (Array.isArray(raw)) return { featured_priority: raw.slice(0,6), items: raw.slice(6) };
        if (raw.items !== undefined) return raw;
        return { featured_priority: [], items: [] };
      } catch (_) {}
    }
    throw new Error('No data source reachable');
  }

  function filterCat(items, cat) {
    if (!cat || cat === 'featured') return items;
    return items.filter(it => (it.category || '').toLowerCase().trim() === cat);
  }

  function interleave(items) {
    const g = {};
    items.forEach(it => { (g[it.source_domain || it.source || 'x'] = g[it.source_domain || it.source || 'x'] || []).push(it); });
    const groups = Object.values(g);
    const out = [];
    for (let i = 0; out.length < items.length; i++) {
      let ok = false;
      groups.forEach(arr => { if (i < arr.length) { out.push(arr[i]); ok = true; } });
      if (!ok) break;
    }
    return out;
  }

  // ── MOBILE NAV ───────────────────────────────────────────────
  function initNav() {
    const tog = document.querySelector('.nav-toggle');
    const mob = document.querySelector('.nav-mob');
    if (!tog || !mob) return;
    tog.addEventListener('click', e => { e.stopPropagation(); mob.classList.toggle('open'); });
    document.addEventListener('click', e => {
      if (!mob.contains(e.target) && !tog.contains(e.target)) mob.classList.remove('open');
    });
    mob.querySelectorAll('a').forEach(a => a.addEventListener('click', () => mob.classList.remove('open')));
  }

  // ── BOOT ─────────────────────────────────────────────────────
  async function boot() {
    lazyObs = setupLazy();
    initNav();

    const grid = document.getElementById('bentoGridLarge');
    if (!grid) return;

    const cat = (document.body.dataset.category || '').toLowerCase().trim();
    grid.innerHTML = '<li class="bento-loading">Loading latest broadcast news\u2026</li>';

    try {
      const data  = await loadNews();
      const pool  = [...(data.featured_priority || []), ...(data.items || [])];
      // Filter to only items that have a valid URL (internal slug OR external link)
      const valid = pool.filter(it => it.slug || it.url || it.link);
      allItems    = (!cat || cat === 'featured')
        ? interleave(valid)
        : interleave(filterCat(valid, cat)).slice(1); // skip first — already shown as SSR hero above grid

      if (!allItems.length) {
        grid.innerHTML = '<li class="bento-loading">No content yet. Check back soon.</li>';
        return;
      }
      grid.innerHTML = '';
      renderBatch(grid);
      if (allItems.length > BATCH) addMoreBtn(grid);
    } catch (err) {
      console.error('[Streamic]', err);
      grid.innerHTML = '<li class="bento-loading">Live feed temporarily unavailable.</li>';
    }
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', boot)
    : boot();
})();
