/* THE STREAMIC · main.js
   Apple Newsroom-style RSS news grid
   Reads docs/data/news.json → renders .news-grid#newsGrid
   Cards: title links to source (nofollow), "Read Full Story →" in footer
*/
(() => {
  'use strict';

  const BUST  = Date.now();
  const MAX   = 1800; // chars per summary — keeps layout stable
  const BATCH = 12;

  const FALLBACK = {
    featured:           'https://images.unsplash.com/photo-1598488035139-bdbb2231ce04?w=800&q=80',
    newsroom:           'https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=800&q=80',
    playout:            'https://images.unsplash.com/photo-1478737270239-2f02b77fc618?w=800&q=80',
    infrastructure:     'https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=800&q=80',
    graphics:           'https://images.unsplash.com/photo-1504639725590-34d0984388bd?w=800&q=80',
    cloud:              'https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=800&q=80',
    streaming:          'https://images.unsplash.com/photo-1499364615650-ec38552f4f34?w=800&q=80',
    'ai-post-production':'https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=800&q=80',
  };

  // ── state
  let all = [], shown = 0, obs = null;

  // ── helpers
  function fb(cat) {
    return FALLBACK[(cat||'').toLowerCase().trim()] || FALLBACK.featured;
  }
  function ok(url) {
    const u = (url||'').trim().toLowerCase();
    return u.startsWith('http://') || u.startsWith('https://');
  }
  function img(item) { return ok(item.image) ? item.image : fb(item.category); }
  function clip(s, n) {
    if (!s) return '';
    s = s.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
    return s.length > n ? s.slice(0,n).replace(/\s+\S*$/,'')+'…' : s;
  }
  function lazyImg(url, alt) {
    const i = document.createElement('img');
    i.alt = alt||'';
    if (obs) {
      i.dataset.src = url;
      i.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
      i.classList.add('lazy');
      obs.observe(i);
    } else { i.src = url; i.loading = 'lazy'; }
    return i;
  }

  // ── card builder — strictly follows spec HTML structure
  function makeCard(item, idx) {
    const li   = document.createElement('li');
    li.className = 'nc';

    const url  = ok(item.url)  ? item.url  :
                 ok(item.link) ? item.link : '#';
    const title = (item.title || 'Untitled').trim();
    const cat   = (item.category || 'featured').toLowerCase().trim();
    const src   = (item.source || item.sourceName || '').trim();
    const sum   = clip(item.card_summary || item.summary || item.dek || item.teaser || '', MAX);
    const catLabel = cat.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase());

    // image
    const imgWrap = document.createElement('div');
    imgWrap.className = 'nc-img';
    const imgA = document.createElement('a');
    imgA.href = url; imgA.target='_blank';
    imgA.rel  = 'noopener noreferrer nofollow';
    imgA.setAttribute('tabindex','-1');
    imgA.setAttribute('aria-hidden','true');
    imgA.appendChild(lazyImg(img(item), title));
    imgWrap.appendChild(imgA);

    // body
    const body = document.createElement('div');
    body.className = 'nc-body';

    const catEl = document.createElement('div');
    catEl.className = 'nc-cat';
    catEl.textContent = catLabel;

    const h3 = document.createElement('h3');
    h3.className = 'nc-hl';
    const a = document.createElement('a');
    a.href = url; a.target = '_blank';
    a.rel  = 'noopener noreferrer nofollow';
    a.textContent = title;
    h3.appendChild(a);

    body.appendChild(catEl);
    body.appendChild(h3);

    if (sum) {
      const p = document.createElement('p');
      p.className = 'nc-sum';
      p.textContent = sum;
      body.appendChild(p);
    }

    // footer: source + Read Full Story
    const foot = document.createElement('div');
    foot.className = 'nc-foot';

    if (src) {
      const s = document.createElement('span');
      s.className = 'nc-src';
      s.textContent = src;
      foot.appendChild(s);
    }

    if (url !== '#') {
      const rd = document.createElement('a');
      rd.href = url; rd.target = '_blank';
      rd.rel  = 'noopener noreferrer nofollow';
      rd.className = 'nc-read';
      rd.textContent = 'Read Full Story →';
      foot.appendChild(rd);
    }

    body.appendChild(foot);
    li.appendChild(imgWrap);
    li.appendChild(body);
    return li;
  }

  // ── batch renderer
  function renderBatch(grid) {
    const slice = all.slice(shown, shown + BATCH);
    if (!slice.length) { hideMore(); return; }
    const f = document.createDocumentFragment();
    slice.forEach((item, i) => f.appendChild(makeCard(item, shown + i)));
    grid.appendChild(f);
    shown += slice.length;
    if (shown >= all.length) hideMore();
  }

  function hideMore() {
    const btn = document.getElementById('loadMoreBtn');
    if (btn) btn.parentElement.style.display = 'none';
  }

  function makeMoreBtn(grid) {
    if (document.getElementById('loadMoreBtn')) return;
    const wrap = document.createElement('div');
    wrap.style.cssText = 'margin:36px 0;text-align:center';
    const btn = document.createElement('button');
    btn.id = 'loadMoreBtn';
    btn.textContent = 'Load More Stories';
    btn.style.cssText = `padding:13px 36px;border-radius:999px;border:1px solid var(--line);
      background:var(--white);color:var(--ink);font-size:14px;font-weight:600;
      cursor:pointer;font-family:var(--font);transition:all .15s`;
    btn.onmouseover = () => { btn.style.background='var(--ink)'; btn.style.color='#fff'; };
    btn.onmouseout  = () => { btn.style.background='var(--white)'; btn.style.color='var(--ink)'; };
    btn.onclick = () => renderBatch(grid);
    wrap.appendChild(btn);
    grid.parentElement.appendChild(wrap);
  }

  // ── data load + normalise
  async function loadData() {
    for (const path of ['data/news.json?v='+BUST, '/data/news.json?v='+BUST]) {
      try {
        const r = await fetch(path);
        if (!r.ok) continue;
        const raw = await r.json();
        if (Array.isArray(raw)) {
          return { featured_priority: raw.slice(0,6), items: raw.slice(6) };
        }
        if (raw.items !== undefined) return raw;
        // dict-of-categories
        const flat = [];
        Object.entries(raw).forEach(([cat,lst]) =>
          (lst||[]).forEach(it => flat.push({...it, category:it.category||cat}))
        );
        flat.sort((a,b) => (b.pubDate||b.published||'').localeCompare(a.pubDate||a.published||''));
        return { featured_priority: flat.slice(0,6), items: flat.slice(6) };
      } catch(e) { continue; }
    }
    throw new Error('news.json unavailable');
  }

  function filterCat(items, cat) {
    if (!cat || cat === 'featured') return items;
    return items.filter(it => (it.category||'').toLowerCase().trim() === cat);
  }

  function interleave(items) {
    const groups = {};
    items.forEach(it => {
      const s = it.source||'x';
      (groups[s] = groups[s]||[]).push(it);
    });
    const g = Object.values(groups); const out = [];
    for (let i = 0; out.length < items.length; i++) {
      let added = false;
      g.forEach(arr => { if (i < arr.length) { out.push(arr[i]); added = true; } });
      if (!added) break;
    }
    return out;
  }

  // ── init
  function init() {
    // lazy image observer
    if ('IntersectionObserver' in window) {
      obs = new IntersectionObserver((entries, o) => {
        entries.forEach(e => {
          if (e.isIntersecting && e.target.dataset.src) {
            e.target.src = e.target.dataset.src;
            e.target.classList.remove('lazy');
            o.unobserve(e.target);
          }
        });
      }, { rootMargin: '80px', threshold: 0.01 });
    }

    // mobile nav
    const tog  = document.querySelector('.nav-toggle');
    const mob  = document.querySelector('.nav-mob');
    if (tog && mob) {
      tog.addEventListener('click', e => {
        e.stopPropagation();
        mob.classList.toggle('open');
      });
      document.addEventListener('click', e => {
        if (!mob.contains(e.target) && !tog.contains(e.target))
          mob.classList.remove('open');
      });
      mob.querySelectorAll('a').forEach(a => a.addEventListener('click', () => mob.classList.remove('open')));
    }

    // news grid — only on pages with #newsGrid
    const grid = document.getElementById('newsGrid');
    if (!grid) return;

    // detect category
    const cat = (document.body.dataset.category || '').toLowerCase().trim();

    grid.innerHTML = '<li class="nc" style="grid-column:span 3;padding:48px;text-align:center;color:var(--ink4)">Loading latest stories…</li>';

    loadData()
      .then(data => {
        const pool = [...(data.featured_priority||[]), ...(data.items||[])];
        const valid = pool.filter(it => ok(it.url||it.link));
        all = (!cat || cat==='featured') ? valid : interleave(filterCat(valid, cat));
        if (!all.length) {
          grid.innerHTML = '<li class="nc" style="grid-column:span 3;padding:48px;text-align:center;color:var(--ink4)">No stories yet — check back soon.</li>';
          return;
        }
        grid.innerHTML = '';
        renderBatch(grid);
        if (all.length > BATCH) makeMoreBtn(grid);
      })
      .catch(() => {
        grid.innerHTML = '<li class="nc" style="grid-column:span 3;padding:48px;text-align:center;color:var(--ink4)">Unable to load live feed. Showing editorial content above.</li>';
      });
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', init)
    : init();
})();
