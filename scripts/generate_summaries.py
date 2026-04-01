#!/usr/bin/env python3
"""
generate_summaries.py  —  The Streamic
Enriches data/generated_articles.json with substantive Groq-powered analysis.

Key changes from original:
  • Target 500-600 words (was 330) with structured H2 sections
  • Force-reprocess any article with word_count < 400 (catches existing thin entries)
  • Force-reprocess articles that have no <h2> tags in body_html (catches "just Source" stubs)
  • Sets is_editorial=True, dek, meta_description, card_summary on every processed item
  • Prompt is broadcast-industry specific, not generic tech journalism
"""

import json
import os
import re
import time
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL     = "llama3-70b-8192"          # best quality on free tier
GROQ_API_URL   = "https://api.groq.com/openai/v1/chat/completions"

DATA_DIR       = Path(__file__).parent.parent / "data"
ARTICLES_FILE  = DATA_DIR / "generated_articles.json"
SUMMARIES_DIR  = DATA_DIR / "summaries"

# Reprocess if word_count is below this threshold  ← was effectively 0 (no reprocessing)
REPROCESS_THRESHOLD = 400
# Also reprocess if body_html has no <h2> headings (means it's a stub/plain paragraph)
REQUIRE_HEADINGS    = True
# Max articles to process per run (avoids Groq rate limits on a 6-hour cron)
MAX_PER_RUN         = 20

SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)


# ── Prompt ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a senior broadcast technology and media IT journalist writing for The Streamic (thestreamic.in), an independent editorial publication for broadcast engineers, media technology directors, and OTT platform professionals.

Your writing style is analytical and authoritative — similar to the Financial Times technology desk or TVBEurope's in-depth features. You write for practitioners who already understand the technology, not general consumers.

When you receive a news item, you write a structured analytical article that goes beyond the press release: you explain the engineering or operational significance, place it in industry context, and draw out implications for broadcast workflows."""

def build_user_prompt(title: str, source_text: str, category: str) -> str:
    return f"""Write a substantive broadcast industry analysis article based on the following news item.

Title: {title}
Category: {category}
Source content:
{source_text}

---

REQUIREMENTS — follow exactly:

1. OUTPUT FORMAT: Return ONLY valid HTML fragments (no <!DOCTYPE>, no <html>, no <head>). Start directly with a <p> or <h2> tag.

2. STRUCTURE — use exactly these four sections with <h2> tags:
   • <h2>What Was Announced</h2>  — factual summary of the news, 2–3 sentences
   • <h2>The Engineering and Operational Significance</h2>  — why this matters technically, what problem it solves, what workflow change it enables (3–4 sentences, specific)
   • <h2>Industry Context</h2>  — where this fits in the current broadcast/media IT landscape, any comparable approaches or competing technologies (3–4 sentences)
   • <h2>Implications for Broadcast and Media Teams</h2>  — what engineers, operations managers or platform teams should take note of and why (3–4 sentences)

3. LENGTH: 500–600 words total across all four sections. Do not pad; be analytically dense.

4. TONE: Confident, technical, editorial. Do not use marketing language from the press release. No phrases like "exciting announcement" or "game-changing". Write as a journalist explaining significance, not a publicist.

5. BROADCAST-SPECIFIC: Use correct industry terminology (IP core, SDI, AES67, SMPTE ST 2110, OTT, MAM, PAM, ABR, CDN, playout, ingest, etc.) where relevant and accurate.

6. No bullet lists — all prose paragraphs inside the section structure above.

7. Do not include a byline, title, or article header — only the body sections.

Begin the article now:"""


# ── Helpers ───────────────────────────────────────────────────────────────────
def needs_reprocessing(article: dict) -> bool:
    """Return True if this article should be (re-)processed by Groq."""
    body = article.get("body_html", "")
    wc   = article.get("word_count", 0)

    # No body at all
    if not body or len(body.strip()) < 100:
        return True
    # Below word-count threshold
    if wc < REPROCESS_THRESHOLD:
        return True
    # Has no H2 section headings (stub / plain paragraph)
    if REQUIRE_HEADINGS and "<h2" not in body.lower():
        return True

    return False


def count_words(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html)
    return len(text.split())


def extract_source_text(article: dict) -> str:
    """Build source text from available fields for the Groq prompt."""
    parts = []
    if article.get("dek"):
        parts.append(article["dek"])
    if article.get("card_summary"):
        parts.append(article["card_summary"])
    body = article.get("body_html", "")
    if body:
        # Strip HTML tags to get plain text for the prompt
        plain = re.sub(r"<[^>]+>", " ", body)
        plain = re.sub(r"\s+", " ", plain).strip()
        if len(plain) > 80:
            parts.append(plain)
    return "\n\n".join(parts) if parts else article.get("title", "")


def call_groq(title: str, source_text: str, category: str) -> str | None:
    """Call Groq API and return the generated HTML body, or None on failure."""
    if not GROQ_API_KEY:
        print("  [WARN] GROQ_API_KEY not set — skipping API call")
        return None

    payload = {
        "model":      GROQ_MODEL,
        "max_tokens": 900,
        "temperature": 0.45,
        "messages": [
            {"role": "system",  "content": SYSTEM_PROMPT},
            {"role": "user",    "content": build_user_prompt(title, source_text, category)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }

    try:
        resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except requests.exceptions.HTTPError as e:
        print(f"  [ERROR] Groq HTTP error: {e} — {resp.text[:200]}")
    except Exception as e:
        print(f"  [ERROR] Groq call failed: {e}")
    return None


def build_dek(title: str, body_html: str) -> str:
    """Generate a 1-sentence dek from the first paragraph of body."""
    plain = re.sub(r"<[^>]+>", " ", body_html)
    plain = re.sub(r"\s+", " ", plain).strip()
    sentences = re.split(r"(?<=[.!?])\s+", plain)
    # Take first 2 sentences, cap at 160 chars
    dek = " ".join(sentences[:2])
    if len(dek) > 160:
        dek = dek[:157] + "..."
    return dek


def build_meta_description(title: str, dek: str) -> str:
    base = f"{title}. {dek}"
    if len(base) > 155:
        base = base[:152] + "..."
    return base


def build_card_summary(body_html: str) -> str:
    """Pull the first paragraph after the first <h2> as card summary."""
    # Try to find first <p> after a heading
    match = re.search(r"<h2[^>]*>.*?</h2>\s*<p[^>]*>(.*?)</p>", body_html, re.DOTALL | re.IGNORECASE)
    if match:
        text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if len(text) > 200:
            text = text[:197] + "..."
        return text
    # Fallback: first <p>
    match = re.search(r"<p[^>]*>(.*?)</p>", body_html, re.DOTALL | re.IGNORECASE)
    if match:
        text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if len(text) > 200:
            text = text[:197] + "..."
        return text
    return ""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not ARTICLES_FILE.exists():
        print(f"[ERROR] {ARTICLES_FILE} not found — run fetch_rss.py + rewrite_feed.py first")
        return

    with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
        articles: list[dict] = json.load(f)

    print(f"[INFO] Loaded {len(articles)} articles from generated_articles.json")

    to_process = [a for a in articles if needs_reprocessing(a)]
    print(f"[INFO] {len(to_process)} articles need enrichment (word_count < {REPROCESS_THRESHOLD} or missing H2 headings)")

    if not to_process:
        print("[INFO] All articles already meet quality threshold — nothing to do")
        return

    processed = 0
    changed   = 0

    for article in articles:
        if not needs_reprocessing(article):
            continue
        if processed >= MAX_PER_RUN:
            print(f"[INFO] Hit MAX_PER_RUN={MAX_PER_RUN} — remaining articles will be processed on next run")
            break

        slug     = article.get("slug", article.get("id", "unknown"))
        title    = article.get("title", "Untitled")
        category = article.get("category", "Broadcast Technology")

        print(f"  → [{processed+1}/{min(len(to_process), MAX_PER_RUN)}] Processing: {slug}")

        source_text = extract_source_text(article)
        new_body    = call_groq(title, source_text, category)

        if not new_body:
            print(f"    [SKIP] Groq returned nothing for: {slug}")
            processed += 1
            time.sleep(1)
            continue

        # Validate that Groq actually gave us structured content
        wc = count_words(new_body)
        if wc < 300:
            print(f"    [WARN] Generated body only {wc} words — skipping (prompt may need adjustment)")
            processed += 1
            time.sleep(1)
            continue

        # Update article fields
        article["body_html"]        = new_body
        article["word_count"]       = wc
        article["is_editorial"]     = True
        article["dek"]              = build_dek(title, new_body)
        article["meta_description"] = build_meta_description(title, article["dek"])
        article["card_summary"]     = build_card_summary(new_body)

        # Also persist to per-article summary file (so future runs can detect it)
        summary_file = SUMMARIES_DIR / f"{slug}.json"
        with open(summary_file, "w", encoding="utf-8") as sf:
            json.dump({
                "slug":             slug,
                "title":            title,
                "body_html":        new_body,
                "word_count":       wc,
                "dek":              article["dek"],
                "card_summary":     article["card_summary"],
                "meta_description": article["meta_description"],
            }, sf, ensure_ascii=False, indent=2)

        print(f"    ✓ {wc} words, {len(re.findall('<h2', new_body))} sections → {slug}")

        processed += 1
        changed   += 1

        # Groq free tier: ~30 req/min — small sleep to stay safe
        time.sleep(2.5)

    # Write enriched articles back to JSON
    if changed > 0:
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"\n[DONE] Enriched {changed} articles → saved to {ARTICLES_FILE}")
    else:
        print("\n[DONE] No articles were changed (all Groq calls returned empty or too-short content)")


if __name__ == "__main__":
    main()
