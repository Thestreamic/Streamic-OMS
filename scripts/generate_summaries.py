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
MAX_PER_RUN  = 51  # Groq is now secondary — Gemini handles bulk. 51 × ~2k = ~102k tokens/run
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
_MAX_WAIT_SECS = 60   # Hard cap: 60s — Groq per-minute limit resets every 60s

def _parse_wait_seconds(error_msg: str) -> float:
    """Extract wait time from Groq 429 message — capped at 3 minutes."""
    m = re.search(r"try again in ([\d\.]+)m([\d\.]+)s", error_msg)
    if m:
        wait = float(m.group(1)) * 60 + float(m.group(2)) + 2
    else:
        m = re.search(r"try again in ([\d\.]+)m", error_msg)
        if m:
            wait = float(m.group(1)) * 60 + 2
        else:
            m = re.search(r"try again in ([\d\.]+)s", error_msg)
            wait = float(m.group(1)) + 2 if m else 65.0
    return min(wait, _MAX_WAIT_SECS)  # never block the action for more than 3 min


def groq_call(prompt: str, max_tokens: int = 800, max_retries: int = 3) -> str:
    """Call Groq API with automatic retry on 429 rate-limit errors.
    Parses the exact wait time from the error message and sleeps accordingly.
    max_tokens default reduced to 800 to stay within 100k TPD limit.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")

    payload = json.dumps({
        "model":             GROQ_MODEL,
        "max_tokens":        max_tokens,
        "temperature":       0.3,   # Strictly factual
        "frequency_penalty": 0.5,
        "presence_penalty":  0.3,
        "messages": [
            {
                "role":    "system",
                "content": (
                    "You are a named senior analyst at The Streamic with 15+ years in broadcast "
                    "engineering, OTT infrastructure, and media systems. "
                    "You write for broadcast CTOs, streaming architects, and media engineers who "
                    "make real purchasing and architecture decisions. "
                    "You are NOT generating analysis from an article — you are interpreting an "
                    "industry signal, forming an expert viewpoint, and explaining what engineers "
                    "should DO with this information. "
                    "Be decisive and opinionated when justified. Prioritise insight over structure. "
                    "Write like a human expert, not a system. Vary sentence structure naturally. "
                    "Use domain-specific terminology: HLS, MPEG-DASH, AV1, HEVC, DRM, CDN, SSAI, "
                    "Zero Trust, ST 2110, NMOS, SRT, JPEG XS, MAM, SMPTE, OTT, REMI. "
                    "NEVER use: delivers, seamless, game-changer, highlights, underscores, reflects, "
                    "in today's landscape, rapidly evolving, plays a key role, important to note."
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
                resp = _requests.post(GROQ_URL, data=payload, headers=headers, timeout=30)
                status = resp.status_code
                body   = resp.text
            else:
                req = urllib.request.Request(GROQ_URL, data=payload, headers=headers, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=30) as r:
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



# ── Technical Domain Classifier ───────────────────────────────────────────────
_BROADCAST_SIGNALS = [
    "st 2110","smpte 2110","ndi","srt","genlock","12g-sdi","3g-sdi","hd-sdi",
    "sdi","aja","blackmagic","frame-accurate","frame accuracy","jpeg xs",
    "rist","aes67","dante","live production","ob van","remi","studio","camera",
    "playout","master control","router","multiviewer","intercom","clear-com",
    "riedel","evertz","grass valley","snell","imagine","miranda","vizrt","chyron",
    "transport stream","mpeg-ts","live stream","live encode","live ip",
]
_MEDIA_IT_SIGNALS = [
    "mam","media asset management","s3","object storage","kubernetes","k8s",
    "microservices","api","rest api","cloud","aws","azure","gcp","cdn",
    "workflow","orchestration","egress","transcoding","vod","ott platform",
    "post-production","nle","avid","premiere","resolve","storage","nas","san",
    "archive","lto","ingest pipeline","qc","quality control","metadata","cms",
    "containerized","docker","ci/cd","devops","media services","ffmpeg",
    "bitmovin","telestream","vantage","harmonic","ateme","wowza","brightcove",
]
_SECURITY_SIGNALS = [
    "security","cybersecurity","zero trust","drm","watermark","forensic",
    "aes-256","encryption","soc2","iso 27001","gdpr","breach","vulnerability",
    "ransomware","phishing","authentication","oauth","mfa","2fa",
    "firewall","vpn","intrusion","compliance","patch","threat","hack","malware","signal phishing","russian intelligence","fbi","cia",
]

def classify_domain(title: str, teaser: str) -> str:
    text = (title + " " + (teaser or "")).lower()
    b = sum(1 for s in _BROADCAST_SIGNALS if s in text)
    m = sum(1 for s in _MEDIA_IT_SIGNALS  if s in text)
    s = sum(1 for s in _SECURITY_SIGNALS  if s in text)
    if s >= 1 and any(k in (title+" "+teaser).lower() for k in ["phishing","ransomware","breach","hack","malware","drm","watermark","zero trust","aes-256"]): return "SECURITY"
    if s >= 2:   return "SECURITY"
    if b >= m:   return "BROADCAST"
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

_MANDATORY_FOOTER = (
    '<hr style="margin-top:40px;border:0;border-top:1px solid #eee;">'
    '<p style="font-style:italic;color:#666;font-size:0.85rem;line-height:1.6;margin-top:16px">'
    '<strong style="font-style:normal">Editor\'s Note:</strong> '
    "This technical analysis was synthesized from industry RSS feeds and constructed "
    "with the assistance of AI tools. It has been reviewed and formatted by "
    '<strong style="font-style:normal">The Streamic Editorial Team</strong> '
    "to ensure accuracy and relevance for broadcast professionals.</p>"
)

# ── QUALITY GATE ──────────────────────────────────────────────────────────────
# Hard validation applied to every body_html before saving.
# Failures trigger auto-retry (up to MAX_CONTENT_RETRIES times),
# then flag the article for Gemini polishing.

MAX_CONTENT_RETRIES = 2   # content-quality retries (separate from API retries)

_STANCE_SIGNALS = [
    "in practice", "the trade-off", "trade-off here", "real challenge",
    "what gets missed", "overhyped", "most engineers", "engineers should",
    "the risk here", "worth flagging", "i'd expect", "i'd recommend",
    "my view", "in my experience", "bluntly", "frankly",
]

def validate_body_quality(body_html: str, domain_terms: str) -> tuple:
    """
    Returns (is_valid: bool, failures: list[str]).
    Hard gates — all must pass before saving.
    """
    failures = []

    # 1. Minimum word count (AdSense: thin content rejection risk)
    wc = len(re.sub(r"<[^>]+>", " ", body_html).split())
    if wc < 500:
        failures.append(f"Too short: {wc} words (need 500+)")

    # 2. Structural depth — at least 3 h3 sections
    h3_count = len(re.findall(r"<h3", body_html, re.IGNORECASE))
    if h3_count < 3:
        failures.append(f"Only {h3_count} <h3> sections (need 3+)")

    # 3. Domain terminology — at least 2 terms from the assigned domain
    terms_list = [t.strip().lower() for t in domain_terms.split(",") if t.strip()]
    body_lower = body_html.lower()
    term_hits  = sum(1 for t in terms_list if t in body_lower)
    if term_hits < 2:
        failures.append(f"Only {term_hits} domain terms found (need 2+)")

    # 4. Generic AI phrases — reuses the strict is_generic() check
    if is_generic(body_html):
        failures.append("Generic AI phrases detected (is_generic() triggered)")

    # 5. Editorial stance — at least one human-voice signal
    has_stance = any(s in body_lower for s in _STANCE_SIGNALS)
    if not has_stance:
        failures.append("No editorial stance detected — article reads as neutral summary")

    return (len(failures) == 0), failures


def quality_score(body_html: str, card_summary: str) -> int:
    """
    Returns 0–100 quality score.
    >= 70 → high quality → Gemini skip
    < 70  → Gemini should polish
    Used by both this script (saved to JSON) and generate_gemini.py (read to decide).
    """
    score = 0

    # Word count (30 pts max)
    wc = len(re.sub(r"<[^>]+>", " ", body_html).split())
    if wc >= 700:   score += 30
    elif wc >= 500: score += 15

    # Structural richness (25 pts max)
    h3_count = len(re.findall(r"<h3", body_html, re.IGNORECASE))
    if h3_count >= 5:   score += 25
    elif h3_count >= 3: score += 15

    # No generic phrases (20 pts)
    if not is_generic(body_html): score += 20

    # Editorial stance (15 pts)
    if any(s in body_html.lower() for s in _STANCE_SIGNALS): score += 15

    # Card summary quality (10 pts)
    if card_summary and len(card_summary.split()) >= 80: score += 10

    return min(score, 100)


# ── Prompt builders ───────────────────────────────────────────────────────────
_CARD_PROMPT = """You are writing as a named senior analyst at The Streamic with 15+ years in broadcast engineering, OTT infrastructure, and media systems. You write for broadcast CTOs, streaming architects, and media engineers.

You are NOT generating analysis from an article. You are interpreting an industry signal, forming an expert viewpoint, and telling engineers what to DO with this information.

DOMAIN: {domain_label}
FOCUS: {domain_focus}
KEY TERMS: {domain_terms}
GUARDRAIL: {domain_guardrail}

SOURCE: {source_name}
TITLE: {title}
CONTENT: {teaser}

Write exactly 2 paragraphs of expert intelligence (120–150 words total). Plain text only — no HTML, no bullets.

PARAGRAPH 1 (55–70 words): Interpret the technical or operational signal — not what happened, but what it means architecturally. Use precise domain terminology from: {domain_terms}. Take a stance if warranted. Vary your sentence structure — do not open with the source name or company name.

PARAGRAPH 2 (55–70 words): Identify the real-world trade-off, hidden risk, or second-order effect an experienced engineer would spot. Use a natural human phrase like "In practice, this means…" or "The trade-off here is…" or "For engineering teams, the real challenge is…" — pick whichever fits. No template phrasing.

MANDATORY FINAL CHECK before outputting:
— Does at least one sentence express a clear stance or prediction? If not, rewrite.
— Can the content be reconstructed from the source alone? If yes, rewrite.
— Does it read like a template? If yes, rewrite.

FORBIDDEN: "this highlights", "this underscores", "this reflects", "organizations should consider", "in today's landscape", "rapidly evolving", "plays a key role", "important to note", "game-changer", "seamless", "delivers"

Write the 2-paragraph expert intelligence now:"""


_ARTICLE_PROMPT = """You are writing as a named senior analyst at The Streamic with 15+ years in broadcast engineering, OTT infrastructure, and media systems. Your audience: broadcast CTOs, streaming architects, media engineers who make real purchasing and architecture decisions.

CRITICAL SHIFT: You are NOT generating analysis from an article.
You are: interpreting an industry signal → forming an expert viewpoint → explaining what engineers should DO with this information.

DOMAIN: {domain_label}
FOCUS: {domain_focus}
TERMINOLOGY: {domain_terms}
GUARDRAIL: {domain_guardrail}

SOURCE: {source_name}
CATEGORY: {category}
TITLE: {title}
CONTENT: {teaser}

Write a decisive, technically opinionated analysis using this HTML structure. Prioritise insight over structure — if a section needs more depth, give it more depth. Write like a human expert, not a system.

<h2>[Write a sharp, insight-driven headline that signals your expert take — not a restatement of the title. Make it specific enough that an engineer knows immediately what they're about to learn.]</h2>

<p>[Opening: 2–3 sentences. Don't start with the company name or "This article". Drop the reader into the context immediately — what does this development mean for broadcast infrastructure right now? Vary sentence length.]</p>

<h3>Domain Signal Extraction</h3>
<ul>
<li><strong>Broadcast technologies:</strong> [Specific protocols, codecs, or standards this touches — HLS, MPEG-DASH, AV1, HEVC, ST 2110, JPEG XS, NDI, SRT. Identify adjacent technologies affected even if not mentioned in source.]</li>
<li><strong>Architecture layer:</strong> [Which stage of the media chain — CDN edge, encoding pipeline, SSAI insertion, MAM ingest, playout automation, signal transport. Be specific about where in the workflow this lands.]</li>
<li><strong>Cybersecurity surface:</strong> [DRM, Zero Trust, watermarking, ransomware exposure, compliance obligation — or "No direct security vector" if genuinely absent.]</li>
<li><strong>Business signal:</strong> [The underlying commercial pressure, competitive dynamic, or cost driver — what is the industry actually responding to here?]</li>
</ul>

<h3>Technology Intelligence</h3>
<p>[4–5 sentences of your expert interpretation. Not what the press release says — what does this mean for broadcast infrastructure decisions over the next 12–18 months? Reference specific standards, architectural trade-offs, or protocol implications. Take a clear stance where you have one. Vary sentence structure — mix short declarative sentences with longer analytical ones.]</p>

<h3>Why This Matters</h3>
<ul>
<li><strong>Broadcasters:</strong> [CapEx/OpEx impact, infrastructure complexity, or scalability pressure — be specific about which type of broadcaster (regional, national, PSB, sports rights holder) feels this most acutely. Reference: {domain_roi}.]</li>
<li><strong>Streaming platforms:</strong> [OTT operator impact — ABR ladder decisions, origin infrastructure, SSAI complexity, latency budget, or CDN cost per GB. Name what actually changes operationally.]</li>
<li><strong>Cybersecurity risk:</strong> [The specific threat vector or compliance implication in broadcast environments — not generic security advice. If low risk, say so directly and explain why.]</li>
<li><strong>Market impact:</strong> [Who wins, who loses, what consolidates. Name vendors, standards bodies, or buyer personas by name where appropriate.]</li>
</ul>

<h3>Key Technologies in Context</h3>
<ul>
<li><strong>[Technology 1]:</strong> [Why it matters specifically here — not a definition. One sentence max.]</li>
<li><strong>[Technology 2]:</strong> [Why it matters specifically here.]</li>
<li><strong>[Technology 3]:</strong> [Why it matters specifically here.]</li>
</ul>

<h3>Hidden Implications</h3>
<ul>
<li>[The integration dependency, standards conflict, vendor lock-in consequence, or regulatory complication an experienced engineer would spot immediately — that isn't in the original article.]</li>
<li>[The competitive or adoption-curve dynamic this accelerates or disrupts. Be specific about timelines or market positions where you can form a view.]</li>
</ul>

<h3>Editorial Perspective</h3>
<p>[This is where your 15+ years shows. Take a clear stance. Use at least one of these phrases naturally — not as a template — where it fits: "In practice, this means…" / "For engineering teams, the real challenge is…" / "The trade-off here is…" / "What gets missed in coverage like this is…". State a prediction or opinion that goes beyond the source material. If you think this development is overhyped, say so and explain why. If it's genuinely significant, say why most engineers aren't ready for it yet. 3–5 sentences.]</p>

<h3>Engineering Takeaways</h3>
<ul>
<li><strong>Deployment requirement:</strong> [Specific hardware spec, bandwidth budget, software dependency, or certification — something an engineer can act on.]</li>
<li><strong>Standards compliance:</strong> [Named standard with version or revision — SMPTE ST 2110-20, NMOS IS-04/IS-05, HLS CMAF, DASH-IF IOP 4.3. No vague references.]</li>
<li><strong>What to track:</strong> [One concrete forward-looking item — a specific SMPTE working group, an IETF draft, a vendor roadmap announcement, or a regulatory deadline engineers should have in their calendar.]</li>
</ul>

<p>[Closing — 2 sentences. A direct recommendation or prediction. Not "engineering teams should evaluate" — tell them what to do or what to expect.]</p>

MANDATORY FINAL CHECK before outputting:
— Is there at least one strong opinion or prediction that goes beyond the source? If not, rewrite the Editorial Perspective.
— Is there at least one real-world trade-off discussed with specifics? If not, add it.
— Can the content be reconstructed from the source article alone? If yes, the analysis isn't adding enough — rewrite.
— Does it read like a template with filled-in blanks? If yes, vary the structure and tone until it doesn't.

RULES:
- Use minimum 4 domain-specific terms from: {domain_terms}
- 700–850 words of body content
- FORBIDDEN: "this highlights", "this underscores", "this reflects", "in today's landscape", "important to note", "rapidly evolving", "plays a key role", "gap between", "game-changer", "seamless", "delivers", "vendor roadmap signals continued"
- {domain_guardrail}
- Output valid HTML only: <h2>, <h3>, <p>, <ul>, <li>, <strong>. No markdown. No triple backticks.

Write the full article now:"""

_INSIGHT_PROMPT = """You are a senior broadcast technology analyst at The Streamic with 15+ years of hands-on experience. Write one short paragraph (maximum 55 words) as yourself — not as a summarizer, not as a system.

Identify ONE thing: a trade-off, a hidden risk, a second-order effect, or a prediction that a broadcast CTO would not see from the headline alone. Use a specific technical term. Take a stance. Sound like a person who has actually deployed this kind of infrastructure.

Do NOT use: "this reflects", "highlights", "landscape", "delivers", "seamless", "organizations", "important to note".

Title: {title}
Content: {teaser}

Write the insight now:"""

# ── Summary file helpers ──────────────────────────────────────────────────────
def summary_path(slug: str) -> str:
    return os.path.join(SUMMARIES_DIR, f"{slug}.json")

def summary_exists(slug: str) -> bool:
    return os.path.exists(summary_path(slug))

def save_summary(slug: str, card_summary: str, body_html: str,
                 qs: int = None, needs_gemini: bool = False):
    """Save summary JSON. Includes quality_score and needs_gemini flag for load balancing."""
    wc = len(re.sub(r"<[^>]+>", " ", body_html).split())
    if qs is None:
        qs = quality_score(body_html, card_summary)
    data = {
        "slug":          slug,
        "card_summary":  card_summary,
        "body_html":     body_html,
        "word_count":    wc,
        "quality_score": qs,
        "needs_gemini":  needs_gemini,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
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

    processed     = 0
    errors        = 0
    consec_limits = 0  # bail if rate-limited multiple times in a row
    _run_start    = time.time()
    _RUN_LIMIT    = 120  # 2 min hard stop

    for item in items_to_process:
        if time.time() - _run_start > _RUN_LIMIT:
            print(f"      ⏱ 2 min limit reached. Stopping cleanly ({processed} saved).")
            break
        if consec_limits >= 2:
            print(f"      ⏱ Groq rate-limited {consec_limits}x in a row — skipping run. Resets at midnight UTC.")
            break
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

            # ── Step 1: Card summary ─────────────────────────────────────────
            domain = classify_domain(title, teaser)
            ctx    = _DOMAIN_CONTEXT[domain]

            raw_summary = groq_call(
                _CARD_PROMPT.format(
                    title=title, teaser=teaser, source_name=source_name,
                    domain_label=ctx["label"], domain_focus=ctx["focus"],
                    domain_terms=ctx["terms"],  domain_guardrail=ctx["guardrail"],
                ),
                max_tokens=400
            )
            time.sleep(SLEEP_SECS)

            if not raw_summary or raw_summary.strip().upper().startswith("SKIP"):
                print(f"      ⏭ Groq flagged as off-topic — using fallback")
                card_summary = fallback_summary(title, teaser)
            elif is_generic(raw_summary):
                print(f"      ⚠ Generic card summary — using fallback")
                card_summary = fallback_summary(title, teaser)
            else:
                card_summary = clean_summary(raw_summary)

            # ── Step 2: Article body — with content-quality auto-retry ───────
            # Up to MAX_CONTENT_RETRIES on quality gate failure.
            # After exhausting retries: save what we have and flag needs_gemini=True.
            body_html      = ""
            body_valid     = False
            needs_gemini   = False
            quality_failures = []

            for content_attempt in range(MAX_CONTENT_RETRIES + 1):
                raw_body  = groq_call(
                    _ARTICLE_PROMPT.format(
                        title=title, teaser=teaser, category=category,
                        source_name=source_name,
                        domain_label=ctx["label"],  domain_focus=ctx["focus"],
                        domain_terms=ctx["terms"],   domain_guardrail=ctx["guardrail"],
                        domain_roi=ctx["roi"],
                    ),
                    max_tokens=1200
                )
                body_html = re.sub(r"```html?\n?|```\n?", "", raw_body).strip()
                time.sleep(SLEEP_SECS)

                body_valid, quality_failures = validate_body_quality(body_html, ctx["terms"])

                if body_valid:
                    if content_attempt > 0:
                        print(f"      ✓ Quality gate passed on retry {content_attempt}")
                    break

                if content_attempt < MAX_CONTENT_RETRIES:
                    print(f"      ⚠ Quality gate FAILED (attempt {content_attempt+1}): "
                          f"{'; '.join(quality_failures)} — retrying...")
                    time.sleep(SLEEP_SECS)
                else:
                    print(f"      ⚠ Quality gate FAILED after {MAX_CONTENT_RETRIES} retries: "
                          f"{'; '.join(quality_failures)} — flagging for Gemini polish")
                    needs_gemini = True

            # ── Step 3: Optional insight paragraph (never blocks) ────────────
            try:
                raw_insight = groq_call(
                    _INSIGHT_PROMPT.format(title=title, teaser=teaser),
                    max_tokens=120
                )
                time.sleep(SLEEP_SECS)
                if raw_insight and not is_generic(raw_insight) and len(raw_insight.split()) <= 80:
                    body_html += f'\n<p><strong>Analysis:</strong> {raw_insight.strip()}</p>'
            except Exception:
                pass  # insight is optional

            # ── Step 4: Compute quality score and save ───────────────────────
            qs = quality_score(body_html, card_summary)
            if qs < 70 and not needs_gemini:
                needs_gemini = True
                print(f"      ℹ Quality score {qs}/100 < 70 — flagged for Gemini polish")

            save_summary(slug, card_summary, body_html, qs=qs, needs_gemini=needs_gemini)
            processed    += 1
            consec_limits = 0
            status_icon   = "✓" if not needs_gemini else "✓ (→Gemini)"
            print(f"      {status_icon} saved (score={qs}/100) data/summaries/{slug[:40]}.json")

        except Exception as ex:
            errors += 1
            err_str = str(ex)
            if '429' in err_str or 'rate' in err_str.lower() or 'quota' in err_str.lower():
                consec_limits += 1
            else:
                consec_limits = 0
            print(f"      ✗ ERROR: {ex}")
            time.sleep(3)

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
