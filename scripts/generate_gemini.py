"""
scripts/generate_gemini.py
===========================
Uses Google Gemini 1.5 Flash API to transform short RSS teasers into
600-word technical broadcast briefings.

Acts as a REDUNDANT pipeline alongside generate_summaries.py (Groq).
If Groq hits rate limits, Gemini keeps the site fresh.

Usage:
  GEMINI_API_KEY=xxx python3 scripts/generate_gemini.py

GitHub Actions:
  env:
    GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  run: python3 scripts/generate_gemini.py || echo "Gemini step skipped"

Output per article (data/summaries/<slug>.json):
  {
    "slug": "...",
    "card_summary": "...",
    "body_html": "<h2>...</h2><h3>...</h3><ul>...</ul>",
    "word_count": 620,
    "generated_by": "gemini-2.0-flash"
  }

Idempotent — skips slugs that already have a summary file.
Rate limit: time.sleep(4) between calls (Gemini free tier: 15 RPM).
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT          = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NEWS_F        = os.path.join(ROOT, "data", "news.json")
GEN_ARTS_F    = os.path.join(ROOT, "data", "generated_articles.json")
SUMMARIES_DIR = os.path.join(ROOT, "data", "summaries")
os.makedirs(SUMMARIES_DIR, exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL   = "gemini-2.0-flash"      # Current free-tier model (replaces deprecated 1.5)
GEMINI_URL     = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

MAX_PER_RUN  = 20     # Gemini free tier: 1500 requests/day → 20/run × 4 runs safe
SLEEP_SECS   = 4.0    # Stay within 15 RPM free-tier limit

try:
    import requests as _requests
    _USE_REQUESTS = True
except ImportError:
    _USE_REQUESTS = False

# ── Broadcast relevance filter ────────────────────────────────────────────────
_BROADCAST_SIGNALS = [
    "broadcast", "streaming", "codec", "encoder", "decoder", "nab", "ibc",
    "ott", "cdn", "video", "audio", "production", "playout", "camera",
    "studio", "graphics", "newsroom", "mam", "pam", "nmos", "st 2110",
    "sdi", "ip workflow", "cloud production", "media", "television", "tv",
    "satellite", "transmission", "post-production", "editing", "vfx",
    "signal", "ingest", "workflow", "encoding", "encode", "stream",
    "jpeg xs", "ip media", "live ip", "hevc", "h.264", "av1", "hls", "srt",
    "rist", "ndi", "mxf", "dnxhd", "channel", "intercom", "remi",
]
_OFF_TOPIC = [
    "led wall sleep", "retail led", "sleep study", "fashion week",
    "luxury hotel", "real estate", "restaurant", "fitness app",
    "cryptocurrency", "nft ", "web3 ", "samsung led sleep",
]

def is_broadcast_relevant(title: str, teaser: str = "") -> bool:
    text = (title + " " + teaser).lower()
    if any(k in text for k in _OFF_TOPIC):
        return False
    return any(k in text for k in _BROADCAST_SIGNALS)


# ── Slug helper ───────────────────────────────────────────────────────────────
def make_slug(title: str, pub_date: str, cat: str = "") -> str:
    date_part  = (pub_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    cat_part   = re.sub(r"[^\w]", "-", (cat or "").lower()).strip("-")[:12]
    title_part = re.sub(r"[^\w\s-]", "", title.lower())
    title_part = re.sub(r"[\s_]+", "-", title_part).strip("-")
    prefix     = f"{date_part}-{cat_part}-" if cat_part else f"{date_part}-"
    return f"{prefix}{title_part[:65 - len(prefix)]}"


# ── Summary file helpers ──────────────────────────────────────────────────────
def summary_path(slug: str) -> str:
    return os.path.join(SUMMARIES_DIR, f"{slug}.json")

def summary_exists(slug: str) -> bool:
    return os.path.exists(summary_path(slug))

def save_summary(slug: str, card_summary: str, body_html: str):
    wc   = len(re.sub(r"<[^>]+>", " ", body_html).split())
    data = {
        "slug":         slug,
        "card_summary": card_summary,
        "body_html":    body_html,
        "word_count":   wc,
        "generated_by": "gemini-2.0-flash",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(summary_path(slug), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Gemini API call with retry ────────────────────────────────────────────────
def _parse_wait(msg: str) -> float:
    """Extract retry-after seconds from Gemini/Google 429 response."""
    m = re.search(r"retry.after[:\s]+(\d+)", msg.lower())
    if m:
        return float(m.group(1)) + 2
    m = re.search(r"(\d+)\s*second", msg.lower())
    if m:
        return float(m.group(1)) + 2
    return 65.0


def gemini_call(prompt: str, max_retries: int = 5) -> str:
    """
    Call Gemini 1.5 Flash generateContent endpoint.
    Auto-retries on 429 with parsed wait time.
    Returns generated text string.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")

    payload = json.dumps({
        "system_instruction": {
            "parts": [{
                "text": (
                    "You are a Broadcast Systems Engineer writing for The Streamic. "
                    "Write in a confident, technical, and analytical tone. "
                    "Avoid: 'In the ever-evolving world', 'This article explores', 'delve into', "
                    "'game-changer', 'seamless', 'innovative'. Start directly with the facts."
                )
            }]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature":     0.65,
            "maxOutputTokens": 1200,
            "topP":            0.9,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "User-Agent":   "Mozilla/5.0 (compatible; TheStreamic/1.0)",
    }

    for attempt in range(max_retries):
        try:
            if _USE_REQUESTS:
                resp   = _requests.post(GEMINI_URL, data=payload, headers=headers, timeout=60)
                status = resp.status_code
                body   = resp.text
            else:
                req  = urllib.request.Request(GEMINI_URL, data=payload, headers=headers, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=60) as r:
                        body   = r.read().decode("utf-8")
                        status = 200
                except urllib.error.HTTPError as he:
                    body   = he.read().decode("utf-8", errors="replace")
                    status = he.code

            if status == 200:
                data = json.loads(body)
                # Extract text from Gemini response structure
                return (
                    data["candidates"][0]["content"]["parts"][0]["text"].strip()
                )

            if status == 429:
                wait = _parse_wait(body)
                print(f"      ⏱ Gemini rate limit. Waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(wait)
                continue

            raise RuntimeError(f"Gemini HTTP {status}: {body[:300]}")

        except RuntimeError:
            raise
        except Exception as ex:
            if attempt < max_retries - 1:
                time.sleep(10)
                continue
            raise RuntimeError(f"Gemini call failed: {ex}")

    raise RuntimeError(f"Gemini: max retries ({max_retries}) exceeded")


# ── Prompts ───────────────────────────────────────────────────────────────────

# System context injected at the start of every prompt (Gemini uses single-turn)
_SYSTEM = (
    "You are a Broadcast Systems Engineer writing for The Streamic — "
    "a professional publication for broadcast engineers, media architects, and CTOs. "
    "Write in a confident, technical, and analytical tone. "
    "Avoid these phrases entirely: 'In the ever-evolving world', 'This article explores', "
    "'delve into', 'game-changer', 'seamless', 'innovative', 'it is worth noting'. "
    "Start directly with the facts. Every paragraph must add new technical information."
)

def build_article_prompt(title: str, teaser: str, source: str, category: str) -> str:
    """
    Prompt for a 600-word technical briefing from an RSS teaser.
    Forces: <h2> Analysis, <h3> Technical Impact, <ul> Engineering Takeaways.
    """
    cat_context = {
        "streaming":          "video streaming, OTT delivery, adaptive bitrate encoding, CDN",
        "cloud":              "cloud-native broadcast production, REMI workflows, remote playout",
        "infrastructure":     "broadcast IP infrastructure, SMPTE ST 2110, NMOS, SDI migration",
        "ai-post-production": "AI-assisted post-production, MAM automation, intelligent QC",
        "playout":            "broadcast playout automation, channel-in-a-box, master control",
        "graphics":           "real-time broadcast graphics, virtual sets, AR/XR in live production",
        "newsroom":           "newsroom control systems, NRCS, remote journalism workflows",
        "featured":           "broadcast and streaming technology",
    }.get(category, "broadcast and streaming technology")

    return f"""{_SYSTEM}

Transform the following RSS news item into a 600-word technical briefing for broadcast engineers.

STRUCTURE (use exactly these HTML tags — no markdown):

<h2>[Write a specific, fact-based headline about what happened]</h2>

<p>[Opening paragraph — 2-3 sentences. State what happened, who is involved, and what the technical context is. No fluff.]</p>

<h3>Technical Impact</h3>

<p>[2-3 paragraphs. Explain HOW this technology works and WHY it matters for {cat_context}. Reference specific standards or protocols where appropriate: SMPTE ST 2110, NMOS, AES67, HLS, HEVC, AV1, SRT, RIST, NDI, MXF, DNxHD, JPEG XS, etc. Be specific — name bitrates, latency figures, or interoperability details if the source mentions them.]</p>

<h3>Engineering Takeaways</h3>

<ul>
<li>[Specific, actionable implication for broadcast engineers — not generic]</li>
<li>[Technical or operational consideration that affects infrastructure decisions]</li>
<li>[Forward-looking point: what engineers should monitor or evaluate next]</li>
</ul>

<p>[Closing paragraph — 2-3 sentences. What does this signal for the market? What should engineering teams do next?]</p>

RULES:
- Total: 550–650 words
- Output HTML only: <h2>, <h3>, <p>, <ul>, <li>. No markdown. No <html>, <head>, <body>.
- DO NOT use: "this highlights", "this underscores", "this reflects", "organizations should"
- DO NOT start any sentence with the same word as the previous sentence

Source: {source}
Category: {cat_context}
Title: {title}
Content: {teaser}

Write the technical briefing now:"""


def build_card_prompt(title: str, teaser: str, source: str) -> str:
    """
    Prompt for a 100–140 word card summary (shown on homepage cards).
    Factual, no fluff.
    """
    return f"""{_SYSTEM}

Write a 2-sentence factual summary of this broadcast technology news item.

Rules:
- Sentence 1: State exactly what happened (company, product, action)
- Sentence 2: State one specific technical or operational implication for broadcast engineers
- Total: 100–140 words maximum
- No generic phrases. No fluff. Facts only.
- Output plain text only (no HTML tags)

Source: {source}
Title: {title}
Content: {teaser}

Write the 2-sentence summary now:"""


# ── Generic output detector ───────────────────────────────────────────────────
_GENERIC_MARKERS = [
    "this reflects a growing", "in today's landscape", "it is worth noting",
    "this highlights the importance", "this underscores", "organizations should consider",
    "the ever-evolving", "rapidly evolving field",
]

def is_generic(text: str) -> bool:
    tl = text.lower()
    return sum(1 for m in _GENERIC_MARKERS if m in tl) >= 2


def fallback_card(title: str, teaser: str) -> str:
    """Use raw teaser as card summary if Gemini produces generic output."""
    text = (teaser or title or "").strip()
    sentences = re.split(r"(?<=[.!?]) +", text)
    return " ".join(sentences[:3])


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=== generate_gemini.py ===")

    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set. Export it before running.")
        sys.exit(1)

    # Load news.json — handles flat list and dict-of-categories formats
    with open(NEWS_F, "r", encoding="utf-8") as f:
        news_raw = json.load(f)

    if isinstance(news_raw, list):
        news_flat = news_raw
    else:
        news_flat = []
        for cat, items in news_raw.items():
            for it in (items or []):
                it.setdefault("category", cat)
                news_flat.append(it)

    # Also load generated_articles.json for articles needing summaries
    gen_arts = []
    if os.path.exists(GEN_ARTS_F):
        with open(GEN_ARTS_F, "r", encoding="utf-8") as f:
            gen_arts = json.load(f)

    # Build processing queue
    items_to_process = []
    seen = set()

    # From news.json
    for item in news_flat:
        title  = (item.get("title") or "").strip()
        teaser = (item.get("teaser") or item.get("description") or "").strip()
        cat    = (item.get("category") or "featured").strip()
        pub    = (item.get("published") or item.get("pubDate") or "")[:10]
        source = (item.get("source") or item.get("source_domain") or "")

        if not title: continue
        if not is_broadcast_relevant(title, teaser):
            continue

        slug = make_slug(title, pub, cat)
        if slug in seen or summary_exists(slug):
            continue
        seen.add(slug)
        items_to_process.append({
            "slug": slug, "title": title, "teaser": teaser,
            "category": cat, "source": source,
        })

    # From generated_articles.json — articles missing structured body (no <h2>)
    generic_markers = [
        "An independent editorial overview",
        "Understanding what is changing helps teams",
        "<h2>" ,  # if body already has h2, skip (already processed)
    ]
    for a in gen_arts:
        if a.get("is_editorial") or a.get("editorial"):
            continue
        slug  = a.get("slug", "")
        body  = a.get("body_html", "") or ""
        if not slug or slug in seen or summary_exists(slug):
            continue
        if "<h2>" in body:
            continue  # already has structured content
        seen.add(slug)
        items_to_process.append({
            "slug":     slug,
            "title":    a.get("title", ""),
            "teaser":   a.get("dek") or a.get("meta_description") or a.get("teaser") or "",
            "category": a.get("category", "featured"),
            "source":   a.get("source_domain") or a.get("source") or "",
        })

    total = len(items_to_process)
    batch = items_to_process[:MAX_PER_RUN]
    print(f"Items to process: {total} (this run: {len(batch)})")

    processed = 0
    errors    = 0

    for item in batch:
        slug     = item["slug"]
        title    = item["title"]
        teaser   = item["teaser"]
        category = item["category"]
        source   = item["source"] or "industry source"

        print(f"  [{processed+1}/{len(batch)}] {title[:55]}...")

        try:
            # ── Step 1: Card summary (2 sentences) ──────────────────────────
            raw_card = gemini_call(build_card_prompt(title, teaser, source))
            time.sleep(SLEEP_SECS)

            if not raw_card or is_generic(raw_card):
                print(f"      ⚠ Generic card — using fallback")
                card_summary = fallback_card(title, teaser)
            else:
                card_summary = re.sub(r"\s+", " ", raw_card).strip()

            # ── Step 2: Full technical briefing (600 words) ──────────────────
            raw_body = gemini_call(build_article_prompt(title, teaser, source, category))
            time.sleep(SLEEP_SECS)

            # Strip any markdown fences Gemini might add
            body_html = re.sub(r"```html?\n?|```\n?", "", raw_body).strip()

            save_summary(slug, card_summary, body_html)
            processed += 1
            print(f"      ✓ saved → data/summaries/{slug[:45]}.json")

        except Exception as ex:
            errors += 1
            print(f"      ✗ ERROR: {ex}")
            time.sleep(5)

    print(f"\n✓ Done: {processed} summaries saved, {errors} errors.")
    print(f"  Files in data/summaries/: {len(os.listdir(SUMMARIES_DIR))}")

    # Patch generated_articles.json with new Gemini summaries
    patch_generated_articles()


def patch_generated_articles():
    """Apply Gemini summaries back into generated_articles.json."""
    if not os.path.exists(GEN_ARTS_F):
        return

    with open(GEN_ARTS_F, "r", encoding="utf-8") as f:
        arts = json.load(f)

    patched = 0
    for a in arts:
        slug = a.get("slug", "")
        if not slug: continue
        sp = summary_path(slug)
        if not os.path.exists(sp): continue
        try:
            with open(sp, encoding="utf-8") as sf:
                s = json.load(sf)
            if s.get("card_summary"):
                a["card_summary"] = s["card_summary"]
            if s.get("body_html"):
                a["body_html"]    = s["body_html"]
            if s.get("word_count"):
                a["word_count"]   = s["word_count"]
            patched += 1
        except Exception:
            continue

    with open(GEN_ARTS_F, "w", encoding="utf-8") as f:
        json.dump(arts, f, indent=2, ensure_ascii=False)
    print(f"  Patched {patched} articles in generated_articles.json")


if __name__ == "__main__":
    main()
