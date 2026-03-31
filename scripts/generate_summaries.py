#!/usr/bin/env python3
"""
generate_summaries.py  —  The Streamic
Stage 5b: Groq-only card summaries (secondary fallback to generate_gemini.py).

NOTE: Gemini is handled exclusively by generate_gemini.py (Stage 5).
This script is Groq-only to avoid model conflicts and quota collisions.

Fixes applied:
  • Removed Gemini calls entirely (gemini-1.5-flash 404; gemini-2.0-flash 200 RPD)
  • Model: llama3-70b-8192 (deprecated → 400) → llama-3.3-70b-versatile
  • Reads GROQ_MAX_PER_RUN env var (generate.yml sets this to "4" for daily runs)
  • Skips articles already processed by generate_gemini.py (generated_by=gemini-2.5-pro)
  • Exponential backoff retry on 429
  • 8s inter-request sleep (safe for Groq 30 RPM free tier)
"""

import json
import os
import re
import time
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL   = "llama-3.3-70b-versatile"   # current name; llama3-70b-8192 is deprecated
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

DATA_DIR      = Path(__file__).parent.parent / "data"
ARTICLES_FILE = DATA_DIR / "generated_articles.json"
SUMMARIES_DIR = DATA_DIR / "summaries"

# Read from env so workflow can cap usage; generate.yml sets GROQ_MAX_PER_RUN=4
MAX_PER_RUN         = int(os.environ.get("GROQ_MAX_PER_RUN", "12"))
REPROCESS_THRESHOLD = 700   # enrich articles below this word count
INTER_REQUEST_SLEEP = 8     # seconds between calls (30 RPM free tier = 2s min; 8s = safe)
MAX_RETRIES         = 3
RETRY_BACKOFF       = [20, 45, 90]  # seconds to wait on consecutive 429s

SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)


# ── Prompts ───────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are a senior broadcast technology and media IT journalist at The Streamic \
(thestreamic.in), writing for broadcast engineers, media technology directors, \
and OTT platform operators. Your writing is analytical, confident, and \
practitioner-focused — like TVBEurope in-depth analysis or the Financial Times \
technology desk. You write for people who already understand broadcast \
infrastructure. Never use marketing language or phrases like "game-changing", \
"seamless", or "exciting announcement".\
"""


def build_prompt(title: str, source_text: str, category: str) -> str:
    # Cap source to avoid token limit errors on Groq
    src = source_text[:1500] if len(source_text) > 1500 else source_text
    return f"""\
Write a 1000-word broadcast industry analysis article.

TITLE: {title}
CATEGORY: {category}
SOURCE CONTENT:
{src}

STRICT REQUIREMENTS:

1. Return ONLY valid HTML fragments. No <!DOCTYPE>, <html>, <head>, or <body> tags.
   Start immediately with the first <h2> tag.

2. Use exactly these five <h2> sections in this order:
   <h2>What Was Announced</h2>
   <h2>The Engineering and Operational Significance</h2>
   <h2>Industry Context and Competitive Landscape</h2>
   <h2>Workflow and Infrastructure Implications</h2>
   <h2>The Streamic Analysis</h2>

3. Total length: 950–1050 words. Each section: 3–5 full analytical sentences.
   Be analytically dense — no padding, no repetition.

4. Tone: confident, technical, editorial. Zero marketing language.
   If something is incremental rather than truly new, say so plainly.

5. Use correct broadcast terminology where genuinely applicable:
   AES67, SMPTE ST 2110, SDI, MAM, PAM, FAST channels, ABR, CDN, playout,
   ingest, EPG, metadata, rights management, transcoding.

6. "The Streamic Analysis" must be genuine editorial opinion:
   what does this mean for the industry 12–24 months from now?
   What should engineers or technology managers specifically watch?

7. All prose paragraphs — no bullet lists anywhere.

8. Do not include a title, headline, byline, or any article header.

Begin with the first <h2> tag now:\
"""


# ── Groq API with retry ───────────────────────────────────────────────────────
def call_groq(title: str, source_text: str, category: str) -> str | None:
    payload = {
        "model":       GROQ_MODEL,
        "max_tokens":  1800,
        "temperature": 0.42,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": build_prompt(title, source_text, category)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=90)

            if resp.status_code == 429:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                print(f"    [Groq] 429 rate limit — waiting {wait}s "
                      f"(attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                print(f"    [WARN] Groq HTTP {resp.status_code}: {resp.text[:300]}")
                return None

            content = resp.json()["choices"][0]["message"]["content"].strip()
            return content

        except Exception as exc:
            print(f"    [WARN] Groq exception (attempt {attempt + 1}): {exc}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(5)

    return None


# ── Article helpers ───────────────────────────────────────────────────────────
def already_gemini_processed(slug: str) -> bool:
    """Skip articles generate_gemini.py already handled at high quality."""
    sf = SUMMARIES_DIR / f"{slug}.json"
    if not sf.exists():
        return False
    try:
        s = json.loads(sf.read_text(encoding="utf-8"))
        return (
            s.get("generated_by") == "gemini-2.5-pro"
            and int(s.get("word_count", 0)) >= 700
        )
    except Exception:
        return False


def needs_reprocessing(article: dict) -> bool:
    slug = article.get("slug", "")
    if already_gemini_processed(slug):
        return False   # Gemini already did this one — don't overwrite
    body = article.get("body_html", "")
    wc   = article.get("word_count", 0)
    if not body or len(body.strip()) < 150:
        return True
    if wc < REPROCESS_THRESHOLD:
        return True
    if "<h2" not in body.lower():
        return True
    return False


def count_words(html: str) -> int:
    return len(re.sub(r"<[^>]+>", " ", html).split())


def extract_source_text(article: dict) -> str:
    parts = []
    for field in ("dek", "card_summary"):
        v = (article.get(field) or "").strip()
        if v and len(v) > 20:
            parts.append(v)
    body = (article.get("body_html") or "").strip()
    if body:
        plain = re.sub(r"<[^>]+>", " ", body)
        plain = re.sub(r"\s+", " ", plain).strip()
        if len(plain) > 40:
            parts.append(plain)
    if not parts:
        parts.append(article.get("title") or "")
    return "\n\n".join(parts)


def build_dek(body_html: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", body_html)
    plain = re.sub(r"\s+", " ", plain).strip()
    sentences = re.split(r"(?<=[.!?])\s+", plain)
    dek = " ".join(sentences[:2])
    return (dek[:200] + "...") if len(dek) > 200 else dek


def build_card_summary(body_html: str) -> str:
    m = re.search(
        r"<h2[^>]*>.*?</h2>\s*<p[^>]*>(.*?)</p>",
        body_html, re.DOTALL | re.IGNORECASE
    )
    if not m:
        m = re.search(r"<p[^>]*>(.*?)</p>", body_html, re.DOTALL | re.IGNORECASE)
    if m:
        text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        return (text[:220] + "...") if len(text) > 220 else text
    return ""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not GROQ_API_KEY:
        print("[INFO] GROQ_API_KEY not set — skipping")
        return

    if not ARTICLES_FILE.exists():
        print(f"[ERROR] {ARTICLES_FILE} not found — run fetch_rss.py and rewrite_feed.py first")
        return

    print(f"[INFO] Groq model  : {GROQ_MODEL}")
    print(f"[INFO] Max per run : {MAX_PER_RUN} (env: GROQ_MAX_PER_RUN)")
    print(f"[INFO] Sleep       : {INTER_REQUEST_SLEEP}s between requests")

    with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
        articles: list[dict] = json.load(f)

    to_process = [a for a in articles if needs_reprocessing(a)]
    total_need = len(to_process)
    this_run   = min(total_need, MAX_PER_RUN)

    print(f"[INFO] {len(articles)} total articles")
    print(f"[INFO] {total_need} need Groq enrichment — processing {this_run} this run")
    if total_need > MAX_PER_RUN:
        print(f"[INFO] {total_need - MAX_PER_RUN} queued for subsequent runs")

    processed = changed = 0

    for article in articles:
        if not needs_reprocessing(article):
            continue
        if processed >= MAX_PER_RUN:
            break

        slug     = article.get("slug") or f"article-{processed}"
        title    = (article.get("title") or "Untitled").strip()
        category = article.get("category") or "Broadcast Technology"

        print(f"\n  [{processed + 1}/{this_run}] {slug[:65]}")
        print(f"    Title: {title[:70]}")

        source_text = extract_source_text(article)
        if len(source_text.strip()) < 20:
            print("    [SKIP] Source text too short to generate meaningful analysis")
            processed += 1
            continue

        new_body = call_groq(title, source_text, category)
        processed += 1

        if not new_body:
            print("    [ERROR] Groq returned nothing — skipping")
            time.sleep(INTER_REQUEST_SLEEP)
            continue

        wc = count_words(new_body)
        if wc < 400:
            print(f"    [SKIP] Only {wc} words generated — too short")
            time.sleep(INTER_REQUEST_SLEEP)
            continue

        # Update article
        article["body_html"]        = new_body
        article["word_count"]       = wc
        article["is_editorial"]     = True
        article["dek"]              = build_dek(new_body)
        article["meta_description"] = (
            (article["dek"][:155] + "...")
            if len(article["dek"]) > 155 else article["dek"]
        )
        article["card_summary"] = build_card_summary(new_body)

        # Persist per-article summary so generate_gemini.py can detect it
        summary_file = SUMMARIES_DIR / f"{slug}.json"
        summary_file.write_text(
            json.dumps(
                {
                    "slug":             slug,
                    "title":            title,
                    "body_html":        new_body,
                    "word_count":       wc,
                    "dek":              article["dek"],
                    "card_summary":     article["card_summary"],
                    "meta_description": article["meta_description"],
                    "generated_by":     "groq-llama-3.3-70b",
                },
                ensure_ascii=False, indent=2
            ),
            encoding="utf-8"
        )

        changed += 1
        h2s = len(re.findall(r"<h2", new_body, re.IGNORECASE))
        print(f"    [Groq] ✓ {wc} words | {h2s} sections")

        time.sleep(INTER_REQUEST_SLEEP)

    if changed > 0:
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"\n[DONE] Enriched {changed}/{processed} articles → generated_articles.json")
    else:
        print(f"\n[DONE] 0 articles changed — check errors above")


if __name__ == "__main__":
    main()
