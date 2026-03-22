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

MAX_PER_RUN  = 220    # Process all 225 articles in one run: 220 × 2 calls × 5s = 37min
SLEEP_SECS   = 5.0    # 5s = 12 RPM — safely under 15 RPM free-tier limit

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


# ── Technical Domain Classifier ───────────────────────────────────────────────
# Determines whether an article is Broadcast (Live/Signals), Media IT, or Security
# so the AI writes with the right terminology — no cross-contamination.

_BROADCAST_SIGNALS = [
    "st 2110","smpte 2110","ndi","srt","genlock","12g-sdi","3g-sdi","hd-sdi",
    "sdi","aja","blackmagic","frame-accurate","frame accuracy","jpeg xs","jpeg2000",
    "rist","aes67","dante","live production","ob van","remi","studio","camera",
    "playout","master control","router","multiviewer","intercom","clear-com",
    "riedel","evertz","grass valley","snell","imagine","miranda","vizrt","chyron",
    "broadcast transmit","satellite uplink","encoder hardware","decoder hardware",
    "transport stream","mpeg-ts","hls ingest","live stream","live encode",
]
_MEDIA_IT_SIGNALS = [
    "mam","media asset management","s3","object storage","kubernetes","k8s",
    "microservices","api","rest api","cloud","aws","azure","gcp","cdn",
    "workflow","orchestration","egress","transcoding","vod","ott platform",
    "media supply chain","post-production","nle","avid","premiere","resolve",
    "storage","nas","san","archive","lto","ingest pipeline","qc","quality control",
    "metadata","cms","headless","containerized","docker","ci/cd","devops",
    "media io","media services","elemental","mediaconvert","ffmpeg","bitmovin",
    "telestream","vantage","harmonic","ateme","wowza","brightcove","kaltura",
]
_SECURITY_SIGNALS = [
    "security","cybersecurity","zero trust","drm","watermark","forensic",
    "aes-256","encryption","soc2","iso 27001","gdpr","breach","vulnerability",
    "ransomware","phishing","authentication","oauth","saml","mfa","2fa",
    "firewall","vpn","intrusion","pen test","audit","compliance","patch",
    "signal phishing","russian","fbi","hack","malware","threat",
]

def classify_domain(title: str, teaser: str) -> str:
    """Returns 'BROADCAST', 'MEDIA_IT', or 'SECURITY'."""
    text = (title + " " + teaser).lower()
    broadcast_score = sum(1 for s in _BROADCAST_SIGNALS if s in text)
    media_it_score  = sum(1 for s in _MEDIA_IT_SIGNALS  if s in text)
    security_score  = sum(1 for s in _SECURITY_SIGNALS  if s in text)
    if security_score >= 2:
        return "SECURITY"
    if broadcast_score >= media_it_score:
        return "BROADCAST"
    return "MEDIA_IT"

_DOMAIN_CONTEXT = {
    "BROADCAST": {
        "label": "Broadcast (Live/Signals)",
        "focus": "real-time transport, latency, signal integrity, and frame-accuracy",
        "terms": "ST 2110, NDI, SRT, Genlock, 12G-SDI, JPEG XS, AES67, RIST, NMOS",
        "guardrail": "Primary focus is live signal transport and latency. Reference cloud/MAM only if the article specifically covers hybrid or cloud-connected live production. Do not force cloud or Kubernetes references for pure hardware/signal topics.",
        "roi": "reduced transmission cost, lower latency than satellite/fibre, simplified signal routing, and reduced hardware rack footprint"
    },
    "MEDIA_IT": {
        "label": "Media IT (Storage/Workflow/Cloud)",
        "focus": "scalability, data integrity, workflow automation, and total cost of ownership",
        "terms": "Object Storage (S3), Microservices, Kubernetes, MAM, Egress Costs, API Orchestration, ST 2110 (for ingest), NMOS (for discovery)",
        "guardrail": "Primary focus is file-based workflow and cloud infrastructure. ST 2110 and NMOS may appear where relevant for ingest or playout integration \u2014 do not force them into pure software/storage contexts.",
        "roi": "reduced operational overhead, faster content delivery, lower infrastructure costs, and eliminated manual QC effort"
    },
    "SECURITY": {
        "label": "Security & Compliance",
        "focus": "risk mitigation, threat surface reduction, and regulatory compliance in broadcast environments",
        "terms": "Zero Trust, DRM, Forensic Watermarking, AES-256 Encryption, SOC2 Compliance, NIST, CDN security, broadcast signal integrity",
        "guardrail": "Frame security risks practically for broadcast operations. Reference specific broadcast-relevant threat vectors (signal interception, content piracy, newsroom systems) where relevant. Do not make unverified attribution claims.",
        "roi": "reduced breach risk, lower content piracy losses, compliance with broadcast licensing obligations, and lower cyber insurance premiums"
    }
}

_MANDATORY_FOOTER = '''<hr style="margin-top:40px;border:0;border-top:1px solid #eee;">
<p style="font-style:italic;color:#666;font-size:0.85rem;line-height:1.6;margin-top:16px">
<strong style="font-style:normal">Editor's Note:</strong> This technical analysis was synthesized from industry RSS feeds and constructed with the assistance of AI tools. It has been reviewed and formatted by <strong style="font-style:normal">The Streamic Editorial Team</strong> to ensure accuracy and relevance for broadcast professionals.
</p>'''

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
    return 32.0  # short default — resets within 60s


def gemini_call(prompt: str, max_retries: int = 2) -> str:
    """Call Gemini API. Bails immediately on daily quota exhaustion."""
    payload = json.dumps({
        "system_instruction": {
            "parts": [{"text": (
                "You are a Broadcast Systems Engineer writing for The Streamic. "
                "Write in a confident, technical, and analytical tone. "
                "Avoid: 'In the ever-evolving world', 'This article explores', 'delve into', "
                "'game-changer', 'seamless', 'innovative'. Start directly with the facts."
            )}]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":     0.3,
            "maxOutputTokens": 900,
        }
    }).encode()

    headers = {"Content-Type": "application/json"}

    for attempt in range(max_retries):
        try:
            try:
                import requests as _req
                resp = _req.post(GEMINI_URL, data=payload, headers=headers, timeout=30)
                status = resp.status_code
                body   = resp.text
            except Exception:
                import urllib.request
                req = urllib.request.Request(GEMINI_URL, data=payload, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=30) as r:
                    status = r.status
                    body   = r.read().decode()

            if status == 200:
                data = json.loads(body)
                return data["candidates"][0]["content"]["parts"][0]["text"]

            if status == 429:
                body_lower = body.lower()
                # Daily quota exhausted — no point retrying at all
                if any(p in body_lower for p in [
                    "daily", "per day", "resource_exhausted",
                    "quota exceeded", "limit exceeded", "free tier"
                ]):
                    raise RuntimeError(f"DAILY_QUOTA_EXHAUSTED: {body[:120]}")
                # Per-minute limit — wait and retry once
                wait = _parse_wait_seconds(body)
                wait = min(wait, 35)  # never wait more than 35s
                print(f"      ⏱ Gemini rate limit. Waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(wait)
                continue

            raise RuntimeError(f"Gemini HTTP {status}: {body[:200]}")

        except RuntimeError as ex:
            if "DAILY_QUOTA_EXHAUSTED" in str(ex):
                raise  # propagate immediately — caller handles bail
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise RuntimeError(f"Gemini: max retries ({max_retries}) exceeded")
        except Exception as ex:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise RuntimeError(f"Gemini error: {ex}")

    raise RuntimeError(f"Gemini: max retries ({max_retries}) exceeded")



def build_article_prompt(title: str, teaser: str, source: str, category: str) -> str:
    """Domain-aware 600-word article prompt for Gemini."""
    domain  = classify_domain(title, teaser)
    ctx     = _DOMAIN_CONTEXT[domain]

    return f"""{_SYSTEM}

You are writing for The Streamic. Classify this article as domain: {ctx['label']}.
Focus on: {ctx['focus']}.
Use relevant technical terms from: {ctx['terms']}.
GUARDRAIL: {ctx['guardrail']}

Transform this news into a 600-word technical analysis using EXACTLY this HTML structure:

<h2>Technical Analysis: [Write a specific, fact-based headline]</h2>

<p>[Opening: 2-3 sentences. State what happened, who, where, what technology. No filler.]</p>

<h3>Operational ROI</h3>
<p>[How does this save money or time for a broadcast CTO? Be specific: {ctx['roi']}. Name actual workflow steps affected.]</p>

<h3>Security &amp; Integration</h3>
<p>[How does this fit into an existing broadcast IT stack? Address cybersecurity implications. Reference relevant standards or protocols from: {ctx['terms']}.]</p>

<h3>Engineering Takeaways</h3>
<ul>
<li><strong>Deployment:</strong> [Specific deployment consideration — hardware, software, or network requirement]</li>
<li><strong>Compatibility:</strong> [Standards compliance and interoperability — name the specific standard]</li>
<li><strong>What to Watch:</strong> [Forward-looking: what engineers should evaluate or monitor next]</li>
</ul>

<p>[Closing: 2 sentences. Market signal or next step for engineering teams. No generic phrases.]</p>

{_MANDATORY_FOOTER}

RULES:
- Temperature mindset: 0.3 — strictly factual, no invention
- 550–650 words of content (not counting the footer)
- Output HTML only: <h2>, <h3>, <p>, <ul>, <li>, <strong>. No markdown.
- NEVER start any sentence with the same word as the previous sentence.

Source: {source}
Title: {title}
Content: {teaser}

Write the structured technical analysis now:"""



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

    processed       = 0
    errors          = 0
    consec_limits   = 0   # consecutive rate-limit errors — bail if too many
    _run_start      = time.time()
    _RUN_LIMIT      = 2400 # 40 min — fits inside 45-min GitHub Actions timeout

    for item in batch:
        if time.time() - _run_start > _RUN_LIMIT:
            print(f"      ⏱ 3 min limit reached. Stopping cleanly ({processed} saved).")
            break
        if consec_limits >= 2:
            print(f"      ⏱ Gemini rate limit hit {consec_limits}x in a row — skipping run. Will retry next scheduled run.")
            break
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
            processed    += 1
            consec_limits = 0  # reset on success
            print(f"      ✓ saved → data/summaries/{slug[:45]}.json")

        except Exception as ex:
            errors += 1
            err_str = str(ex)
            if 'DAILY_QUOTA_EXHAUSTED' in err_str:
                print(f"      ✗ Daily quota exhausted — resets 08:00 UTC. Stopping now.")
                break  # exit immediately — no point processing more articles
            elif '429' in err_str or 'rate' in err_str.lower():
                consec_limits += 1
            else:
                consec_limits = 0
            print(f"      ✗ ERROR: {ex}")
            time.sleep(2)

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
