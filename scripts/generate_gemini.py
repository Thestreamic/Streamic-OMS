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
    "generated_by": "gemini-2.5-flash-lite"
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

# ── DUAL MODEL STRATEGY ───────────────────────────────────────────────────────
# Flash-Lite: 15 RPM / 1,000 RPD — use for ALL regular summaries (220 articles)
# Pro:        10 RPM / 100 RPD   — reserve ONLY for top "featured" pillar posts
#
# Limits reset at Midnight Pacific Time (PT).
# If running from India (IST = PT + 13.5h), your PT midnight = 13:30 IST next day.
# Plan runs accordingly: morning IST run hits yesterday's quota; afternoon is fresh.
#
# NOTE: "gemini-3.1-flash-lite" doesn't exist as of 2026.
# Correct model strings used below. Update if Google releases newer versions.

GEMINI_FLASH_LITE_MODEL = "gemini-2.5-flash-lite"   # 15 RPM / 1,000 RPD — bulk summaries
GEMINI_PRO_MODEL        = "gemini-2.5-pro"           # 10 RPM / 100 RPD  — featured pillar posts

GEMINI_FLASH_LITE_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_FLASH_LITE_MODEL}:generateContent?key={GEMINI_API_KEY}"
)
GEMINI_PRO_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_PRO_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

# Keep GEMINI_MODEL/GEMINI_URL aliases so nothing else in the file breaks
GEMINI_MODEL = GEMINI_FLASH_LITE_MODEL
GEMINI_URL   = GEMINI_FLASH_LITE_URL

# Categories that get Pro model treatment (deep pillar analysis)
# All other categories use Flash-Lite
PRO_CATEGORIES = {"featured", "featured_priority", "infrastructure"}
PRO_BUDGET_PER_RUN = 10    # never spend more than this many Pro calls in one run

MAX_PER_RUN  = 220    # Total queue size ceiling
SLEEP_SECS   = 5.0    # 5s = 12 RPM — safely under Flash-Lite 15 RPM limit
SLEEP_PRO    = 8.0    # 8s between Pro calls — stays under 10 RPM

# ── Batch + fallback config (easy to tune) ────────────────────────────────────
MAX_ITEMS_PER_RUN  = 40     # Hard cap per run — raise to process more per cycle
USE_GROQ_FALLBACK  = False  # Set True to fall back to Groq when Gemini quota exhausted

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

    # Already processed by Gemini at good quality — don't re-process
    if (s.get("generated_by") in ("gemini-2.5-flash-lite", "gemini-2.5-pro")
            and s.get("quality_score", 0) >= GEMINI_QUALITY_THRESHOLD):
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

def save_summary(slug: str, card_summary: str, body_html: str, qs: int = None,
                 model: str = "gemini-2.5-flash-lite"):
    """Save Gemini-generated summary. Records which model produced it."""
    wc   = len(re.sub(r"<[^>]+>", " ", body_html).split())
    if qs is None:
        qs = compute_quality_score(body_html, card_summary)
    data = {
        "slug":          slug,
        "card_summary":  card_summary,
        "body_html":     body_html,
        "word_count":    wc,
        "quality_score": qs,
        "needs_gemini":  False,
        "generated_by":  model,
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


def gemini_call(prompt: str, max_retries: int = 2, use_pro: bool = False) -> str:
    """Call Gemini API. Routes to Pro model for featured pillar posts, Flash-Lite for everything else.
    Bails immediately on daily quota exhaustion.
    """
    url          = GEMINI_PRO_URL if use_pro else GEMINI_FLASH_LITE_URL
    model_label  = "Pro" if use_pro else "Flash-Lite"
    max_tokens   = 1800 if use_pro else 1200   # Pro can go deeper
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
            "maxOutputTokens": max_tokens,
        }
    }).encode()

    headers = {"Content-Type": "application/json"}

    for attempt in range(max_retries):
        try:
            try:
                import requests as _req
                resp = _req.post(url, data=payload, headers=headers, timeout=30)
                status = resp.status_code
                body   = resp.text
            except Exception:
                import urllib.request
                req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
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
                    raise RuntimeError(f"DAILY_QUOTA_EXHAUSTED_{model_label}: {body[:120]}")
                # Per-minute limit — wait and retry once
                wait = _parse_wait(body)
                wait = min(wait, 35)  # never wait more than 35s
                print(f"      ⏱ Gemini {model_label} rate limit. Waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(wait)
                continue

            raise RuntimeError(f"Gemini {model_label} HTTP {status}: {body[:200]}")

        except RuntimeError as ex:
            if "DAILY_QUOTA_EXHAUSTED" in str(ex):
                raise  # propagate immediately — caller handles bail
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise RuntimeError(f"Gemini {model_label}: max retries ({max_retries}) exceeded")
        except Exception as ex:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise RuntimeError(f"Gemini {model_label} error: {ex}")

    raise RuntimeError(f"Gemini: max retries ({max_retries}) exceeded")



def build_article_prompt(title: str, teaser: str, source: str, category: str) -> str:
    """Pillar-post E-E-A-T prompt — vendor specifics, table, diagram placeholder, author bio."""
    domain = classify_domain(title, teaser)
    ctx    = _DOMAIN_CONTEXT[domain]

    return f"""You are a Senior Technical Editor and Broadcast Systems Engineer at The Streamic with 15+ years of hands-on experience deploying enterprise media infrastructure — broadcast playout, IP signal transport, OTT origin stacks, MAM systems, and post-production pipelines. You write for broadcast CTOs, infrastructure engineers, and media operations leads who make real purchasing decisions.

YOUR ROLE: Do NOT summarize the source. Rewrite it as a Pillar Post — a definitive, authoritative reference article that demonstrates Experience, Expertise, Authoritativeness, and Trustworthiness (E-E-A-T) for Google Search.

DOMAIN: {ctx['label']}
FOCUS: {ctx['focus']}
TERMINOLOGY: {ctx['terms']}
GUARDRAIL: {ctx['guardrail']}

SOURCE: {source}
CATEGORY: {category}
TITLE: {title}
CONTENT: {teaser}

OUTPUT FORMAT — PILLAR POST STRUCTURE. Use this exact HTML. Do not deviate from section order.

<h2>[Write a decisive, expert headline that signals your take — not the source title. Example format: "Why [Technology] Is Forcing Broadcasters to Rethink [Architecture]"]</h2>

<p>[Opening paragraph: 2–3 sentences. Drop straight into the operational context. What pressure, shift, or inflection point does this development represent? Do not open with the company name. Vary sentence length.]</p>

<h2>What This Development Actually Means</h2>
<p>[2–3 sentences: State what happened. Company, product, announcement, or capability. Be specific — name the product, standard, or architecture involved. Rewrite completely from the source. No sentence similarity with the original.]</p>
<p>[1–2 sentences: Explain the industry context this sits within. Why now? What pressure or trend is this responding to?]</p>

<h2>Why It Matters for Broadcast Operations</h2>
<p>[3–4 sentences of original expert analysis. NOT a rewrite of the source. What does this mean for a broadcast engineer's infrastructure decisions over the next 12–18 months? Reference real operational implications — CapEx/OpEx trade-offs, integration complexity, workflow disruption, or competitive dynamics. Mention 2–3 specific, real-world vendors relevant to this development — e.g. if discussing IP gateways: Matrox ConvertIP, Riedel MediorNet; if discussing newsroom: Avid iNEWS, Vizrt Trio; if discussing playout: Pebble Beach Systems, Evertz Mediator-X; if discussing encoding: Harmonic VOS360, Telestream Vantage. Name them naturally, not as a list.]</p>

<h3>Impact by Stakeholder</h3>
<ul>
<li><strong>Regional and national broadcasters:</strong> [CapEx/OpEx impact specific to this type of operator. Reference: {ctx['roi']}. Be concrete — not "may benefit from" but "will need to budget for" or "can eliminate".]</li>
<li><strong>OTT and streaming platforms:</strong> [What changes operationally for a platform running HLS/DASH delivery at scale? ABR ladder, CDN cost per GB, SSAI complexity, or latency budget — pick what's relevant and be specific.]</li>
<li><strong>Post-production and MAM teams:</strong> [Workflow implications for ingest, QC, archive, or content operations. If not applicable, replace with a different affected persona — sports rights holders, news operations, etc.]</li>
</ul>

<h2>Deep Insight: The Broader Industry Shift</h2>
<p>[4–5 sentences. Expert commentary that cannot be reconstructed from the source. Identify the trend this is part of. Name specific competing approaches, predecessor technologies, or alternative architectures. What is the industry moving away from, and toward? Include a prediction: "By [year], we expect…" or "The vendors who will struggle here are…" or "The real risk is not X — it's Y." Take a clear stance.]</p>

[Insert Diagram: [Write a specific, useful description of a technical diagram that would help a broadcast engineer understand the architecture or workflow described in this article. Example: "A signal flow diagram showing IP media ingest from a Matrox ConvertIP gateway through an ST 2110 fabric to a cloud MAM and playout system, with NMOS IS-04 discovery layer annotated."]]

<h2>Comparison: Key Approaches at a Glance</h2>
<p>[1 sentence introducing the comparison table.]</p>
[GENERATE A MARKDOWN TABLE comparing 2–4 approaches, architectures, protocols, or vendor options relevant to this article. Use these columns where appropriate: | Approach | Best For | Key Trade-off | Typical Vendors | Standards Compliance |. The table must contain real, accurate data — not placeholders.]

<h2>Practical Takeaways for Engineering Teams</h2>
<ul>
<li><strong>What to assess first:</strong> [The most important thing an engineering team should evaluate before deploying or integrating this technology. Specific — a particular spec, a certification requirement, or a vendor interop question.]</li>
<li><strong>Standards and compliance to check:</strong> [Named standard with version — e.g. SMPTE ST 2110-20, NMOS IS-04/IS-05, HLS CMAF, DASH-IF IOP 4.3, EBU R 148. No vague references.]</li>
<li><strong>Integration risk to flag:</strong> [The one integration dependency or compatibility issue that will surprise teams who haven't deployed this before.]</li>
<li><strong>What to watch in the next 12 months:</strong> [A specific working group decision, regulatory deadline, vendor product release, or standards update. Name the body or vendor specifically.]</li>
</ul>

<h2>Source Attribution</h2>
<p>This analysis is based on reporting from <strong>{source}</strong>. The editorial commentary, technical assessment, and industry context above represent original analysis by The Streamic and should not be attributed to the source publication.</p>

<div class="art-author-bio">
  <div class="bio-avatar">PK</div>
  <div class="bio-body">
    <strong class="bio-name">Prerak K Mehta</strong>
    <span class="bio-title">Broadcast Systems &amp; Post-Production Engineer · Editor-in-Chief, The Streamic</span>
    <p class="bio-text">Prerak has 25+ years of experience designing and operating broadcast and media technology infrastructure across enterprise environments — including IP signal transport (ST 2110, NDI, SRT), cloud-native production workflows, MAM/PAM systems, and OTT origin and delivery stacks. He founded The Streamic to provide broadcast engineers with analysis that goes beyond vendor press releases. Based in Dublin, Ireland.</p>
  </div>
</div>

{_MANDATORY_FOOTER}

MANDATORY FINAL CHECK before outputting:
— Does the article include at least 2–3 real vendor names used naturally in context? If not, add them.
— Is there a Markdown table with real, accurate comparative data? If not, generate one.
— Is there a [Insert Diagram: ...] placeholder with a specific, useful description? If not, add one.
— Does the Deep Insight section contain at least one prediction or clear stance? If not, rewrite it.
— Can the content be reconstructed from the source alone? If yes, it's not analysis — rewrite.
— Does the author bio present Prerak K Mehta as named author? If not, add it.

RULES:
- 800–1100 words of body content (not counting bio or source attribution)
- Use minimum 4 domain-specific terms from: {ctx['terms']}
- FORBIDDEN: "this highlights", "this underscores", "this reflects", "in today's landscape", "important to note", "rapidly evolving", "plays a key role", "game-changer", "seamless", "delivers", "delve into", "innovative"
- {ctx['guardrail']}
- Output valid HTML. Markdown tables within HTML are acceptable.
- No markdown fences. No triple backticks.

Write the full pillar post now:"""



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
    batch = items_to_process[:MAX_ITEMS_PER_RUN]
    print(f"Items to process: {total} (this run: {len(batch)}) | "
          f"Skipped (high-quality Groq): {skipped_high_quality}")

    processed       = 0
    errors          = 0
    consec_limits   = 0
    quota_exhausted = False  # Flash-Lite quota hit
    pro_exhausted   = False  # Pro quota hit (separate — Flash-Lite still works)
    pro_used        = 0      # Pro calls used this run — capped at PRO_BUDGET_PER_RUN
    _run_start      = time.time()
    _RUN_LIMIT      = 2400   # 40 min — fits inside 45-min GitHub Actions timeout

    for item in batch:
        if time.time() - _run_start > _RUN_LIMIT:
            print(f"      ⏱ Run time limit reached. Stopping cleanly ({processed} saved).")
            break
        if consec_limits >= 2:
            print(f"      ⏱ Gemini rate limit hit {consec_limits}x in a row — skipping run.")
            break

        # Skip remaining items gracefully if quota hit — don't break (lets patch run)
        if quota_exhausted:
            errors += 1
            print(f"  [{processed+errors}/{len(batch)}] Skipped due to quota")
            continue

        slug     = item["slug"]
        title    = item["title"]
        teaser   = item["teaser"]
        category = item["category"]
        source   = item["source"] or "industry source"
        reason   = item.get("reason", "unknown")

        # Decide which model to use for this article
        # Pro: featured/infrastructure categories, budget available, Pro not exhausted
        use_pro = (
            category in PRO_CATEGORIES
            and pro_used < PRO_BUDGET_PER_RUN
            and not pro_exhausted
        )
        model_label = f"Pro (#{pro_used+1}/{PRO_BUDGET_PER_RUN})" if use_pro else "Flash-Lite"
        sleep_time  = SLEEP_PRO if use_pro else SLEEP_SECS

        print(f"  [{processed+1}/{len(batch)}] [{model_label}] {title[:50]}... (reason: {reason})")

        try:
            domain = classify_domain(title, teaser)
            ctx    = _DOMAIN_CONTEXT[domain]

            # ── Step 1: Card summary — single call, fail fast ────────────
            raw_card = gemini_call(build_card_prompt(title, teaser, source), use_pro=use_pro)
            time.sleep(sleep_time)

            if not raw_card or is_generic(raw_card):
                print(f"      ⚠ Generic card — using fallback")
                card_summary = fallback_card(title, teaser)
            else:
                card_summary = re.sub(r"\s+", " ", raw_card).strip()

            # ── Step 2: Full article body — single call, no retry (fail fast) ──
            raw_body  = gemini_call(build_article_prompt(title, teaser, source, category), use_pro=use_pro)
            body_html = re.sub(r"```html?\n?|```\n?", "", raw_body).strip()
            time.sleep(sleep_time)

            body_valid, failures = validate_body_quality(body_html, ctx["terms"])
            if not body_valid:
                print(f"      ⚠ Quality gate: {'; '.join(failures)} — saving anyway")

            qs = compute_quality_score(body_html, card_summary)
            used_model = GEMINI_PRO_MODEL if use_pro else GEMINI_FLASH_LITE_MODEL
            save_summary(slug, card_summary, body_html, qs=qs, model=used_model)
            processed    += 1
            consec_limits = 0
            if use_pro:
                pro_used += 1
            print(f"      ✓ saved (score={qs}/100, model={model_label}) → data/summaries/{slug[:35]}.json")

        except Exception as ex:
            errors += 1
            err_str = str(ex)
            is_quota = ('DAILY_QUOTA_EXHAUSTED' in err_str
                        or any(k in err_str.lower() for k in ['quota', 'exhausted']))

            if is_quota and use_pro:
                # Pro quota hit — downgrade this article to Flash-Lite, keep going
                pro_exhausted = True
                print(f"      ✗ Gemini Pro quota exhausted (used {pro_used} this run) — retrying with Flash-Lite")
                try:
                    raw_card2    = gemini_call(build_card_prompt(title, teaser, source), use_pro=False)
                    time.sleep(SLEEP_SECS)
                    card_summary2 = re.sub(r"\s+", " ", raw_card2).strip() if raw_card2 else fallback_card(title, teaser)
                    raw_body2    = gemini_call(build_article_prompt(title, teaser, source, category), use_pro=False)
                    body_html2   = re.sub(r"```html?\n?|```\n?", "", raw_body2).strip()
                    time.sleep(SLEEP_SECS)
                    qs2 = compute_quality_score(body_html2, card_summary2)
                    save_summary(slug, card_summary2, body_html2, qs=qs2, model=GEMINI_FLASH_LITE_MODEL)
                    processed += 1
                    errors    -= 1
                    print(f"      ✓ Flash-Lite fallback saved (score={qs2}/100)")
                except Exception as fl_ex:
                    print(f"      ✗ Flash-Lite fallback also failed: {fl_ex}")

            elif is_quota:
                # Flash-Lite quota hit — nothing left to try, skip remaining
                quota_exhausted = True
                print(f"      ✗ Gemini Flash-Lite quota exhausted — skipping remaining items")
                if USE_GROQ_FALLBACK:
                    try:
                        from generate_summaries import groq_call, _CARD_PROMPT, _ARTICLE_PROMPT, _DOMAIN_CONTEXT as _GS_CTX
                        print(f"      → Using Groq fallback")
                        domain2 = classify_domain(title, teaser)
                        ctx2    = _GS_CTX[domain2]
                        raw_card2 = groq_call(_CARD_PROMPT.format(
                            title=title, teaser=teaser, source_name=source,
                            domain_label=ctx2["label"], domain_focus=ctx2["focus"],
                            domain_terms=ctx2["terms"], domain_guardrail=ctx2["guardrail"],
                        ), max_tokens=400)
                        raw_body2 = groq_call(_ARTICLE_PROMPT.format(
                            title=title, teaser=teaser, category=category,
                            source_name=source, domain_label=ctx2["label"],
                            domain_focus=ctx2["focus"], domain_terms=ctx2["terms"],
                            domain_guardrail=ctx2["guardrail"], domain_roi=ctx2["roi"],
                        ), max_tokens=1200)
                        body2 = re.sub(r"```html?\n?|```\n?", "", raw_body2).strip()
                        qs2   = compute_quality_score(body2, raw_card2)
                        save_summary(slug, raw_card2, body2, qs=qs2, model="groq-fallback")
                        processed += 1
                        errors    -= 1
                        print(f"      ✓ Groq fallback saved (score={qs2}/100)")
                    except Exception as groq_ex:
                        print(f"      ✗ Groq fallback failed: {groq_ex}")

            elif '429' in err_str or 'rate' in err_str.lower():
                consec_limits += 1
                print(f"      ✗ Rate limit error: {ex}")
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
