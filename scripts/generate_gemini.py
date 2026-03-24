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

# Load balancing threshold: articles with quality_score >= this are skipped by Gemini
# (Groq already produced high-quality output — no need to spend Gemini quota)
GEMINI_QUALITY_THRESHOLD = 70

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


# ── Quality gate (mirrors generate_summaries.py logic) ───────────────────────
_STANCE_SIGNALS = [
    "in practice", "the trade-off", "trade-off here", "real challenge",
    "what gets missed", "overhyped", "most engineers", "engineers should",
    "the risk here", "worth flagging", "i'd expect", "i'd recommend",
    "my view", "bluntly", "frankly",
]

_GENERIC_FULL = [
    "this reflects a growing", "this highlights the importance",
    "organizations should consider", "in today's landscape",
    "important to note", "rapidly evolving", "plays a key role",
    "it is worth noting", "this underscores", "in the current environment",
    "the ever-evolving", "rapidly evolving field",
]

def validate_body_quality(body_html: str, domain_terms: str) -> tuple:
    """Returns (is_valid, failures_list). Same gates as generate_summaries.py."""
    failures = []
    wc = len(re.sub(r"<[^>]+>", " ", body_html).split())
    if wc < 500:
        failures.append(f"Too short: {wc} words")
    if len(re.findall(r"<h3", body_html, re.IGNORECASE)) < 3:
        failures.append("Fewer than 3 <h3> sections")
    terms_list = [t.strip().lower() for t in domain_terms.split(",") if t.strip()]
    if sum(1 for t in terms_list if t in body_html.lower()) < 2:
        failures.append("Fewer than 2 domain terms")
    if sum(1 for p in _GENERIC_FULL if p in body_html.lower()) >= 2:
        failures.append("Generic phrases detected")
    if not any(s in body_html.lower() for s in _STANCE_SIGNALS):
        failures.append("No editorial stance detected")
    return len(failures) == 0, failures


def compute_quality_score(body_html: str, card_summary: str) -> int:
    """0–100 quality score — same formula as generate_summaries.py."""
    score = 0
    wc = len(re.sub(r"<[^>]+>", " ", body_html).split())
    if wc >= 700:   score += 30
    elif wc >= 500: score += 15
    h3s = len(re.findall(r"<h3", body_html, re.IGNORECASE))
    if h3s >= 5:   score += 25
    elif h3s >= 3: score += 15
    if not any(p in body_html.lower() for p in _GENERIC_FULL): score += 20
    if any(s in body_html.lower() for s in _STANCE_SIGNALS):   score += 15
    if card_summary and len(card_summary.split()) >= 80:        score += 10
    return min(score, 100)


def needs_gemini_processing(slug: str) -> tuple:
    """
    Load balancing decision: should Gemini process this article?
    Returns (should_process: bool, reason: str).
    
    Process if:
    1. No summary file exists (Groq hasn't run yet)
    2. needs_gemini=True flag set by Groq (quality gate failures)
    3. quality_score < GEMINI_QUALITY_THRESHOLD
    4. body_html has no <h2> (unstructured content)
    
    Skip if:
    - quality_score >= GEMINI_QUALITY_THRESHOLD AND needs_gemini=False
    """
    sp = summary_path(slug)
    if not os.path.exists(sp):
        return True, "no_summary"
    try:
        with open(sp, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        return True, "corrupt_summary"

    # Already processed by Gemini — don't re-process
    if s.get("generated_by") == "gemini-2.0-flash" and s.get("quality_score", 0) >= GEMINI_QUALITY_THRESHOLD:
        return False, "already_good_gemini"

    # Groq flagged it
    if s.get("needs_gemini"):
        return True, "groq_flagged"

    # Low quality score
    qs = s.get("quality_score", 0)
    if qs > 0 and qs < GEMINI_QUALITY_THRESHOLD:
        return True, f"low_score_{qs}"

    # No structured body
    if "<h2>" not in (s.get("body_html") or ""):
        return True, "no_h2_structure"

    # Groq produced high-quality output — skip Gemini
    return False, f"high_quality_groq_{qs}"


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

def save_summary(slug: str, card_summary: str, body_html: str, qs: int = None):
    """Save Gemini-generated summary. Always marks generated_by and quality_score."""
    wc   = len(re.sub(r"<[^>]+>", " ", body_html).split())
    if qs is None:
        qs = compute_quality_score(body_html, card_summary)
    data = {
        "slug":          slug,
        "card_summary":  card_summary,
        "body_html":     body_html,
        "word_count":    wc,
        "quality_score": qs,
        "needs_gemini":  False,   # Gemini has now processed it
        "generated_by":  "gemini-2.0-flash",
        "generated_at":  datetime.now(timezone.utc).isoformat(),
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
                "in today's landscape, rapidly evolving, plays a key role, delve into, "
                "this article explores, innovative, important to note."
            )}]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":     0.3,
            "maxOutputTokens": 1200,
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
                wait = _parse_wait(body)
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
    """Humanized expert analyst article prompt — opinionated, human voice, Editorial Perspective section."""
    domain = classify_domain(title, teaser)
    ctx    = _DOMAIN_CONTEXT[domain]

    return f"""You are writing as a named senior analyst at The Streamic with 15+ years in broadcast engineering, OTT infrastructure, and media systems. Your audience: broadcast CTOs, streaming architects, media engineers who make real purchasing and architecture decisions.

CRITICAL SHIFT: You are NOT generating analysis from an article.
You are: interpreting an industry signal → forming an expert viewpoint → explaining what engineers should DO with this information.

DOMAIN: {ctx['label']}
FOCUS: {ctx['focus']}
TERMINOLOGY: {ctx['terms']}
GUARDRAIL: {ctx['guardrail']}

SOURCE: {source}
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
<li><strong>Broadcasters:</strong> [CapEx/OpEx impact, infrastructure complexity, or scalability pressure — be specific about which type of broadcaster feels this most acutely. Reference: {ctx['roi']}.]</li>
<li><strong>Streaming platforms:</strong> [OTT operator impact — ABR ladder decisions, origin infrastructure, SSAI complexity, latency budget, or CDN cost per GB. Name what actually changes operationally.]</li>
<li><strong>Cybersecurity risk:</strong> [The specific threat vector or compliance implication in broadcast environments. If low risk, say so directly and explain why.]</li>
<li><strong>Market impact:</strong> [Who wins, who loses, what consolidates. Name vendors, standards bodies, or buyer personas where appropriate.]</li>
</ul>

<h3>Key Technologies in Context</h3>
<ul>
<li><strong>[Technology 1]:</strong> [Why it matters specifically here — not a definition. One sentence.]</li>
<li><strong>[Technology 2]:</strong> [Why it matters specifically here.]</li>
<li><strong>[Technology 3]:</strong> [Why it matters specifically here.]</li>
</ul>

<h3>Hidden Implications</h3>
<ul>
<li>[The integration dependency, standards conflict, vendor lock-in consequence, or regulatory complication an experienced engineer would spot immediately — not in the original article.]</li>
<li>[The competitive or adoption-curve dynamic this accelerates or disrupts. Be specific about timelines or market positions where you can form a view.]</li>
</ul>

<h3>Editorial Perspective</h3>
<p>[This is where your 15+ years shows. Take a clear stance. Use at least one of these phrases naturally — not as a template — where it fits: "In practice, this means…" / "For engineering teams, the real challenge is…" / "The trade-off here is…" / "What gets missed in coverage like this is…". State a prediction or opinion that goes beyond the source material. If this development is overhyped, say so. If most engineers aren't ready for it, say that. 3–5 sentences.]</p>

<h3>Engineering Takeaways</h3>
<ul>
<li><strong>Deployment requirement:</strong> [Specific hardware spec, bandwidth budget, software dependency, or certification — something an engineer can act on.]</li>
<li><strong>Standards compliance:</strong> [Named standard with version — SMPTE ST 2110-20, NMOS IS-04/IS-05, HLS CMAF, DASH-IF IOP 4.3. No vague references.]</li>
<li><strong>What to track:</strong> [One concrete forward-looking item — a specific working group, IETF draft, vendor roadmap announcement, or regulatory deadline.]</li>
</ul>

<p>[Closing — 2 sentences. A direct recommendation or prediction. Not "engineering teams should evaluate" — tell them what to do or what to expect.]</p>

{_MANDATORY_FOOTER}

MANDATORY FINAL CHECK before outputting:
— Is there at least one strong opinion or prediction that goes beyond the source? If not, rewrite the Editorial Perspective.
— Is there at least one real-world trade-off discussed with specifics? If not, add it.
— Can the content be reconstructed from the source article alone? If yes, rewrite.
— Does it read like a template? If yes, vary the structure and tone until it doesn't.

RULES:
- Use minimum 4 domain-specific terms from: {ctx['terms']}
- 700–850 words of body content (not counting footer)
- FORBIDDEN: "this highlights", "this underscores", "this reflects", "in today's landscape", "important to note", "rapidly evolving", "plays a key role", "gap between", "game-changer", "seamless", "delivers", "delve into", "innovative"
- {ctx['guardrail']}
- Output valid HTML only: <h2>, <h3>, <p>, <ul>, <li>, <strong>. No markdown. No triple backticks.

Write the full article now:"""



def build_card_prompt(title: str, teaser: str, source: str) -> str:
    """
    Humanized expert intelligence card prompt — opinionated analyst voice, not a summary.
    Shown on homepage cards (~120-150 words, plain text).
    """
    domain = classify_domain(title, teaser)
    ctx    = _DOMAIN_CONTEXT[domain]

    return f"""You are writing as a named senior analyst at The Streamic with 15+ years in broadcast engineering, OTT infrastructure, and media systems. You write for broadcast CTOs, streaming architects, and media engineers.

You are NOT summarizing an article. You are interpreting an industry signal and telling engineers what it means.

DOMAIN: {ctx['label']}
FOCUS: {ctx['focus']}
KEY TERMS: {ctx['terms']}
GUARDRAIL: {ctx['guardrail']}

SOURCE: {source}
TITLE: {title}
CONTENT: {teaser}

Write exactly 2 paragraphs of expert intelligence (120–150 words total). Plain text only — no HTML, no bullets.

PARAGRAPH 1 (55–70 words): Interpret the technical or operational signal — not what happened, but what it means architecturally. Use precise domain terminology from: {ctx['terms']}. Take a stance if warranted. Do not open with the company name.

PARAGRAPH 2 (55–70 words): Identify the real-world trade-off, hidden risk, or second-order effect an experienced engineer would spot. Use a natural human phrase like "In practice, this means…" or "The trade-off here is…" or "For engineering teams, the real challenge is…" — pick whichever fits. No template phrasing.

MANDATORY FINAL CHECK: Does it read like a template or a filled-in blank? If yes, rewrite. Does it express a stance? If no, add one.

FORBIDDEN: "this highlights", "this underscores", "this reflects", "organizations should consider", "in today's landscape", "rapidly evolving", "plays a key role", "game-changer", "seamless", "delivers"

Write the 2-paragraph expert intelligence now:"""


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

    # Build processing queue using load-balancing logic:
    # Only process articles that Groq flagged as weak, or never processed, or low score.
    # Skip articles where Groq already produced high-quality output (score >= threshold).
    items_to_process = []
    seen = set()
    skipped_high_quality = 0

    # From news.json — identify slugs that need Gemini
    for item in news_flat:
        title  = (item.get("title") or "").strip()
        teaser = (item.get("teaser") or item.get("description") or "").strip()
        cat    = (item.get("category") or "featured").strip()
        pub    = (item.get("published") or item.get("pubDate") or "")[:10]
        source = (item.get("source") or item.get("source_domain") or "")

        if not title: continue
        if not is_broadcast_relevant(title, teaser): continue

        slug = make_slug(title, pub, cat)
        if slug in seen: continue
        seen.add(slug)

        should_process, reason = needs_gemini_processing(slug)
        if not should_process:
            skipped_high_quality += 1
            continue

        items_to_process.append({
            "slug": slug, "title": title, "teaser": teaser,
            "category": cat, "source": source, "reason": reason,
        })

    # From generated_articles.json — catch articles Groq flagged or never touched
    for a in gen_arts:
        if a.get("is_editorial") or a.get("editorial"):
            continue
        slug  = a.get("slug", "")
        if not slug or slug in seen: continue
        seen.add(slug)

        should_process, reason = needs_gemini_processing(slug)
        if not should_process:
            skipped_high_quality += 1
            continue

        items_to_process.append({
            "slug":     slug,
            "title":    a.get("title", ""),
            "teaser":   a.get("dek") or a.get("meta_description") or a.get("teaser") or "",
            "category": a.get("category", "featured"),
            "source":   a.get("source_domain") or a.get("source") or "",
            "reason":   reason,
        })

    total = len(items_to_process)
    batch = items_to_process[:MAX_PER_RUN]
    print(f"Items to process: {total} (this run: {len(batch)}) | "
          f"Skipped (high-quality Groq): {skipped_high_quality}")

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
        reason   = item.get("reason", "unknown")

        print(f"  [{processed+1}/{len(batch)}] {title[:55]}... (reason: {reason})")

        try:
            domain = classify_domain(title, teaser)
            ctx    = _DOMAIN_CONTEXT[domain]

            # ── Step 1: Card summary ─────────────────────────────────────
            raw_card = gemini_call(build_card_prompt(title, teaser, source))
            time.sleep(SLEEP_SECS)

            if not raw_card or is_generic(raw_card):
                print(f"      ⚠ Generic card — using fallback")
                card_summary = fallback_card(title, teaser)
            else:
                card_summary = re.sub(r"\s+", " ", raw_card).strip()

            # ── Step 2: Full article body — with quality gate + 1 retry ──
            body_html  = ""
            body_valid = False
            MAX_BODY_RETRIES = 1   # Gemini: 1 retry (rate limit is tighter)

            for body_attempt in range(MAX_BODY_RETRIES + 1):
                raw_body  = gemini_call(build_article_prompt(title, teaser, source, category))
                body_html = re.sub(r"```html?\n?|```\n?", "", raw_body).strip()
                time.sleep(SLEEP_SECS)

                body_valid, failures = validate_body_quality(body_html, ctx["terms"])
                if body_valid:
                    if body_attempt > 0:
                        print(f"      ✓ Quality gate passed on retry {body_attempt}")
                    break
                if body_attempt < MAX_BODY_RETRIES:
                    print(f"      ⚠ Quality gate failed: {'; '.join(failures)} — retrying...")
                    time.sleep(SLEEP_SECS)
                else:
                    print(f"      ⚠ Quality gate still failed after retry: {'; '.join(failures)} — saving anyway")

            qs = compute_quality_score(body_html, card_summary)
            save_summary(slug, card_summary, body_html, qs=qs)
            processed    += 1
            consec_limits = 0
            print(f"      ✓ saved (score={qs}/100) → data/summaries/{slug[:40]}.json")

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
