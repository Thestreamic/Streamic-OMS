#!/usr/bin/env python3
"""
generate_summaries.py — The Streamic

Enriches data/generated_articles.json with substantive Groq-powered analysis.

Fixes included:
  • Replaces deprecated Groq model with a current supported one
  • Adds model fallback support via environment variable
  • Handles Groq/OpenAI-compatible response parsing more safely
  • Retries once on temporary rate/server failures
  • Preserves your existing enrichment logic and summary-file output
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import requests

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()

# Primary Groq model:
# Current supported replacement for deprecated llama3-70b-8192
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()

# Optional faster fallback if quotas/permissions differ
GROQ_FALLBACK_MODEL = os.environ.get("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant").strip()

GROQ_API_URL = os.environ.get(
    "GROQ_API_URL",
    "https://api.groq.com/openai/v1/chat/completions",
).strip()

DATA_DIR = Path(__file__).parent.parent / "data"
ARTICLES_FILE = DATA_DIR / "generated_articles.json"
SUMMARIES_DIR = DATA_DIR / "summaries"

# Reprocess if word_count is below this threshold
REPROCESS_THRESHOLD = int(os.environ.get("REPROCESS_THRESHOLD", "400"))

# Also reprocess if body_html has no <h2> headings
REQUIRE_HEADINGS = os.environ.get("REQUIRE_HEADINGS", "true").lower() in {"1", "true", "yes", "y"}

# Max articles to process per run
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "20"))

# Groq/OpenAI-compatible params
REQUEST_TIMEOUT = int(os.environ.get("GROQ_TIMEOUT", "60"))
MAX_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", "900"))
TEMPERATURE = float(os.environ.get("GROQ_TEMPERATURE", "0.45"))

SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

# ── Prompt ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a senior broadcast technology and media IT journalist writing for The Streamic (thestreamic.in), an independent editorial publication for broadcast engineers, media technology directors, and OTT platform professionals.

Your writing style is analytical and authoritative — similar to the Financial Times technology desk or TVBEurope's in-depth features. You write for practitioners who already understand the technology, not general consumers.

When you receive a news item, you write a structured analytical article that goes beyond the press release: you explain the engineering or operational significance, place it in industry context, and draw out implications for broadcast workflows.
"""

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
   • <h2>What Was Announced</h2> — factual summary of the news, 2–3 sentences
   • <h2>The Engineering and Operational Significance</h2> — why this matters technically, what problem it solves, what workflow change it enables (3–4 sentences, specific)
   • <h2>Industry Context</h2> — where this fits in the current broadcast/media IT landscape, any comparable approaches or competing technologies (3–4 sentences)
   • <h2>Implications for Broadcast and Media Teams</h2> — what engineers, operations managers or platform teams should take note of and why (3–4 sentences)

3. LENGTH: 500–600 words total across all four sections. Do not pad; be analytically dense.

4. TONE: Confident, technical, editorial. Do not use marketing language from the press release. No phrases like "exciting announcement" or "game-changing". Write as a journalist explaining significance, not a publicist.

5. BROADCAST-SPECIFIC: Use correct industry terminology (IP core, SDI, AES67, SMPTE ST 2110, OTT, MAM, PAM, ABR, CDN, playout, ingest, etc.) where relevant and accurate.

6. No bullet lists — all prose paragraphs inside the section structure above.

7. Do not include a byline, title, or article header — only the body sections.

Begin the article now:
"""

# ── Helpers ───────────────────────────────────────────────────────────────────
def needs_reprocessing(article: dict[str, Any]) -> bool:
    """Return True if this article should be (re-)processed by Groq."""
    body = article.get("body_html", "") or ""
    wc = int(article.get("word_count", 0) or 0)

    if not body or len(body.strip()) < 100:
        return True

    if wc < REPROCESS_THRESHOLD:
        return True

    if REQUIRE_HEADINGS and "<h2" not in body.lower():
        return True

    return False


def count_words(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return len(text.split()) if text else 0


def strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def extract_source_text(article: dict[str, Any]) -> str:
    """Build source text from available fields for the Groq prompt."""
    parts: list[str] = []

    for key in ("dek", "meta_description", "card_summary"):
        value = article.get(key)
        if value:
            parts.append(strip_html(str(value)))

    body = article.get("body_html", "")
    if body:
        plain = strip_html(body)
        if len(plain) > 80:
            parts.append(plain)

    source_url = article.get("source_url")
    if source_url:
        parts.append(f"Original source URL: {source_url}")

    source_domain = article.get("source_domain")
    if source_domain:
        parts.append(f"Source domain: {source_domain}")

    title = article.get("title", "")
    if not parts and title:
        parts.append(title)

    merged = "\n\n".join([p for p in parts if p]).strip()
    return merged[:12000]  # keep prompt size sane


def extract_message_content(data: dict[str, Any]) -> Optional[str]:
    """Extract assistant text from OpenAI-compatible response."""
    try:
        choices = data.get("choices") or []
        if not choices:
            return None

        message = choices[0].get("message") or {}
        content = message.get("content")

        if isinstance(content, str):
            return content.strip()

        # Some compatible APIs may return a content array
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
            joined = "".join(parts).strip()
            return joined or None

        return None
    except Exception:
        return None


def post_chat_completion(model: str, title: str, source_text: str, category: str) -> Optional[str]:
    """Single Groq API attempt."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(title, source_text, category)},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "n": 1,
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    resp = requests.post(
        GROQ_API_URL,
        json=payload,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    if resp.status_code >= 400:
        body = resp.text[:500].replace("\n", " ")
        raise requests.exceptions.HTTPError(
            f"{resp.status_code} {resp.reason} — {body}",
            response=resp,
        )

    data = resp.json()
    return extract_message_content(data)


def call_groq(title: str, source_text: str, category: str) -> Optional[str]:
    """Call Groq API with retry and fallback model."""
    if not GROQ_API_KEY:
        print("  [WARN] GROQ_API_KEY not set — skipping API call")
        return None

    models_to_try = []
    for m in (GROQ_MODEL, GROQ_FALLBACK_MODEL):
        if m and m not in models_to_try:
            models_to_try.append(m)

    for model_index, model in enumerate(models_to_try, start=1):
        for attempt in range(1, 3):  # 2 tries per model
            try:
                if attempt > 1:
                    time.sleep(3)

                result = post_chat_completion(model, title, source_text, category)
                if result:
                    if model_index > 1:
                        print(f"    [INFO] Used fallback model: {model}")
                    return result
                return None

            except requests.exceptions.HTTPError as e:
                msg = str(e)

                # Temporary / retryable
                if any(code in msg for code in ("429", "500", "502", "503", "504")):
                    print(f"  [WARN] Temporary Groq HTTP issue on {model}, attempt {attempt}/2: {msg[:220]}")
                    continue

                # Non-retryable for this model: move to next model
                print(f"  [ERROR] Groq HTTP error on {model}: {msg[:260]}")
                break

            except requests.exceptions.RequestException as e:
                print(f"  [WARN] Network/API error on {model}, attempt {attempt}/2: {e}")
                continue

            except Exception as e:
                print(f"  [ERROR] Groq call failed on {model}: {e}")
                break

    return None


def build_dek(title: str, body_html: str) -> str:
    """Generate a 1-sentence dek from the first paragraph of body."""
    plain = strip_html(body_html)
    sentences = re.split(r"(?<=[.!?])\s+", plain)
    dek = " ".join(sentences[:2]).strip()

    if not dek:
        dek = title.strip()

    if len(dek) > 160:
        dek = dek[:157].rstrip() + "..."

    return dek


def build_meta_description(title: str, dek: str) -> str:
    base = f"{title}. {dek}".strip()
    if len(base) > 155:
        base = base[:152].rstrip() + "..."
    return base


def build_card_summary(body_html: str) -> str:
    """Pull the first paragraph after the first <h2> as card summary."""
    match = re.search(
        r"<h2[^>]*>.*?</h2>\s*<p[^>]*>(.*?)</p>",
        body_html or "",
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        text = strip_html(match.group(1))
        if len(text) > 200:
            text = text[:197].rstrip() + "..."
        return text

    match = re.search(r"<p[^>]*>(.*?)</p>", body_html or "", re.DOTALL | re.IGNORECASE)
    if match:
        text = strip_html(match.group(1))
        if len(text) > 200:
            text = text[:197].rstrip() + "..."
        return text

    return ""


def save_summary_file(
    slug: str,
    title: str,
    body_html: str,
    word_count: int,
    dek: str,
    card_summary: str,
    meta_description: str,
) -> None:
    summary_file = SUMMARIES_DIR / f"{slug}.json"
    with open(summary_file, "w", encoding="utf-8") as sf:
        json.dump(
            {
                "slug": slug,
                "title": title,
                "body_html": body_html,
                "word_count": word_count,
                "dek": dek,
                "card_summary": card_summary,
                "meta_description": meta_description,
            },
            sf,
            ensure_ascii=False,
            indent=2,
        )


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    if not ARTICLES_FILE.exists():
        print(f"[ERROR] {ARTICLES_FILE} not found — run fetch/rewrite steps first")
        return

    with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
        articles: list[dict[str, Any]] = json.load(f)

    print(f"[INFO] Loaded {len(articles)} articles from generated_articles.json")

    to_process = [a for a in articles if needs_reprocessing(a)]
    print(
        f"[INFO] {len(to_process)} articles need enrichment "
        f"(word_count < {REPROCESS_THRESHOLD} or missing H2 headings)"
    )

    if not to_process:
        print("[INFO] All articles already meet quality threshold — nothing to do")
        return

    processed = 0
    changed = 0

    for article in articles:
        if not needs_reprocessing(article):
            continue

        if processed >= MAX_PER_RUN:
            print(f"[INFO] Hit MAX_PER_RUN={MAX_PER_RUN} — remaining articles will be processed on next run")
            break

        slug = article.get("slug") or article.get("id") or "unknown"
        title = article.get("title") or "Untitled"
        category = article.get("category") or "Broadcast Technology"

        print(f"  → [{processed + 1}/{min(len(to_process), MAX_PER_RUN)}] Processing: {slug}")

        source_text = extract_source_text(article)
        new_body = call_groq(title, source_text, category)

        if not new_body:
            print(f"    [SKIP] Groq returned nothing for: {slug}")
            processed += 1
            time.sleep(1.5)
            continue

        wc = count_words(new_body)
        h2_count = len(re.findall(r"<h2\b", new_body, flags=re.IGNORECASE))

        if wc < 300:
            print(f"    [WARN] Generated body only {wc} words — skipping")
            processed += 1
            time.sleep(1.5)
            continue

        if h2_count < 4:
            print(f"    [WARN] Generated body has only {h2_count} H2 sections — skipping")
            processed += 1
            time.sleep(1.5)
            continue

        article["body_html"] = new_body
        article["word_count"] = wc
        article["is_editorial"] = True
        article["editorial"] = True
        article["dek"] = build_dek(title, new_body)
        article["meta_description"] = build_meta_description(title, article["dek"])
        article["card_summary"] = build_card_summary(new_body)

        save_summary_file(
            slug=slug,
            title=title,
            body_html=new_body,
            word_count=wc,
            dek=article["dek"],
            card_summary=article["card_summary"],
            meta_description=article["meta_description"],
        )

        print(f"    ✓ {wc} words, {h2_count} sections → {slug}")

        processed += 1
        changed += 1

        # Small delay to stay gentle on rate limits
        time.sleep(2.0)

    if changed > 0:
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"\n[DONE] Enriched {changed} articles → saved to {ARTICLES_FILE}")
    else:
        print("\n[DONE] No articles were changed (all Groq calls returned empty or too-short content)")


if __name__ == "__main__":
    main()
