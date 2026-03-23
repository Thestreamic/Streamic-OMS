# The Streamic — thestreamic.in

Independent broadcast & streaming technology journalism.

## Architecture

```
streamic-new/
├── docs/                          ← GitHub Pages root (serve from /docs)
│   ├── index.html                 ← Homepage (redirects to featured.html)
│   ├── featured.html              ← Main editorial page
│   ├── streaming.html             ← Category pages
│   ├── cloud.html
│   ├── ai-post-production.html
│   ├── infrastructure.html
│   ├── graphics.html
│   ├── playout.html
│   ├── newsroom.html
│   ├── howto.html                 ← How-To Guides hub
│   ├── about.html
│   ├── contact.html
│   ├── privacy.html
│   ├── terms.html
│   ├── vlog.html                  ← Editor's Desk
│   ├── sitemap.xml
│   ├── robots.txt
│   ├── ads.txt                    ← Google AdSense verification
│   ├── style.css                  ← Apple Newsroom-style design system
│   ├── main.js                    ← RSS bento grid loader
│   ├── assets/
│   │   ├── logo.png
│   │   └── fallback.jpg
│   ├── articles/                  ← 100+ article pages
│   │   ├── guide-premiere-to-avid.html
│   │   ├── guide-vantage-nas-transcode.html
│   │   ├── guide-vantage-aws-transcode.html
│   │   ├── guide-avid-strawberry.html
│   │   └── ... (RSS + editorial articles)
│   └── data/
│       ├── news.json              ← Live RSS feed (served to main.js)
│       └── generated_articles.json ← Articles with Groq summaries
│
├── scripts/
│   ├── generate.js                ← Node.js: HF API → 1200+ word articles
│   ├── fetch_rss.py               ← Python: fetch broadcast RSS feeds
│   ├── rewrite_feed.py            ← Python: RSS → card summaries
│   ├── generate_editorial.py      ← Python: 5 deep-dive editorial articles
│   ├── generate_summaries.py      ← Python: Groq 330-word analyses
│   └── build.py                   ← Python: full static site generator
│
├── data/
│   ├── generated_articles.json    ← Article data store (96 articles)
│   ├── news.json                  ← Latest RSS feed data
│   ├── image_pools.json           ← Verified broadcast Unsplash IDs
│   └── summaries/                 ← Per-article Groq summaries
│
├── .github/workflows/
│   ├── generate.yml               ← Full pipeline (HF + Python + build)
│   └── build.yml                  ← Python-only build (fallback)
│
├── style.css                      ← Root copy (for Pages fallback)
├── main.js                        ← Root copy
├── CNAME                          ← thestreamic.in
├── ads.txt                        ← AdSense verification
└── robots.txt
```

## Setup

### 1. GitHub Pages
- Settings → Pages → Branch: `main` / Folder: `/docs`

### 2. Required Secrets (Settings → Secrets → Actions)
| Secret | Purpose |
|--------|---------|
| `GROQ_API_KEY` | Groq LLaMA 330-word analyses |
| `HF_API_KEY` | Hugging Face Mistral 1200-word articles |

### 3. Run the pipeline
Actions → "The Streamic — Full Content Pipeline" → Run workflow

## Content Pipeline

```
Every 6 hours:
  Node.js generate.js
    → Fetches RSS feeds
    → Calls HF Mistral-7B-Instruct API
    → Generates 1200+ word articles
    → Writes to docs/posts/ + docs/index.html

  Python scripts:
    fetch_rss.py         → data/news.json
    rewrite_feed.py      → data/generated_articles.json
    generate_editorial.py → 5 deep-dive articles
    generate_summaries.py → Groq 330-word summaries (if GROQ_API_KEY set)
    build.py             → All static HTML pages
```

## AdSense Compliance
- ✅ Original editorial content (5 long-form articles, 1200+ words each)
- ✅ How-To guides (4 broadcast workflow guides, 1000-1300 words each)
- ✅ Source attribution on all RSS-based content
- ✅ `rel="nofollow"` on all external links
- ✅ GDPR cookie consent (Consent Mode v2)
- ✅ Privacy Policy, Terms of Use, About, Contact pages
- ✅ ads.txt with publisher ID
- ✅ No scraped content — all analysis is original
- ✅ AdSense "Advertisement" label on all ad slots

## Technology
- **Hosting:** GitHub Pages (static, zero cost)
- **Build:** Python 3.11 + Node.js 20
- **AI:** Groq LLaMA (summaries) + Hugging Face Mistral-7B (full articles)  
- **Design:** DM Serif Display + DM Sans, Apple Newsroom-inspired
- **RSS Sources:** TVBEurope, BroadcastBeat, Streaming Media Blog, Harmonic, Haivision, Ross Video, and 20+ broadcast industry feeds
- **Analytics:** Google Analytics (G-0VSHDN3ZR6) + Consent Mode v2

## Categories
- Featured | Streaming | Cloud Production | AI & Post-Production
- Graphics | Playout | Infrastructure | Newsroom | How-To
