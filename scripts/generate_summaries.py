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
try:
    import requests as _requests
    _USE_REQUESTS = True
except ImportError:
    _USE_REQUESTS = False
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NEWS_F       = os.path.join(ROOT, "data", "news.json")
GEN_ARTS_F   = os.path.join(ROOT, "data", "generated_articles.json")
SUMMARIES_DIR = os.path.join(ROOT, "data", "summaries")
os.makedirs(SUMMARIES_DIR, exist_ok=True)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"   # fast + free tier
MAX_PER_RUN  = 15  # 15 × ~2k tokens = 30k/run, safe within 100k TPD                  # stay within Groq free tier rate limits
SLEEP_SECS   = 3.0                 # pause between calls — 3s minimum between each request

# ── Slug builder (mirrors rewrite_feed.py) ────────────────────────────────────
def make_slug(title, pub_date, cat=""):
    date_part  = (pub_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    cat_part   = re.sub(r"[^\w]", "-", (cat or "").lower()).strip("-")[:12]
    title_part = re.sub(r"[^\w\s-]", "", title.lower())
    title_part = re.sub(r"[\s_]+", "-", title_part).strip("-")
    prefix     = f"{date_part}-{cat_part}-" if cat_part else f"{date_part}-"
    return f"{prefix}{title_part[:65 - len(prefix)]}"

# ── Groq API call with automatic 429 retry ───────────────────────────────────
def _parse_wait_seconds(error_msg: str) -> float:
    """Extract wait time from Groq 429 message: 'try again in 4m1.055s'"""
    m = re.search(r"try again in ([\d\.]+)m([\d\.]+)s", error_msg)
    if m:
        return float(m.group(1)) * 60 + float(m.group(2)) + 2
    m = re.search(r"try again in ([\d\.]+)m", error_msg)
    if m:
        return float(m.group(1)) * 60 + 2
    m = re.search(r"try again in ([\d\.]+)s", error_msg)
    if m:
        return float(m.group(1)) + 2
    return 65.0  # safe default: wait 65s


def groq_call(prompt: str, max_tokens: int = 800, max_retries: int = 6) -> str:
    """Call Groq API with automatic retry on 429 rate-limit errors.
    Parses the exact wait time from the error message and sleeps accordingly.
    max_tokens default reduced to 800 to stay within 100k TPD limit.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")

    payload = json.dumps({
        "model":             GROQ_MODEL,
        "max_tokens":        max_tokens,
        "temperature":       0.7,
        "frequency_penalty": 0.5,
        "presence_penalty":  0.3,
        "messages": [
            {
                "role":    "system",
                "content": (
                    "You are a senior broadcast technology editor. "
                    "Write factual, specific technical analysis. "
                    "Never use: delivers, seamless, game-changer, highlights, underscores, reflects. "
                    "Focus on specs (ST 2110, NMOS, latency, bitrate) and practical engineering impact."
                )
            },
            {"role": "user", "content": prompt}
        ]
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
        "User-Agent":    "Mozilla/5.0 (compatible; TheStreamic/1.0)",
        "Accept":        "application/json",
    }

    for attempt in range(max_retries):
        try:
            if _USE_REQUESTS:
                resp = _requests.post(GROQ_URL, data=payload, headers=headers, timeout=60)
                status = resp.status_code
                body   = resp.text
            else:
                req = urllib.request.Request(GROQ_URL, data=payload, headers=headers, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=60) as r:
                        body   = r.read().decode("utf-8")
                        status = 200
                except urllib.error.HTTPError as e:
                    body   = e.read().decode("utf-8", errors="replace")
                    status = e.code

            if status == 200:
                data = json.loads(body) if isinstance(body, str) else body
                return data["choices"][0]["message"]["content"].strip()

            if status == 429:
                wait = _parse_wait_seconds(body)
                print(f"      ⏱ Rate limit (429). Waiting {wait:.0f}s before retry {attempt+1}/{max_retries}...")
                time.sleep(wait)
                continue

            if status == 403:
                # Cloudflare block — short wait and retry
                wait = 10 * (attempt + 1)
                print(f"      ⚠ 403 (attempt {attempt+1}). Waiting {wait}s...")
                time.sleep(wait)
                continue

            raise RuntimeError(f"Groq HTTP {status}: {body[:200]}")

        except RuntimeError:
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            raise RuntimeError(f"Groq call failed: {e}")

    raise RuntimeError(f"Max retries ({max_retries}) exceeded")

# ── Broadcast relevance filter ───────────────────────────────────────────────
# Titles that contain these keywords are unlikely to be broadcast/streaming relevant
_OFF_TOPIC_SIGNALS = [
    "led wall sleep", "retail led", "samsung led wall", "indoor led", "led display sleep",
    "fashion", "restaurant", "hotel room", "real estate", "travel", "food",
    "cryptocurrency", "nft", "web3", "metaverse fashion",
    "fitness", "gym", "wellness",
]

def is_broadcast_relevant(title: str, teaser: str) -> bool:
    """Return False if the article is clearly off-topic for a broadcast tech publication."""
    text = (title + " " + teaser).lower()
    # Must contain at least one broadcast/streaming signal
    broadcast_signals = [
        "broadcast", "streaming", "codec", "encoder", "decoder", "nab", "ibc",
        "ott", "cdn", "latency", "video", "audio", "production", "playout",
        "camera", "studio", "graphics", "newsroom", "mam", "pam", "nmos",
        "st 2110", "sdi", "ip workflow", "cloud production", "media", "television",
        "tv", "satellite", "transmission", "post-production", "editing", "vfx",
        "signal", "ingest", "archive", "asset management", "live event",
        "jpeg xs", "ip media", "media server", "channel", "vendor", "workflow",
        "color grade", "colour grade", "ip broadcast", "media workflow",
        "newscast", "live ip", "software-defined", "media asset", "encoding", "encode",
        "cloud encode", "stream", "vod platform", "mpeg-dash", "dash ", "cmaf",
    ]
    has_signal = any(s in text for s in broadcast_signals)
    has_off_topic = any(s in text for s in _OFF_TOPIC_SIGNALS)
    return has_signal and not has_off_topic


# ── Generic output detector ───────────────────────────────────────────────────
_GENERIC_PHRASES = [
    "this reflects a growing", "this highlights the importance", "organizations should consider",
    "in today's landscape", "important to note", "rapidly evolving", "plays a key role",
    "it is worth noting", "this underscores", "in the current environment",
    "for broadcast engineers and technology decision", "staying current with vendor developments",
    "operational requirement, not just a professional interest",
    "organisations that have been piloting similar", "accelerate their evaluation timelines",
    "the announcement reflects sustained demand",
    "an independent editorial overview of the technology forces",
]

def is_generic(text: str) -> bool:
    tl = text.lower()
    hits = sum(1 for p in _GENERIC_PHRASES if p in tl)
    return hits >= 2  # reject if 2+ generic phrases detected


# ── Output cleaner ────────────────────────────────────────────────────────────
def clean_summary(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"```html?\n?|```\n?", "", text)
    parts = [p.strip() for p in re.split(r"\n{1,}", text) if p.strip()]
    parts = parts[:2]  # max 2 paragraphs for card summary
    return "\n".join(f"<p>{p}</p>" for p in parts)


# ── Fallback: use real source content instead of AI garbage ──────────────────
def fallback_summary(title: str, teaser: str) -> str:
    content = (teaser or title or "").strip()
    if not content:
        return f"<p>{title}</p>"
    sentences = re.split(r'(?<=[.!?]) +', content)
    first_three = " ".join(sentences[:3])
    return f"<p>{first_three}</p>"


# ── Prompt builders ───────────────────────────────────────────────────────────
_CARD_PROMPT = """You are a broadcast technology journalist writing for The Streamic.

Summarize this article using STRICT rules:

1. Use ONLY real facts stated in the article:
   - Company name(s) and location
   - Product name or technology
   - What specifically happened or was announced
   - Any numbers, specs, standards mentioned (e.g. ST 2110, AV1, latency ms, bitrate Mbps)

2. DO NOT write any of these generic filler statements:
   - "this reflects a growing trend"
   - "organizations should consider"
   - "in today's rapidly evolving landscape"
   - "this highlights the importance of"
   - "staying current with vendor developments"
   - "this underscores the need for"

3. Write in exactly 2 short paragraphs:
   - Paragraph 1 (60–80 words): factual summary of what happened
   - Paragraph 2 (60–80 words): specific technical relevance to broadcast operations

4. Total length: 120–160 words. No more.

5. No fluff. No repetition. No vague language. If the article is not about broadcast technology, write only: SKIP

Source: {source_name}
Title: {title}
Content: {teaser}

Write the 2-paragraph factual summary now:"""


_ARTICLE_PROMPT = """You are a senior broadcast technology analyst writing for a professional publication (TV Tech, IABM, or SVG Europe level). Transform the following news into a high-quality original technical analysis.

CRITICAL — DO NOT use any of these phrases:
"this highlights", "this underscores", "this reflects", "in today's landscape",
"it is worth noting", "rapidly evolving", "plays a key role", "organizations should consider",
"this development builds on", "sustained demand", "announcement reflects".

STRUCTURE (use these exact headings):

<p>[Introduction — max 120 words. State factually what happened. Company name, product, location, date if known. No fluff.]</p>

<h2>Technical Breakdown</h2>
[Explain the actual technology. How does it work? Reference relevant broadcast standards: ST 2110, NMOS, AES67, HLS, HEVC, AV1, JPEG XS, SRT, NDI, MXF, DNxHD. What protocols, codecs, or APIs are involved? Be specific.]

<h2>Operational Impact for Broadcast Engineers</h2>
[How does this affect playout, MAM, ingest, post-production, or live production workflows? What must engineers evaluate or change? Be practical and specific — name the workflow step affected.]

<h2>Real-World Scenario</h2>
[MANDATORY: Describe one concrete realistic example. Name a broadcaster type (regional TV station, OTT platform, post house, live sports operator). Show the actual decision or consequence they now face.]

<h2>Industry and Market Signals</h2>
[What does this mean for the vendor ecosystem? Standards bodies? Competition? Cost implications? What is shifting in the market?]

<h2>What to Watch Next</h2>
[Forward-looking: what should engineers and technology directors monitor? Name specific standards, product roadmaps, or market developments to track.]

STYLE RULES:
- 500–700 words total (concise and focused — do not pad)
- Confident, analytical tone — write as a domain expert
- Every paragraph adds new information (no repetition)
- Prefer concrete technical terms over abstract language
- Output valid HTML only: <p>, <h2>, <h3>, <ul>, <li> tags
- NO "Conclusion" heading. NO meta-commentary. NO markdown.

Title: {title}
Category: {category}
Content: {teaser}

Write the complete structured HTML analysis now:"""


_INSIGHT_PROMPT = """Write ONE short technical insight (maximum 55 words) about this broadcast technology news.

Focus ONLY on:
- Specific broadcast or streaming workflow implication
- Named standard, codec, or protocol relevance

Do NOT use: "this reflects", "organizations", "important", "highlights", "landscape".

Title: {title}
Content: {teaser}

One paragraph, 55 words max:"""

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

    # From news.json — handles both flat list and dict-of-categories format
    if isinstance(news, list):
        news_flat = news
    else:
        # dict-of-categories: flatten it
        news_flat = []
        for cat, items in news.items():
            for it in (items or []):
                it.setdefault("category", cat)
                news_flat.append(it)

    for item in news_flat:
        title  = (item.get("title") or "").strip()
        teaser = (item.get("teaser") or item.get("description") or "").strip()
        cat    = (item.get("category") or "featured").strip()
        pub    = (item.get("published") or item.get("pubDate") or "")[:10]
        source = (item.get("source") or item.get("source_domain") or "")
        if not title: continue
        slug = make_slug(title, pub, cat)
        if slug in seen_slugs or summary_exists(slug): continue
        seen_slugs.add(slug)
        items_to_process.append({
            "slug": slug, "title": title, "teaser": teaser,
            "category": cat, "source": source,
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
        if not slug or slug in seen_slugs: continue
        body = a.get("body_html", "") or ""
        cs   = a.get("card_summary", "") or ""
        # Re-generate if: no summary file, body has no h2 structure, OR generic markers
        has_structure  = "<h2>" in body
        has_generic    = any(m in (body + cs) for m in generic_markers)
        needs_regen    = not summary_exists(slug) or not has_structure or has_generic
        if not needs_regen: continue
        if any(m in (body + cs) for m in generic_markers):
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

        # ── Step 0: Skip off-topic articles ────────────────────────────
        if not is_broadcast_relevant(title, teaser):
            print(f"      ⏭ Skipped (off-topic for broadcast tech): {title[:50]}")
            processed += 1
            continue

        try:
            source_name = item.get('source_domain') or item.get('source') or 'the original source'

            # ── Step 1: Generate factual card summary ────────────────────
            raw_summary = groq_call(
                _CARD_PROMPT.format(title=title, teaser=teaser, source_name=source_name),
                max_tokens=400
            )
            time.sleep(SLEEP_SECS)

            # Reject if AI returned SKIP (off-topic) or generic filler
            if not raw_summary or raw_summary.strip().upper().startswith("SKIP"):
                print(f"      ⏭ Groq flagged as off-topic — using fallback")
                card_summary = fallback_summary(title, teaser)
            elif is_generic(raw_summary):
                print(f"      ⚠ Generic summary detected — using fallback")
                card_summary = fallback_summary(title, teaser)
            else:
                card_summary = clean_summary(raw_summary)

            # ── Step 2: Generate factual article body ────────────────────
            raw_body = groq_call(
                _ARTICLE_PROMPT.format(title=title, teaser=teaser, category=category),
                max_tokens=1200  # 700 words ≈ 1000 tokens + buffer
            )
            body_html = re.sub(r"```html?\n?|```\n?", "", raw_body).strip()
            time.sleep(SLEEP_SECS)

            # ── Step 3: Optional insight paragraph ───────────────────────
            try:
                raw_insight = groq_call(
                    _INSIGHT_PROMPT.format(title=title, teaser=teaser),
                    max_tokens=120
                )
                time.sleep(SLEEP_SECS)
                if raw_insight and not is_generic(raw_insight) and len(raw_insight.split()) <= 80:
                    body_html += f'\n<p><strong>Analysis:</strong> {raw_insight.strip()}</p>'
            except Exception:
                pass  # insight is optional — never block on it

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
