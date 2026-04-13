#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_mistral.py — Tier-1 generator using Mistral AI (free tier)

Pipeline position: runs FIRST in the AI cascade (before Gemini, Groq,
OpenRouter). Mistral's free tier offers 1 billion tokens/month per model
— far more generous than Gemini's daily quota — so it can handle the
bulk of daily article enrichment.

FACTUAL INTEGRITY DISCIPLINE (same as Gemini / Groq / OpenRouter):
  1. FACTUAL_SAFETY_BLOCK (NotebookLM protocol) prepended to every call:
     - Strict grounding: only source text, no outside knowledge
     - 16-vendor safe-list prevents category misclassification
       (e.g., Mediagenix=scheduling NOT playout; Avid Nexis=storage NOT MAM)
     - Analogy rule for technical terms
     - Stay-vague override when source is ambiguous
     - Zero invented standards (ST 2110/NMOS/SCTE-35/AES67 only if
       source states them)
  2. FETCH_SOURCE mode: if the RSS body is short, fetch the original
     article URL and use that as ground truth.
  3. SOURCE VERIFICATION: the article URL is passed to the model
     so every [Source N] citation maps back to it.
  4. Tier-gating: never overwrites higher-tier output; only processes
     fresh scaffolds.
  5. 5 validation gates (word count, H2, Sources, Blind Spots, citations).
     Failure = article stays scaffold; no partial-quality output shipped.
  6. Temperature LOCKED at 0.1.

Setup:
  1. Get free API key at https://console.mistral.ai/api-keys/
  2. Add to GitHub repo: Settings → Secrets → Actions → MISTRAL_API_KEY

Environment:
  MISTRAL_API_KEY            — required
  MISTRAL_MAX_PER_RUN        — default 8
  MISTRAL_MODELS             — default "mistral-large-latest,mistral-medium-latest,mistral-small-latest"
  MISTRAL_TEMPERATURE        — default 0.1 (LOCKED LOW — do not raise)
  MISTRAL_TIMEOUT            — default 120s
  MISTRAL_FETCH_SOURCE       — default "true" — enrich thin scaffolds with
                               live source-page fetch for factual grounding
  MISTRAL_SOURCE_TIMEOUT     — default 15s per source fetch
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

import requests

# ── Shared NotebookLM protocol ───────────────────────────────────────────────
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from prompt_safety import FACTUAL_SAFETY_BLOCK
except ImportError:
    FACTUAL_SAFETY_BLOCK = ""

# ── Config ────────────────────────────────────────────────────────────────────
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "").strip()
MISTRAL_API_URL = os.environ.get(
    "MISTRAL_API_URL",
    "https://api.mistral.ai/v1/chat/completions",
).strip()

# Model cascade — try largest first, fall back on errors.
_DEFAULT_MODELS = [
    "mistral-large-latest",
    "mistral-medium-latest",
    "mistral-small-latest",
]
MISTRAL_MODELS = [
    m.strip() for m in
    os.environ.get("MISTRAL_MODELS", ",".join(_DEFAULT_MODELS)).split(",")
    if m.strip()
]

# LOCKED tuning
TEMPERATURE      = float(os.environ.get("MISTRAL_TEMPERATURE", "0.1"))
TOP_P            = float(os.environ.get("MISTRAL_TOP_P", "0.95"))
MAX_TOKENS       = int(os.environ.get("MISTRAL_MAX_TOKENS", "2000"))

MAX_PER_RUN      = int(os.environ.get("MISTRAL_MAX_PER_RUN", "15"))
REQUEST_TIMEOUT  = int(os.environ.get("MISTRAL_TIMEOUT", "120"))
INTER_CALL_SLEEP = int(os.environ.get("MISTRAL_SLEEP", "3"))

# Source-page fetching for factual grounding
FETCH_SOURCE        = os.environ.get("MISTRAL_FETCH_SOURCE", "true").lower() in {"1","true","yes","y"}
SOURCE_TIMEOUT      = int(os.environ.get("MISTRAL_SOURCE_TIMEOUT", "15"))
MIN_SOURCE_CHARS    = int(os.environ.get("MISTRAL_MIN_SOURCE_CHARS", "1200"))
MAX_SOURCE_CHARS    = int(os.environ.get("MISTRAL_MAX_SOURCE_CHARS", "8000"))

# Quality thresholds — identical to Gemini / Groq / OpenRouter.
# REPROCESS_THRESHOLD = 800: any article below 800 words is eligible for
# Mistral upgrade. This catches the backlog of 500-700w scaffolds that
# slipped past rewrite_feed but never got AI-enriched (Gemini quota hit,
# Groq TPD exhausted). Mistral's 1B tokens/month handles them.
REPROCESS_THRESHOLD = int(os.environ.get("REPROCESS_THRESHOLD", "800"))
REQUIRE_HEADINGS    = os.environ.get("REQUIRE_HEADINGS", "true").lower() in {"1","true","yes","y"}

DATA_DIR      = Path(__file__).parent.parent / "data"
ARTICLES_FILE = DATA_DIR / "generated_articles.json"


# ── Tier-1 gating: process fresh scaffolds only ──────────────────────────────
def needs_mistral(article: dict[str, Any]) -> bool:
    """Return True if this article should be processed by Mistral tier-1.

    Tier-1 ONLY processes untouched scaffolds. Anything already upgraded
    by any tier is sacred and skipped. This prevents overwriting quality
    output from earlier runs.
    """
    gen_by = (article.get("generated_by") or "").lower()

    # Already handled by any AI tier (including prior Mistral run): sacred.
    if gen_by.startswith("mistral"):
        return False
    if gen_by.startswith("gemini"):
        return False
    if "groq" in gen_by:
        return False
    if "deepseek" in gen_by or "openrouter" in gen_by:
        return False

    # Editorial / hand-authored content: protected.
    if article.get("is_editorial") or article.get("editorial"):
        return False
    if gen_by == "gpt_manual_editorial":
        return False

    # Only scaffolds are eligible.
    is_scaffold = gen_by in ("", "rewrite_feed_local", "rewrite_feed")
    if not is_scaffold:
        return False

    body = article.get("body_html", "") or ""
    wc   = int(article.get("word_count", 0) or 0)

    if not body or len(body.strip()) < 100:
        return True
    if wc < REPROCESS_THRESHOLD:
        return True
    if REQUIRE_HEADINGS and "<h2" not in body.lower():
        return True
    return False


# ── Source-page fetch for factual grounding ──────────────────────────────────
# If the RSS scaffold body is thin, we fetch the ORIGINAL source article
# to give the model real, verifiable ground truth instead of making it
# extrapolate from a 2-sentence RSS blurb. This is the key to 100%
# factual output on short-feed stories.
def fetch_source_body(url: str) -> str:
    """Fetch the live source article and extract plain-text body.

    Returns empty string on any failure — never raises. The caller will
    fall through to whatever body the RSS scaffold had.
    """
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; StreamicBot/1.0; "
                "+https://www.thestreamic.in/about)"
            ),
            "Accept": "text/html,application/xhtml+xml",
        }
        resp = requests.get(url, headers=headers, timeout=SOURCE_TIMEOUT)
        if resp.status_code != 200:
            return ""
        html = resp.text
    except Exception:
        return ""

    # Strip scripts, styles, nav, header, footer, aside — keep article body
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<nav[^>]*>.*?</nav>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<header[^>]*>.*?</header>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<footer[^>]*>.*?</footer>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<aside[^>]*>.*?</aside>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<form[^>]*>.*?</form>", " ", html, flags=re.S | re.I)

    # Prefer <article> or <main> if present
    m = re.search(r"<article[^>]*>(.*?)</article>", html, re.S | re.I)
    if not m:
        m = re.search(r"<main[^>]*>(.*?)</main>", html, re.S | re.I)
    if m:
        html = m.group(1)

    # Strip remaining HTML tags and normalize whitespace
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()

    # Cap length so prompt stays manageable
    return text[:MAX_SOURCE_CHARS]


# ── System prompt: NotebookLM protocol + Mistral-specific discipline ─────────
SYSTEM_PROMPT = FACTUAL_SAFETY_BLOCK + """

═══════════════════════════════════════════════════════════════════════════
TIER-1 MISTRAL GENERATION — FACTUAL INTEGRITY RULES
═══════════════════════════════════════════════════════════════════════════

You are running as The Streamic's tier-1 article generator. This is the
primary pass — your output is what readers will see. Get it right.

SOURCE-FIRST GROUNDING:
The user message contains the source material for this article. You MUST
treat it as the ONLY ground truth. If two pieces of source text are
provided (RSS scaffold + live source-page fetch), the live source page
takes precedence for factual claims.

Do NOT:
  - Invent products, model numbers, specs, dates, or partnerships not
    stated in the source
  - Extrapolate company strategy or intent beyond what is quoted
  - Add competitor comparisons the source did not make
  - Claim standards compliance (ST 2110, NMOS, SCTE-35, AES67, etc.)
    unless the source explicitly states it
  - Invent CVE IDs, NIST frameworks, or compliance claims
  - Assume vendor category — follow the vendor safe-list in the
    factual-safety block above

If the source is ambiguous, stay ambiguous. "The company has not
disclosed..." is always better than an invented specific.

REQUIRED STRUCTURE (ALL five must pass validation or output is rejected):
  ✓ At least 4 <h2> sections
  ✓ A <h3>Sources</h3> block with [Source N] entries at the end
  ✓ A <h2>Blind Spots</h2> section listing what the source did NOT say
  ✓ At least 2 inline [Source N] citations in the body
  ✓ At least 400 words of body text

If you cannot satisfy ALL 5 gates using ONLY the source material,
respond with less rather than inventing more. A short honest article
passes the gate. A long invented article gets rejected.

Do NOT include reasoning traces, preambles, or meta-commentary. Emit
only the structured HTML article body.
"""


# ── User prompt builder ──────────────────────────────────────────────────────
def build_user_prompt(article: dict[str, Any]) -> str:
    """Pack all source material — including live source-page fetch — into the
    user message. The model sees both the RSS scaffold and the actual
    article body so it can cross-verify every claim.
    """
    title      = article.get("title", "") or ""
    slug       = article.get("slug", "") or ""
    category   = article.get("category", "") or ""
    source     = article.get("source", "") or article.get("site", "") or ""
    source_url = article.get("url", "") or article.get("link", "") or ""
    published  = article.get("date", "") or article.get("published", "") or ""
    existing_body = article.get("body_html", "") or article.get("body", "") or ""

    # Strip HTML tags so RSS body arrives as clean plain text
    rss_plain = re.sub(r"<[^>]+>", " ", existing_body)
    rss_plain = re.sub(r"\s+", " ", rss_plain).strip()

    # Fetch live source page if enabled AND RSS body is thin
    live_source = ""
    used_source_fetch = False
    if FETCH_SOURCE and source_url and len(rss_plain) < MIN_SOURCE_CHARS:
        live_source = fetch_source_body(source_url)
        if len(live_source) > len(rss_plain):
            used_source_fetch = True

    source_block = f"""RSS scaffold body:
---
{rss_plain if rss_plain else '(empty — source page fetch is the only ground truth)'}
---
"""
    if used_source_fetch:
        source_block += f"""
LIVE SOURCE PAGE (fetched from {source_url}):
---
{live_source}
---
"""

    return f"""SOURCE MATERIAL — use ONLY this text. Every [Source N] citation must
map to one of the two blocks below.

Title: {title}
Vendor/Publisher: {source}
URL: {source_url}
Date: {published}
Category: {category}
Slug: {slug}

{source_block}

Generate the article following the NotebookLM protocol from the system
prompt. Required structure:

  <h2>The Quick Hit</h2>          — one-sentence coffee-shop summary
  <h2>What Happened</h2>          — 2-3 facts with [Source N] citations
  <h2>The Tech Spec</h2>          — technical breakdown, analogy rule
  <h2>So What?</h2>               — practical impact for broadcasters
  <h2>Blind Spots</h2>            — 3-5 unanswered questions
  <h3>Sources</h3>                — <ol> with <li>[Source 1] = {source_url}</li>

Every factual claim must carry an inline [Source N] citation traceable
to the source text above. Do not cite anything not in the source.

Output HTML body only — no <html>, <head>, <title>, or byline tags."""


# ── Mistral API call ─────────────────────────────────────────────────────────
def call_mistral(system: str, user: str, model: str) -> tuple[Optional[str], str]:
    """Call Mistral with a specific model.

    Returns (body_html_or_None, status_reason).
    status_reason: "ok" / "rate_limit" / "auth" / "server" / "timeout" / "other"
    """
    if not MISTRAL_API_KEY:
        return None, "auth"

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }
    payload = {
        "model":       model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": TEMPERATURE,        # LOCKED at 0.1
        "top_p":       TOP_P,
        "max_tokens":  MAX_TOKENS,
        "stream":      False,
    }

    try:
        resp = requests.post(
            MISTRAL_API_URL,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        print(f"    [TIMEOUT] {model} after {REQUEST_TIMEOUT}s")
        return None, "timeout"
    except Exception as e:
        print(f"    [ERROR] {model} request failed: {e}")
        return None, "other"

    if resp.status_code == 401:
        print(f"    [ERROR] Mistral 401 Unauthorized — check MISTRAL_API_KEY")
        return None, "auth"
    if resp.status_code == 429:
        print(f"    [RATE-LIMIT] {model} — trying next model in cascade")
        return None, "rate_limit"
    if resp.status_code == 402:
        print(f"    [ERROR] {model} requires paid tier — trying next model")
        return None, "auth"
    if resp.status_code in (500, 502, 503, 504):
        print(f"    [SERVER] {model} HTTP {resp.status_code} — trying next model")
        return None, "server"
    if resp.status_code != 200:
        print(f"    [ERROR] {model} HTTP {resp.status_code}: {resp.text[:200]}")
        return None, "other"

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"    [ERROR] Could not parse {model} response: {e}")
        return None, "other"

    # Clean common artifacts
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S | re.I)
    content = content.strip()
    # Strip code fences if present
    content = re.sub(r"^```(?:html)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    return (content.strip() or None), "ok"


def call_with_cascade(system: str, user: str) -> Optional[str]:
    """Try each model in the cascade until one succeeds."""
    for model in MISTRAL_MODELS:
        body, reason = call_mistral(system, user, model)
        if body:
            return body
        if reason == "auth":
            raise RuntimeError("MISTRAL_AUTH_FAILURE")
        time.sleep(2)
    return None


# ── Quality gates — identical to other tiers ─────────────────────────────────
def count_words(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html)
    return len(text.split())


def count_h2(html: str) -> int:
    return len(re.findall(r"<h2[\s>]", html, re.I))


def has_sources_section(html: str) -> bool:
    return bool(re.search(r"<h3>\s*Sources\s*</h3>", html, re.I))


def has_blind_spots_section(html: str) -> bool:
    return bool(re.search(r"<h2>\s*Blind Spots\s*</h2>", html, re.I))


def count_citations(html: str) -> int:
    return len(re.findall(r"\[Source\s*\d+\]", html))


def validate(body: str) -> Optional[str]:
    """Return None if body passes all gates; else a reason string."""
    wc = count_words(body)
    if wc < 400:
        return f"only {wc} words (need ≥400)"
    h2 = count_h2(body)
    if h2 < 4:
        return f"only {h2} <h2> sections (need ≥4)"
    if not has_sources_section(body):
        return "missing <h3>Sources</h3> section"
    if not has_blind_spots_section(body):
        return "missing <h2>Blind Spots</h2> section"
    cites = count_citations(body)
    if cites < 2:
        return f"only {cites} [Source N] citations (need ≥2)"
    return None


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    print("=== generate_mistral.py — Tier-1 generator (Mistral AI) ===")

    if not MISTRAL_API_KEY:
        print("  ⚠ MISTRAL_API_KEY not set — skipping tier-1")
        print("  Get a FREE key at https://console.mistral.ai/api-keys/")
        print("  Then add to GitHub repo: Settings → Secrets → Actions → MISTRAL_API_KEY")
        return 0

    if not ARTICLES_FILE.exists():
        print(f"  ⚠ {ARTICLES_FILE} not found — nothing to do")
        return 0

    articles = json.loads(ARTICLES_FILE.read_text(encoding="utf-8"))
    print(f"  Loaded {len(articles)} articles")

    eligible = [a for a in articles if needs_mistral(a)]
    print(f"  Tier-1 eligible (fresh scaffolds): {len(eligible)}")
    print(f"  Will process up to {MAX_PER_RUN} this run")
    print(f"  Tuning: T={TEMPERATURE} (LOCKED LOW), top_p={TOP_P}")
    print(f"  Model cascade: {' → '.join(MISTRAL_MODELS)}")
    print(f"  Live source-page fetch: {'ON' if FETCH_SOURCE else 'OFF'}")

    if not eligible:
        print("  ✓ No scaffolds need tier-1 processing")
        return 0

    processed = 0
    upgraded  = 0
    rejected  = 0

    for art in eligible:
        if processed >= MAX_PER_RUN:
            print(f"  [INFO] Hit MAX_PER_RUN={MAX_PER_RUN} — remaining process next run")
            break
        processed += 1
        slug = art.get("slug", "(no-slug)")
        print(f"  → [{processed}/{min(len(eligible), MAX_PER_RUN)}] Processing: {slug[:60]}")

        try:
            body = call_with_cascade(SYSTEM_PROMPT, build_user_prompt(art))
        except RuntimeError as e:
            # Account-level error — abort whole run
            print(f"\n[ABORT] {e} — tier-1 disabled for this run")
            print("[INFO] Gemini/Groq/OpenRouter will handle later tiers")
            ARTICLES_FILE.write_text(
                json.dumps(articles, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return 0

        if not body:
            print("    [SKIP] All Mistral models failed or rate-limited")
            time.sleep(INTER_CALL_SLEEP)
            continue

        # STRICT validation
        reason = validate(body)
        if reason:
            print(f"    [REJECT] {reason} — article stays scaffold, will retry next run")
            rejected += 1
            time.sleep(INTER_CALL_SLEEP)
            continue

        # Commit upgrade
        wc = count_words(body)
        h2 = count_h2(body)
        cites = count_citations(body)
        art["body_html"]     = body
        art["body"]          = body
        art["word_count"]    = wc
        art["generated_by"]  = "mistral-large"
        art["is_editorial"]  = True
        art["needs_gemini"]  = False
        upgraded += 1
        print(f"    ✓ {wc} words, {h2} H2, {cites} citations → {slug[:60]}")
        time.sleep(INTER_CALL_SLEEP)

    # Save
    ARTICLES_FILE.write_text(
        json.dumps(articles, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n[DONE] Tier-1: {upgraded} upgraded, {rejected} rejected (failed quality gates), "
          f"{processed - upgraded - rejected} skipped (API issues)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
