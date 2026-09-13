# Streamic OMS — IBC 2026 Editorial & Homepage Redesign

**Handover Summary** | 23 August 2026 | Ready to push

---

## What Was Accomplished

### 1. Homepage Hero Redesign
- **Full-bleed IBC 2026 hero** (2400×1000px) with organic lattice motif and left scrim overlay
- **Real HTML headline** ("Top 6 Broadcast Technology Trends to Track") rather than baked text — responsive, SEO-rich, crisp at all sizes
- **Removed 50/50 split card layout** that was leaking onto the features page
- **Order is now**: Lead Hero → Secondary Feature (Top 10) → AssetVista band → Technical Deep Dives

### 2. Two IBC 2026 Editorial Pieces
- **Top 6 Broadcast Technology Trends** (`docs/ibc-2026-broadcast-technology-trends.html`)
  - Full article page with six numbered trends, "Why it matters" callouts, source links, FAQ section
  - Removed production scaffolding (Suggested image ALT text, SEO publishing sections, etc.)
  - 3 min read | Published 22 August 2026
  
- **Top 10 AI & Broadcast Solutions** (`docs/ibc-2026-top-ai-broadcast-solutions.html`)
  - Pre-show analysis: 10 ranked solutions (5 for broadcasters/digital, 5 for Media IT/post-production)
  - Each entry has "Best fit", "What to verify at IBC", source links
  - 5 min read | Published 22 August 2026
  - Cross-links both ways with Top 6 piece

### 3. Secondary Feature Card
- **New `.sec-feat-wrap` horizontal card** positioned between hero and AssetVista
- Graphic left (1200×785), copy right, on white background for visual separation
- Links to Top 10 Solutions article
- Responsive: stacks single-column on mobile, no overflow

### 4. Clean-Room Graphics
Three generated graphics with only geometric primitives (no photographs, no third-party logos):
- **`ibc-2026-hero-wide.jpg`** (2400×1000, 97KB) — Homepage hero background, lattice on right, left scrim
- **`ibc-2026-key-trends.jpg`** (1200×785, 100KB) — Top 6 article card, centered hexagon cluster, gold accents
- **`ibc-2026-top-solutions.jpg`** (1200×785, 89KB) — Top 10 article card, concentric orbital rings with ten nodes

### 5. Deterministic Image Assignment
- Fixed `scripts/assign_images.py` to use SHA-256 hashing of article slugs instead of `random.shuffle()`
- **Before**: Every build shuffled article thumbnails site-wide, producing 24-file diffs with no semantic changes
- **After**: Same slug always gets the same image; identical `docs/index.html` hash across three consecutive builds
- **One-time cost**: 24 article pages get a new thumbnail assignment (locked in after push)

### 6. Bug Fixes
- **Card leaked to features.html**: The split-hero card was appearing on the product page. Fixed by restoring original function and creating separate lead-hero renderer.
- **Horizontal overflow**: Removed `-24px` bleed margins that assumed a padded parent (main has no padding).
- **Features page cleaned up**: Removed the IBC card entirely (was only meant for homepage).

---

## Current State

### Uncommitted Changes (41 files)
Ready to commit and push tomorrow:

**Source code (2 files)**
- `scripts/build.py` — Added HERO_FEATURE, SECOND_FEATURE dicts; _lead_hero_styles/html, _secondary_feature_styles/html
- `scripts/assign_images.py` — Deterministic hash-based assignment (v4), no more random shuffle

**Generated Pages (6 files)**
- `docs/index.html`, `featured.html` — Homepage with full-bleed hero + secondary card
- `index.html`, `featured.html` — Root mirrors of above
- `docs/ibc-2026-broadcast-technology-trends.html` — Top 6 article
- `docs/ibc-2026-top-ai-broadcast-solutions.html` — Top 10 article

**Graphics (3 files)**
- `docs/assets/ibc-2026-hero-wide.jpg` — Homepage hero background
- `docs/assets/ibc-2026-key-trends.jpg` — Top 6 article graphic
- `docs/assets/ibc-2026-top-solutions.jpg` — Top 10 article graphic

**Article Pages (24 files)**
- `docs/articles/` — New thumbnail assignments (one-time shuffle, then deterministic)

**Supporting (2 files)**
- `docs/sitemap.xml` — Added entries for both new articles at priority 0.92
- `data/generated_articles.json` — Updated article data with new thumbnails

**Metadata (4 files)**
- `build.py`, `docs/features.html`, `docs/sitemap.xml`, `docs/editorial-policy.html`

### Already Committed (in HEAD)
- Full-width hero structure and CSS
- Top 6 and Top 10 article pages (without the secondary card)
- All three IBC graphics
- Sitemap entries

---

## Key Technical Decisions

### 1. Text-Free Hero Background
The hero image is **background only** — no baked-in headline. The H1 sits as real HTML on top using CSS positioned text. This means:
- **Responsive**: Font scales with `clamp()`, works at any viewport
- **SEO**: Real text, fully indexable
- **Maintainable**: Change the headline without regenerating graphics
- **Accessible**: Screen readers see the text

### 2. Deterministic Image Pool
Article thumbnails are now keyed to their slug via `hashlib.sha256()`. Trade-off:
- **Pro**: Stable diffs, CI builds don't churn 27 files for no semantic reason
- **Con**: First push moves 24 thumbnails to their hashed assignment (not changeable without re-running the whole pipeline)

### 3. Secondary Feature as Data-Driven
The `.sec-feat-wrap` is configured in `build.py` via a `SECOND_FEATURE` dict. To retire it or feature something else, change the dict or set it to `None` — no HTML editing needed.

---

## How It Looks

### Desktop (1440px)
- Hero image (615px tall) with overlaid "Top 6" headline and gold CTA
- Secondary feature band below (1200px wide, left/right split) linking to Top 10
- AssetVista band below (responsive 2-column grid)
- Technical Deep Dives grid at bottom

### Mobile (375px)
- Hero stacks vertically, same height
- Secondary feature stacks single column (image above copy)
- AssetVista stacks single column
- No horizontal overflow

---

## SEO & Markup

Both articles include:
- **NewsArticle** schema with headline, description, image, datePublished
- **ItemList** schema (ranked 6 or 10 items, each anchored, individually linkable)
- **FAQPage** schema (3 Q&As per article)
- **BreadcrumbList** schema for hierarchy
- **OG meta tags** with correct image URLs
- **H1 → H2 → H3 ladder** with proper scoping
- **Keyword-rich ALT text** for broadcast/media IT terminology

---

## Next Steps (All Optional)

### Tomorrow (24 Aug)
```bash
git add -A
git commit -m "IBC 2026 editorial: top 6 trends hero + top 10 solutions card; deterministic image assignment"
git push
```
CI will rebuild. The diff will be clean — 41 files, no spurious churn. Live within minutes.

### Later (if desired)
1. **Pin the AudioShake link** — `ibc.org/proav/news/audioshake-cleans-up-muddled-speech/22794` ends in the same ID as Innovation Awards URL; verify it's not a copy-paste error.
2. **Monitor thumbnail stability** — Next CI run (whenever) should rebuild with identical asset assignments. If it doesn't, check that `assign_images.py` changes were included.
3. **Expand the secondary card** — To feature a different article next week, update `SECOND_FEATURE` dict in `scripts/build.py` (href, img, title, dek, date, etc.) and rebuild.

---

## Files to Know

### Build System
- `scripts/build.py` — Core generator; HERO_FEATURE & SECOND_FEATURE are the entry points
- `scripts/assign_images.py` — Article thumbnail assignment (now deterministic, v4)
- `data/generated_articles.json` — Article registry (rebuilt each run, source of truth for thumbnails)

### Content
- `docs/ibc-2026-broadcast-technology-trends.html` — Top 6 article (static, no data-driven parts)
- `docs/ibc-2026-top-ai-broadcast-solutions.html` — Top 10 article (static, no data-driven parts)
- `docs/sitemap.xml` — Must include both new articles (already done)

### Homepage
- `docs/index.html` (mirrors `index.html`) — Features lead hero, secondary card, AssetVista band
- The hero region (between `<style>` and `</header>`) contains the full-bleed layout

### Assets
- `docs/assets/ibc-2026-hero-wide.jpg` — 2400×1000, used in hero region
- `docs/assets/ibc-2026-key-trends.jpg` — 1200×785, used in Top 6 article
- `docs/assets/ibc-2026-top-solutions.jpg` — 1200×785, used in Top 10 article

---

## Verified
✅ No horizontal overflow (desktop or mobile)  
✅ Hero and secondary card both render correctly  
✅ Cross-links between articles both resolve  
✅ Features page leak is fixed  
✅ Schema markup is valid (NewsArticle, ItemList, FAQPage, BreadcrumbList)  
✅ Article thumbnails are deterministic (three runs → identical MD5)  
✅ Full pipeline is reproducible (assign → build → identical output)  

---

## Questions?
Check the git log for context on each major commit. The top commit (`HEAD`) will show what you're about to push.
