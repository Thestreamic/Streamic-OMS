"""
scripts/generate_summaries.py
==============================
Uses Groq API to generate per-article unique summaries.
Stores each summary in data/summaries/<slug>.json

Usage:
  GROQ_API_KEY=xxx python scripts/generate_summaries.py

GitHub Actions usage:
  env:
    GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
  run: python scripts/generate_summaries.py

Each summary JSON contains:
  {
    "slug": "...",
    "card_summary": "~300 word editorial summary",
    "body_html": "700-900 word full article HTML",
    "word_count": 850
  }

The script is IDEMPOTENT — skips slugs already in data/summaries/.
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NEWS_F       = os.path.join(ROOT, "data", "news.json")
GEN_ARTS_F   = os.path.join(ROOT, "data", "generated_articles.json")
SUMMARIES_DIR = os.path.join(ROOT, "data", "summaries")
os.makedirs(SUMMARIES_DIR, exist_ok=True)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama3-8b-8192"   # fast + free tier
MAX_PER_RUN  = 40                  # stay within Groq free tier rate limits
SLEEP_SECS   = 1.5                 # pause between calls to avoid rate-limit

# ── Slug builder (mirrors rewrite_feed.py) ────────────────────────────────────
def make_slug(title, pub_date, cat=""):
    date_part  = (pub_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    cat_part   = re.sub(r"[^\w]", "-", (cat or "").lower()).strip("-")[:12]
    title_part = re.sub(r"[^\w\s-]", "", title.lower())
    title_part = re.sub(r"[\s_]+", "-", title_part).strip("-")
    prefix     = f"{date_part}-{cat_part}-" if cat_part else f"{date_part}-"
    return f"{prefix}{title_part[:65 - len(prefix)]}"

# ── Groq API call ─────────────────────────────────────────────────────────────
def groq_call(prompt: str, max_tokens: int = 1200) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")

    payload = json.dumps({
        "model": GROQ_MODEL,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "frequency_penalty": 0.8,
        "presence_penalty": 0.6,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a senior broadcast editor. Write precise 330-word technical analyses. "
                    "Strict rule: never start two sentences with the same word. "
                    "Do not use corporate buzzwords like delivers, seamless, or game-changer. "
                    "Focus on specs (ST 2110, NMOS, latency, bitrate) and the So What for CTOs."
                )
            },
            {"role": "user", "content": prompt}
        ]
    }).encode("utf-8")

    req = urllib.request.Request(
        GROQ_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Groq HTTP {e.code}: {body[:300]}")

# ── Prompt builders ───────────────────────────────────────────────────────────
_CARD_PROMPT = """You are a senior broadcast technology editor at The Streamic.
Write a 330-word ORIGINAL technical analysis. This is NOT a summary — it is your editorial perspective on why this news matters to broadcast engineers and CTOs in 2026.

SOURCE MATERIAL (use ONLY as seed — do not copy it):
Title: {title}
Brief: {teaser}

OUTPUT REQUIREMENTS (ALL MANDATORY):
1. Write exactly two paragraphs totalling 325–335 words.
2. Paragraph 1 — "The Signal" (~165 words): State what happened in one sentence. Then immediately pivot to the strategic implication — how does this affect ST 2110 adoption, operational AI rollouts, hybrid cloud strategy, or IP infrastructure planning? Make the "So What for engineers" explicit.
3. Paragraph 2 — "The Detail" (~165 words): Go deeper. Cite specific technical standards (SMPTE, NMOS, AES67, HLS, HEVC, AV1), vendor ecosystem context, latency/bitrate numbers if relevant, or workflow implications for playout, newsroom, or post-production teams.
4. End with exactly this attribution line on a new line:
   Source: {source_name} — Original reporting via {source_name}.
5. FORBIDDEN words/phrases: "delivers", "seamless", "game-changer", "innovative", "revolutionary", "state-of-the-art", "excited to announce", "proud to", "cutting-edge", "best-in-class".
6. NEVER start two consecutive sentences with the same word.
7. Do NOT restate the title. Do NOT begin "The article...", "This story...", "According to...".

Write the two-paragraph analysis now (330 words, transformative, original):"""

_ARTICLE_PROMPT = """You are a senior editor at a broadcast technology publication.
Write a 750-word article about this news item for our website.

Rules:
- Original prose only. Neutral, factual, informative.
- Structure: opening paragraph (2 sentences) → H2: What is happening → H2: Why it matters → H2: Operational considerations → H2: Looking ahead → closing paragraph.
- Each H2 section: 2-3 short paragraphs (3-4 sentences each).
- Short sentences. Plain newsroom English. No jargon without explanation.
- Do NOT name third-party publications. Keep source references generic.
- No brand-puff phrases. No meta-commentary ("in this article", "as mentioned above").
- Output valid HTML only: use <h2>, <p> tags. No <html>, <head>, <body>.

Title: {title}
Teaser: {teaser}
Category: {category}

Write the full article HTML now:"""

# ── Summary file helpers ──────────────────────────────────────────────────────
def summary_path(slug: str) -> str:
    return os.path.join(SUMMARIES_DIR, f"{slug}.json")

def summary_exists(slug: str) -> bool:
    return os.path.exists(summary_path(slug))

def save_summary(slug: str, card_summary: str, body_html: str):
    wc = len(re.sub(r"<[^>]+>", " ", body_html).split())
    data = {
        "slug":         slug,
        "card_summary": card_summary,
        "body_html":    body_html,
        "word_count":   wc,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(summary_path(slug), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_summary(slug: str) -> dict:
    try:
        with open(summary_path(slug), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=== generate_summaries.py ===")

    if not GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY not set. Export it before running.")
        sys.exit(1)

    # Collect all items to summarise from news.json
    with open(NEWS_F, "r", encoding="utf-8") as f:
        news = json.load(f)

    # Also include items already in generated_articles.json that lack good summaries
    with open(GEN_ARTS_F, "r", encoding="utf-8") as f:
        gen_arts = json.load(f)

    # Build list of (slug, title, teaser, category) to process
    items_to_process = []
    seen_slugs = set()

    # From news.json (RSS items)
    for cat, items in news.items():
        for item in items:
            title  = (item.get("title") or "").strip()
            teaser = (item.get("teaser") or "").strip()
            pub    = (item.get("published") or "")[:10]
            if not title: continue
            slug = make_slug(title, pub, cat)
            if slug in seen_slugs or summary_exists(slug): continue
            seen_slugs.add(slug)
            items_to_process.append({
                "slug": slug, "title": title,
                "teaser": teaser, "category": cat
            })

    # From generated_articles.json (items with generic summaries)
    generic_markers = [
        "This development is part of the ongoing evolution",
        "The Streamic will publish a full analysis",
        "An independent editorial overview of the technology forces",
        "full technical details and deployment implications",
    ]
    for a in gen_arts:
        slug = a.get("slug", "")
        if not slug or slug in seen_slugs or summary_exists(slug): continue
        body = a.get("body_html", "") + a.get("card_summary", "")
        if any(m in body for m in generic_markers):
            seen_slugs.add(slug)
            items_to_process.append({
                "slug": slug,
                "title": a.get("title", ""),
                "teaser": a.get("dek") or a.get("meta_description", ""),
                "category": a.get("category", "featured"),
            })

    print(f"Items to summarise: {len(items_to_process)} (max this run: {MAX_PER_RUN})")
    items_to_process = items_to_process[:MAX_PER_RUN]

    processed = 0
    errors    = 0
    for item in items_to_process:
        slug     = item["slug"]
        title    = item["title"]
        teaser   = item["teaser"]
        category = item["category"]

        print(f"  [{processed+1}/{len(items_to_process)}] {title[:55]}...")

        try:
            card_summary = groq_call(
                _CARD_PROMPT.format(title=title, teaser=teaser, source_name=(src_dom or 'the original source')),
                max_tokens=600   # 330 words ~ 440 tokens, buffer for safety
            )
            time.sleep(SLEEP_SECS)

            body_html = groq_call(
                _ARTICLE_PROMPT.format(title=title, teaser=teaser, category=category),
                max_tokens=1400
            )
            # Ensure HTML only (strip any markdown fences)
            body_html = re.sub(r"```html?\n?|```\n?", "", body_html).strip()
            time.sleep(SLEEP_SECS)

            save_summary(slug, card_summary, body_html)
            processed += 1
            print(f"      ✓ saved data/summaries/{slug}.json")

        except Exception as ex:
            errors += 1
            print(f"      ✗ ERROR: {ex}")
            time.sleep(3)  # back-off on error

    print(f"\n✓ Done: {processed} summaries saved, {errors} errors.")
    print(f"  Files in data/summaries/: {len(os.listdir(SUMMARIES_DIR))}")

    # Patch generated_articles.json with the new summaries
    patch_generated_articles()


def patch_generated_articles():
    """Apply saved summaries back into generated_articles.json."""
    with open(GEN_ARTS_F, "r", encoding="utf-8") as f:
        arts = json.load(f)

    patched = 0
    for a in arts:
        slug = a.get("slug", "")
        if not slug: continue
        s = load_summary(slug)
        if s:
            if s.get("card_summary"):
                a["card_summary"] = s["card_summary"]
            if s.get("body_html"):
                a["body_html"]    = s["body_html"]
            if s.get("word_count"):
                a["word_count"]   = s["word_count"]
            patched += 1

    with open(GEN_ARTS_F, "w", encoding="utf-8") as f:
        json.dump(arts, f, indent=2, ensure_ascii=False)

    print(f"  Patched {patched} articles in generated_articles.json")


if __name__ == "__main__":
    main()
