#!/usr/bin/env python3
"""
generate_summaries.py  —  The Streamic
Enriches data/generated_articles.json with 1000-word Groq/Gemini analysis.

Uses Gemini Flash as primary (free, fast, better at long content).
Falls back to Groq LLaMA if Gemini key not set.
Force-reprocesses any article with word_count < 700 or missing <h2> tags.
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

GEMINI_MODEL   = "gemini-2.0-flash"
GEMINI_URL     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

GROQ_MODEL     = "llama3-70b-8192"
GROQ_URL       = "https://api.groq.com/openai/v1/chat/completions"

DATA_DIR       = Path(__file__).parent.parent / "data"
ARTICLES_FILE  = DATA_DIR / "generated_articles.json"
SUMMARIES_DIR  = DATA_DIR / "summaries"

REPROCESS_THRESHOLD = 700   # reprocess if word_count below this
MAX_PER_RUN         = int(os.environ.get("GROQ_MAX_PER_RUN", "4"))  # workflow sets GROQ_MAX_PER_RUN=4

SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)


# ── Prompt ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a senior broadcast technology and media IT journalist writing for The Streamic (thestreamic.in), an independent editorial publication for broadcast engineers, media technology directors, and streaming platform operators.

Your writing is analytical, authoritative, and practitioner-focused — similar to TVBEurope's in-depth analysis or the Financial Times technology desk. You write for people who already understand broadcast infrastructure, not general consumers. You never use marketing language or phrases like "game-changing" or "exciting announcement"."""


def build_prompt(title: str, source_text: str, category: str) -> str:
    return f"""Write a substantive 1000-word broadcast industry analysis article based on the following news item.

TITLE: {title}
CATEGORY: {category}
SOURCE CONTENT:
{source_text}

---

STRICT REQUIREMENTS:

1. OUTPUT FORMAT: Return ONLY valid HTML fragments. No <!DOCTYPE>, <html>, <head>, <body> tags. Start with <p> or <h2>.

2. MANDATORY STRUCTURE — use exactly these five <h2> sections:
   <h2>What Was Announced</h2>
   <h2>The Engineering and Operational Significance</h2>
   <h2>Industry Context and Competitive Landscape</h2>
   <h2>Workflow and Infrastructure Implications</h2>
   <h2>The Streamic Analysis</h2>

3. WORD COUNT: 950–1050 words across all five sections. Each section must be 3–5 full analytical sentences. Do NOT pad with filler — be analytically dense.

4. TONE: Confident, technical, editorial. Zero marketing language. Explain significance as a journalist, not a publicist. If something is incremental rather than truly new, say so.

5. TECHNICAL SPECIFICITY: Use correct broadcast terminology where accurate — AES67, SMPTE ST 2110, SDI, MAM/PAM, FAST channels, playout automation, ABR ladder, CDN, transcoding, metadata, rights management, EPG, etc. Only use terms that genuinely apply to this story.

6. "The Streamic Analysis" section must be a genuine editorial opinion paragraph — what does this mean for the industry 12–24 months from now? What should engineers or technology managers take note of?

7. All prose, no bullet lists. Every section is connected prose paragraphs only.

8. Do not include a title, headline, byline, or article header — only the five body sections.

Begin immediately with the first <h2> tag:"""


# ── API calls ─────────────────────────────────────────────────────────────────
def call_gemini(title: str, source_text: str, category: str) -> str | None:
    if not GEMINI_API_KEY:
        return None
    prompt = f"{SYSTEM_PROMPT}\n\n{build_prompt(title, source_text, category)}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":     0.40,
            "maxOutputTokens": 1800,
            "topP":            0.90,
        },
    }
    url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
    try:
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"    [WARN] Gemini failed: {e}")
        return None


def call_groq(title: str, source_text: str, category: str) -> str | None:
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
        resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"    [WARN] Groq failed: {e}")
        return None


def generate_body(title: str, source_text: str, category: str) -> str | None:
    """Try Gemini first, fall back to Groq."""
    result = call_gemini(title, source_text, category)
    if result:
        print("    [API] Gemini ✓")
        return result
    result = call_groq(title, source_text, category)
    if result:
        print("    [API] Groq fallback ✓")
        return result
    print("    [ERROR] Both APIs failed")
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────
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
        v = article.get(field, "")
        if v:
            parts.append(v)
    body = article.get("body_html", "")
    if body:
        plain = re.sub(r"<[^>]+>", " ", body)
        plain = re.sub(r"\s+", " ", plain).strip()
        if len(plain) > 80:
            parts.append(plain[:2000])   # cap source text sent to API
    if not parts:
        parts.append(article.get("title", ""))
    return "\n\n".join(parts)


def build_dek(body_html: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", body_html)
    plain = re.sub(r"\s+", " ", plain).strip()
    sentences = re.split(r"(?<=[.!?])\s+", plain)
    dek = " ".join(sentences[:2])
    return dek[:200] + "..." if len(dek) > 200 else dek


def build_card_summary(body_html: str) -> str:
    # First <p> after a <h2>
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
        print(f"[ERROR] {ARTICLES_FILE} not found")
        return

    if not GEMINI_API_KEY and not GROQ_API_KEY:
        print("[ERROR] Neither GEMINI_API_KEY nor GROQ_API_KEY is set — nothing to do")
        return

    api_note = []
    if GEMINI_API_KEY: api_note.append("Gemini (primary)")
    if GROQ_API_KEY:   api_note.append("Groq (fallback)")
    print(f"[INFO] APIs available: {', '.join(api_note)}")

    with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
        articles: list[dict] = json.load(f)

    to_process = [a for a in articles if needs_reprocessing(a)]
    print(f"[INFO] {len(articles)} total articles — {len(to_process)} need enrichment (< {REPROCESS_THRESHOLD} words or missing <h2>)")

    if not to_process:
        print("[INFO] All articles already meet quality threshold")
        return

    processed = changed = 0

    for article in articles:
        if not needs_reprocessing(article):
            continue
        if processed >= MAX_PER_RUN:
            print(f"[INFO] Reached MAX_PER_RUN={MAX_PER_RUN}. Remaining articles will process on next run.")
            break

        slug     = article.get("slug", article.get("id", "unknown"))
        title    = article.get("title", "Untitled")
        category = article.get("category", "Broadcast Technology")

        print(f"\n  [{processed+1}/{min(len(to_process), MAX_PER_RUN)}] {slug}")
        print(f"    Title: {title[:80]}")

        source_text = extract_source_text(article)
        new_body    = generate_body(title, source_text, category)
        processed  += 1

        if not new_body:
            time.sleep(30)
            continue

        wc = count_words(new_body)
        h2_count = len(re.findall(r"<h2", new_body, re.IGNORECASE))

        if wc < 500:
            print(f"    [SKIP] Only {wc} words generated — skipping (API may be returning short content)")
            time.sleep(30)
            continue

        # Update the article record
        article["body_html"]        = new_body
        article["word_count"]       = wc
        article["is_editorial"]     = True
        article["dek"]              = build_dek(new_body)
        article["meta_description"] = (article["dek"][:155] + "...") if len(article["dek"]) > 155 else article["dek"]
        article["card_summary"]     = build_card_summary(new_body)

        # Persist to per-article summary file
        summary_file = SUMMARIES_DIR / f"{slug}.json"
        with open(summary_file, "w", encoding="utf-8") as sf:
            json.dump({k: article[k] for k in (
                "slug", "title", "body_html", "word_count",
                "dek", "card_summary", "meta_description", "is_editorial"
            ) if k in article}, sf, ensure_ascii=False, indent=2)

        changed += 1
        print(f"    ✓ {wc} words | {h2_count} sections | saved")

        # Rate-limit safety: Gemini free tier = 15 req/min; Groq = 30 req/min
        time.sleep(30)

    # Write all enriched articles back
    if changed > 0:
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"\n[DONE] Enriched {changed}/{processed} articles → {ARTICLES_FILE}")
    else:
        print("\n[DONE] No articles were changed")


if __name__ == "__main__":
    main()
