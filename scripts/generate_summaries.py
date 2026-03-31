#!/usr/bin/env python3
"""
generate_summaries.py  —  The Streamic
Enriches data/generated_articles.json with 1000-word Gemini/Groq analysis.

Fixes applied:
  • gemini-2.0-flash (200 req/day) → gemini-1.5-flash (1500 req/day)
  • llama3-70b-8192 (deprecated 400 error) → llama-3.3-70b-versatile
  • Exponential backoff retry on 429 (rate limit) for both APIs
  • Longer inter-request sleep (12s) to stay under 15 RPM free tier
  • Source text capped at 1500 chars to keep prompts within token limits
  • Detailed error logging so failures are diagnosable in CI
"""

import json
import os
import re
import time
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")

# gemini-1.5-flash: 15 RPM, 1500 RPD free tier  (was gemini-2.0-flash: 200 RPD only)
GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_URL   = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

# llama-3.3-70b-versatile: current Groq model name  (was llama3-70b-8192 → 400 error)
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

DATA_DIR      = Path(__file__).parent.parent / "data"
ARTICLES_FILE = DATA_DIR / "generated_articles.json"
SUMMARIES_DIR = DATA_DIR / "summaries"

# Reprocess threshold — articles below this word count get regenerated
REPROCESS_THRESHOLD = 700

# Max articles per CI run to stay within daily quota:
#   gemini-1.5-flash free = 1500 req/day, pipeline runs every 6h = 4x/day
#   Safe per-run budget = 1500 / 4 = 375; we use 12 to be conservative
#   and avoid consuming quota needed by generate_editorial.py
MAX_PER_RUN = 12

# Sleep between requests (seconds).
# 15 RPM limit = 1 request per 4s minimum; 12s gives comfortable headroom
INTER_REQUEST_SLEEP = 12

# Retry settings for 429 rate-limit responses
MAX_RETRIES    = 3
RETRY_BACKOFF  = [30, 60, 120]   # seconds to wait before each retry

SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)


# ── Prompts ───────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are a senior broadcast technology and media IT journalist writing for \
The Streamic (thestreamic.in), an independent editorial publication for \
broadcast engineers, media technology directors, and streaming platform operators.

Your writing is analytical, authoritative, and practitioner-focused — \
similar to TVBEurope in-depth analysis or the Financial Times technology desk. \
You write for people who already understand broadcast infrastructure, \
not general consumers. Never use marketing language or phrases like \
"game-changing" or "exciting announcement".\
"""


def build_prompt(title: str, source_text: str, category: str) -> str:
    # Cap source text to keep total prompt within token limits for both APIs
    source_capped = source_text[:1500] if len(source_text) > 1500 else source_text

    return f"""\
Write a substantive 1000-word broadcast industry analysis article.

TITLE: {title}
CATEGORY: {category}
SOURCE:
{source_capped}

REQUIREMENTS (follow exactly):

1. Return ONLY valid HTML fragments — no <!DOCTYPE>, <html>, <head>, <body>.
   Start immediately with <h2>.

2. Use exactly these five <h2> sections (no others):
   <h2>What Was Announced</h2>
   <h2>The Engineering and Operational Significance</h2>
   <h2>Industry Context and Competitive Landscape</h2>
   <h2>Workflow and Infrastructure Implications</h2>
   <h2>The Streamic Analysis</h2>

3. Total length: 950–1050 words. Each section: 3–5 full analytical sentences.
   Analytically dense — no padding, no repetition.

4. Tone: confident, technical, editorial. Zero marketing language.
   If something is incremental rather than truly new, say so plainly.

5. Use correct broadcast terminology where accurate:
   AES67, SMPTE ST 2110, SDI, MAM, PAM, FAST, ABR, CDN, playout,
   ingest, EPG, metadata, rights management, transcoding — only where applicable.

6. "The Streamic Analysis" must be genuine editorial opinion:
   what does this mean for the industry 12–24 months from now?

7. All prose — no bullet lists anywhere.

8. Do not include a title, headline, byline, or article header.

Begin with the first <h2> tag now:\
"""


# ── API wrappers with retry ───────────────────────────────────────────────────
def _call_with_retry(fn, label: str):
    """Call fn() with exponential backoff on 429 errors."""
    for attempt in range(MAX_RETRIES):
        result = fn()
        if result is not None:
            return result
        if attempt < MAX_RETRIES - 1:
            wait = RETRY_BACKOFF[attempt]
            print(f"    [{label}] Retrying in {wait}s (attempt {attempt + 2}/{MAX_RETRIES})...")
            time.sleep(wait)
    return None


def _gemini_once(title: str, source_text: str, category: str):
    if not GEMINI_API_KEY:
        return None
    full_prompt = f"{SYSTEM_PROMPT}\n\n{build_prompt(title, source_text, category)}"
    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "temperature":     0.40,
            "maxOutputTokens": 1800,
            "topP":            0.90,
        },
    }
    url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
    try:
        resp = requests.post(url, json=payload, timeout=90)
        if resp.status_code == 429:
            print(f"    [Gemini] 429 rate limit — will retry")
            return None   # trigger retry
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except requests.exceptions.HTTPError as e:
        print(f"    [WARN] Gemini HTTP {resp.status_code}: {resp.text[:300]}")
        return None
    except Exception as e:
        print(f"    [WARN] Gemini error: {e}")
        return None


def call_gemini(title: str, source_text: str, category: str) -> str | None:
    return _call_with_retry(
        lambda: _gemini_once(title, source_text, category),
        "Gemini"
    )


def _groq_once(title: str, source_text: str, category: str):
    if not GROQ_API_KEY:
        return None
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
    try:
        resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=90)
        if resp.status_code == 429:
            print(f"    [Groq] 429 rate limit — will retry")
            return None   # trigger retry
        if resp.status_code != 200:
            print(f"    [WARN] Groq HTTP {resp.status_code}: {resp.text[:300]}")
            return None
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"    [WARN] Groq error: {e}")
        return None


def call_groq(title: str, source_text: str, category: str) -> str | None:
    return _call_with_retry(
        lambda: _groq_once(title, source_text, category),
        "Groq"
    )


def generate_body(title: str, source_text: str, category: str) -> str | None:
    """Try Gemini first; fall back to Groq on failure."""
    result = call_gemini(title, source_text, category)
    if result:
        print("    [API] Gemini ✓")
        return result
    result = call_groq(title, source_text, category)
    if result:
        print("    [API] Groq fallback ✓")
        return result
    print("    [ERROR] Both APIs failed for this article")
    return None


# ── Article helpers ───────────────────────────────────────────────────────────
def needs_reprocessing(article: dict) -> bool:
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
    if not ARTICLES_FILE.exists():
        print(f"[ERROR] {ARTICLES_FILE} not found — run fetch_rss.py and rewrite_feed.py first")
        return

    if not GEMINI_API_KEY and not GROQ_API_KEY:
        print("[ERROR] Neither GEMINI_API_KEY nor GROQ_API_KEY is set")
        return

    active_apis = []
    if GEMINI_API_KEY: active_apis.append(f"Gemini/{GEMINI_MODEL} (primary)")
    if GROQ_API_KEY:   active_apis.append(f"Groq/{GROQ_MODEL} (fallback)")
    print(f"[INFO] APIs: {', '.join(active_apis)}")
    print(f"[INFO] Rate limit sleep: {INTER_REQUEST_SLEEP}s between requests")
    print(f"[INFO] Retry backoff: {RETRY_BACKOFF}s on 429")

    with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
        articles: list[dict] = json.load(f)

    to_process = [a for a in articles if needs_reprocessing(a)]
    total_need = len(to_process)
    this_run   = min(total_need, MAX_PER_RUN)

    print(f"[INFO] {len(articles)} total articles — {total_need} need enrichment")
    print(f"[INFO] Processing {this_run} this run (MAX_PER_RUN={MAX_PER_RUN})")
    if total_need > MAX_PER_RUN:
        remaining = total_need - MAX_PER_RUN
        print(f"[INFO] {remaining} articles will be processed on subsequent pipeline runs")

    processed = changed = 0

    for article in articles:
        if not needs_reprocessing(article):
            continue
        if processed >= MAX_PER_RUN:
            break

        slug     = article.get("slug") or article.get("id") or f"article-{processed}"
        title    = (article.get("title") or "Untitled").strip()
        category = article.get("category") or "Broadcast Technology"

        print(f"\n  [{processed + 1}/{this_run}] {slug[:70]}")
        print(f"    Title: {title[:75]}")

        source_text = extract_source_text(article)
        if len(source_text.strip()) < 20:
            print(f"    [SKIP] Source text too short to generate meaningful analysis")
            processed += 1
            continue

        new_body = generate_body(title, source_text, category)
        processed += 1

        if not new_body:
            # Sleep before next attempt even on failure
            time.sleep(INTER_REQUEST_SLEEP)
            continue

        wc       = count_words(new_body)
        h2_count = len(re.findall(r"<h2", new_body, re.IGNORECASE))

        if wc < 400:
            print(f"    [SKIP] Generated only {wc} words — too short, skipping")
            time.sleep(INTER_REQUEST_SLEEP)
            continue

        article["body_html"]        = new_body
        article["word_count"]       = wc
        article["is_editorial"]     = True
        article["dek"]              = build_dek(new_body)
        article["meta_description"] = (
            (article["dek"][:155] + "...") if len(article["dek"]) > 155
            else article["dek"]
        )
        article["card_summary"] = build_card_summary(new_body)

        # Persist per-article summary file for future change detection
        summary_file = SUMMARIES_DIR / f"{slug}.json"
        with open(summary_file, "w", encoding="utf-8") as sf:
            json.dump(
                {k: article[k] for k in (
                    "slug", "title", "body_html", "word_count",
                    "dek", "card_summary", "meta_description", "is_editorial"
                ) if k in article},
                sf, ensure_ascii=False, indent=2
            )

        changed += 1
        print(f"    ✓ {wc} words | {h2_count} sections written")

        # Respect free-tier RPM — sleep between every successful request
        time.sleep(INTER_REQUEST_SLEEP)

    if changed > 0:
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"\n[DONE] Enriched {changed}/{processed} articles → saved to generated_articles.json")
    else:
        print(f"\n[DONE] 0 articles changed (check API errors above)")


if __name__ == "__main__":
    main()
