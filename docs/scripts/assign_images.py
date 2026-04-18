#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assign_images.py — Streamic visual taxonomy image assigner
==========================================================

Standalone, deterministic image assignment for The Streamic article corpus.
Runs BEFORE build.py in the pipeline. Does not modify build.py logic.

What it does
------------
1. Reads data/generated_articles.json (and optionally data/hf_articles.json).
2. For each article, scores its title + slug + category + dek + summary +
   body against 10 fixed broadcast/media-tech taxonomy buckets using a
   keyword scoring system that mirrors the Streamic Visual Taxonomy.
3. Picks the highest-scoring bucket. Ties broken by bucket priority order
   (so the result is fully deterministic — same slug always gets the same
   bucket on every rebuild).
4. Within that bucket, picks one local image deterministically using a
   slug-stable hash, so the same article always gets the same image even
   when the bucket has multiple images available.
5. Writes three new fields onto each article and saves the JSON back:
       image          — relative path to the chosen local image
       image_category — taxonomy bucket name
       image_alt      — accessibility alt text
6. Does NOT touch build.py. Does NOT touch any HTML. Does NOT call any
   external API. Does NOT use random selection. Fully UTF-8 safe.

Where to put your image files
-----------------------------
Create this folder structure inside your repo (next to scripts/, docs/, data/):

    assets/
        images/
            ai_automation/
                01.jpg
                02.jpg
                ...
            cloud_production/
                01.jpg
                ...
            streaming_ott/
            broadcast_infrastructure/
            storage_archive/
            post_production/
            virtual_production/
            live_production/
            newsroom_editorial/
            monitoring_qc/
            _fallback/
                streamic-default.jpg

Each subfolder should contain 3–10 .jpg or .webp images sized roughly
1200x675 (16:9). The script auto-discovers whatever files are present;
if a bucket folder is empty or missing, it falls back to the premium
generic fallback image at assets/images/_fallback/streamic-default.jpg.

If you have not yet uploaded any images, the script still runs safely —
every article gets the fallback path, and you can fill in the bucket
folders progressively without re-running anything.

How to wire into the pipeline
-----------------------------
Add ONE line to .github/workflows/build.yml (or generate.yml), immediately
BEFORE the existing `python3 scripts/build.py` step:

    - name: "Stage 5c: Assign taxonomy images"
      run: python3 scripts/assign_images.py || echo "Image assigner skipped"

That's the only pipeline change. build.py picks up the new `image` field
on its own because it already reads from generated_articles.json.

Optional one-line build.py hint (NOT REQUIRED)
----------------------------------------------
If you want build.py to prefer the local taxonomy image over the existing
image_url field, add this single line inside _fix_article_images() at the
top of the for-loop, before any other image logic:

    if a.get("image"): a["image_url"] = a["image"]

That is the entire build.py change. Skipping it is fine — the new `image`
field is still written to disk and available for any future template work.

Author: The Streamic editorial engineering
License: MIT
"""

import hashlib
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR      = os.path.join(ROOT, "data")
ARTICLES_FILE = os.path.join(DATA_DIR, "generated_articles.json")
HF_FILE       = os.path.join(DATA_DIR, "hf_articles.json")

# Image folder root, relative to repo root. Each taxonomy bucket has its own
# subfolder under here. The path written into the JSON is relative to the
# site root so it works both in build.py output and on the live server.
IMAGE_ROOT_DISK = os.path.join(ROOT, "assets", "images")
IMAGE_ROOT_WEB  = "/assets/images"  # leading slash so it resolves from root

# Premium generic fallback — used when no bucket matches OR the matched
# bucket has no image files on disk yet.
FALLBACK_REL = "_fallback/streamic-default.jpg"


# ── Streamic Visual Taxonomy ──────────────────────────────────────────────────
# 10 fixed buckets. Each bucket has:
#   - keywords: lowercased substrings scored against article text
#   - weight  : per-keyword score boost (some keywords are more diagnostic)
#   - alt_template: accessibility text used when an article matches this bucket
# Buckets are listed in priority order — when two buckets tie on score, the
# one listed FIRST wins. This makes assignment fully deterministic.

TAXONOMY: List[Dict] = [
    {
        "id": "ai_automation",
        "label": "AI in Broadcasting / Automation",
        "alt_template": "AI-driven broadcast automation dashboard",
        "keywords": [
            ("artificial intelligence", 5), ("machine learning", 5),
            ("ai-powered", 4), ("ai automation", 5), ("ai metadata", 5),
            ("neural network", 4), ("deep learning", 4), ("llm", 3),
            ("generative ai", 5), ("ai workflow", 4), ("ai inference", 4),
            ("automation", 2), ("ai dashboard", 4), ("ai tagging", 5),
            ("intelligent automation", 4), (" ai ", 3), ("ai-driven", 4),
        ],
    },
    {
        "id": "virtual_production",
        "label": "Virtual Production / XR / Graphics",
        "alt_template": "Virtual production LED wall stage with real-time graphics",
        "keywords": [
            ("led wall", 5), ("virtual production", 5), ("xr studio", 5),
            ("xr stage", 5), (" xr ", 4), ("vfx", 4), ("real-time render", 4),
            ("unreal engine", 5), ("real time graphics", 4),
            ("vizrt", 4), ("viz engine", 4), ("chyron", 4),
            ("graphics workstation", 4), ("ar graphics", 4),
            ("augmented reality", 4), ("immersive", 3),
        ],
    },
    {
        "id": "post_production",
        "label": "Post Production / Editing / DI",
        "alt_template": "Cinematic post-production editing and color grading suite",
        "keywords": [
            ("color grade", 5), ("color grading", 5), ("colour grading", 5),
            ("davinci resolve", 5), ("avid media composer", 5),
            ("premiere pro", 5), ("post production", 5), ("post-production", 5),
            ("digital intermediate", 5), (" di suite", 4),
            ("editing suite", 4), ("vfx pipeline", 4), ("dailies", 4),
            ("mastering", 3), ("finishing", 3), ("aces", 3),
            ("hdr master", 4), ("nle", 3),
        ],
    },
    {
        "id": "live_production",
        "label": "Live Production / OB / Sports",
        "alt_template": "Live multi-camera production control room",
        "keywords": [
            ("live production", 5), ("ob van", 5), ("ob truck", 5),
            ("outside broadcast", 5), ("sports broadcast", 5),
            ("multicamera", 4), ("multi-camera", 4), ("live event", 4),
            ("production truck", 5), ("sports production", 5),
            ("evs", 4), ("replay", 3), ("ipl", 3), ("nfl", 3),
            ("olympics", 4), ("world cup", 4), ("vision mixer", 4),
            ("live switching", 4), ("pcr", 2),
        ],
    },
    {
        "id": "newsroom_editorial",
        "label": "Newsroom / NRCS / Editorial Ops",
        "alt_template": "Modern broadcast newsroom and editorial operations",
        "keywords": [
            ("newsroom", 5), ("nrcs", 5), ("inews", 5), ("enps", 5),
            ("octopus newsroom", 5), ("dalet", 4), ("mediacentral", 4),
            ("mos protocol", 4), ("editorial workflow", 4),
            ("rundown", 4), ("news production", 4), ("journalist", 3),
            ("wire ingest", 4), ("news automation", 4), ("breaking news", 3),
        ],
    },
    {
        "id": "cloud_production",
        "label": "Cloud Production / REMI / Virtualized Workflows",
        "alt_template": "Cloud-based broadcast production and remote workflow",
        "keywords": [
            ("cloud production", 5), ("cloud playout", 5), ("cloud workflow", 5),
            ("aws medialive", 5), ("mediaconvert", 5), ("mediaconnect", 5),
            ("aws elemental", 5), ("azure media", 5), ("google cloud", 4),
            ("remi", 5), ("remote production", 5), ("virtualized", 4),
            ("containerised", 4), ("containerized", 4), ("kubernetes", 4),
            ("microservices", 3), ("hybrid cloud", 4), ("cloud-native", 4),
            ("cloud native", 4), ("saas", 3), ("paas", 3),
        ],
    },
    {
        "id": "streaming_ott",
        "label": "Streaming / OTT / CDN / Delivery",
        "alt_template": "OTT streaming platform and content delivery analytics",
        "keywords": [
            ("ott", 4), (" hls", 4), (" dash ", 4), ("cmaf", 5),
            ("streaming platform", 5), ("streaming service", 4),
            ("cdn", 5), ("content delivery network", 5),
            ("akamai", 4), ("cloudfront", 4), ("fastly", 4),
            ("ssai", 5), ("server-side ad insertion", 5),
            ("abr ladder", 5), ("adaptive bitrate", 5), ("drm", 4),
            ("widevine", 4), ("playready", 4), ("fairplay", 4),
            ("low latency", 3), ("fast channel", 4), ("vod", 3),
            ("subscriber", 3), ("netflix", 3), ("disney+", 3),
            ("amazon prime video", 3), ("youtube", 2),
        ],
    },
    {
        "id": "broadcast_infrastructure",
        "label": "Broadcast Infrastructure / ST 2110 / IP Networks",
        "alt_template": "Broadcast IP network infrastructure and SMPTE ST 2110 fabric",
        "keywords": [
            ("st 2110", 5), ("st-2110", 5), ("smpte 2110", 5),
            ("nmos", 5), ("is-04", 4), ("is-05", 4), ("aes67", 5),
            ("ndi", 4), (" sdi ", 4), ("ptp", 5), ("ieee 1588", 5),
            ("ip transport", 4), ("ip migration", 4),
            ("network switch", 4), ("fiber optic", 4),
            ("router matrix", 4), ("audio over ip", 4),
            ("ip-based", 4), ("ip based", 4), ("hybrid ip", 4),
            ("dante", 4), ("jpeg xs", 5), ("st 2022", 4),
        ],
    },
    {
        "id": "storage_archive",
        "label": "Storage / MAM / Archive",
        "alt_template": "Enterprise media storage and digital archive infrastructure",
        "keywords": [
            (" mam ", 4), ("media asset management", 5),
            (" pam ", 4), ("production asset management", 5),
            ("archive", 4), ("nearline storage", 5),
            ("avid nexis", 5), ("nexis", 4),
            ("object storage", 5), ("lto", 5), ("lto-9", 5),
            ("tape library", 5), ("nas storage", 4),
            ("san storage", 4), ("nvme", 3), ("petabyte", 4),
            ("deep archive", 5), ("glacier", 4),
            ("storage tier", 4), ("retention policy", 3),
        ],
    },
    {
        "id": "monitoring_qc",
        "label": "Monitoring / Compliance / QC",
        "alt_template": "Broadcast monitoring wall and quality control station",
        "keywords": [
            ("monitoring wall", 5), ("multiviewer", 5),
            ("waveform monitor", 5), ("vectorscope", 5),
            ("loudness", 4), ("compliance", 4),
            ("qc", 3), ("quality control", 5),
            ("ebu r128", 5), ("atsc 3", 4), ("dvb", 3),
            ("captioning", 3), ("subtitle compliance", 4),
            ("c2pa", 4), ("provenance", 3),
            ("signal integrity", 4), ("test pattern", 3),
        ],
    },
]

# Map category slugs that may appear in JSON `category` field directly to a
# bucket id, as a strong hint. This is a soft signal added on top of keyword
# scoring (worth ~8 points), not a hard override.
CATEGORY_HINTS: Dict[str, str] = {
    "ai-post-production": "ai_automation",
    "ai":                 "ai_automation",
    "cloud":              "cloud_production",
    "cloud-production":   "cloud_production",
    "streaming":          "streaming_ott",
    "ott":                "streaming_ott",
    "infrastructure":     "broadcast_infrastructure",
    "broadcast":          "broadcast_infrastructure",
    "playout":            "broadcast_infrastructure",
    "graphics":           "virtual_production",
    "post-production":    "post_production",
    "newsroom":           "newsroom_editorial",
    "live":               "live_production",
    "sports":             "live_production",
    "monitoring":         "monitoring_qc",
    "storage":            "storage_archive",
    "archive":            "storage_archive",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_json(path: str) -> Optional[list]:
    """UTF-8 safe JSON read. Returns None if file missing/unreadable."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Could not read {path}: {e}")
        return None


def _write_json(path: str, data) -> bool:
    """UTF-8 safe JSON write with pretty indent."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[ERROR] Could not write {path}: {e}")
        return False


def _gather_text(article: dict) -> str:
    """
    Concatenate every text-bearing field on the article into one lowercase
    blob for keyword scoring. Missing fields are silently skipped.
    """
    parts = []
    for key in (
        "title", "slug", "dek", "deck", "summary", "excerpt",
        "card_summary", "meta_description", "topic_type",
    ):
        v = article.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v)

    # tags / keywords may be lists
    for key in ("tags", "technical_keywords", "keywords"):
        v = article.get(key)
        if isinstance(v, list):
            parts.append(" ".join(str(x) for x in v if x))
        elif isinstance(v, str):
            parts.append(v)

    # body — strip HTML tags cheaply, no external lib
    body = article.get("body_html") or article.get("body") or ""
    if body:
        import re
        body_text = re.sub(r"<[^>]+>", " ", body)
        body_text = re.sub(r"\s+", " ", body_text)
        parts.append(body_text)

    return " ".join(parts).lower()


def _score_buckets(text: str, category: str) -> List[Tuple[str, int]]:
    """
    Score every taxonomy bucket against the article text.
    Returns a list of (bucket_id, score) tuples in TAXONOMY priority order
    (so ties resolve naturally to the higher-priority bucket).
    """
    scores: List[Tuple[str, int]] = []
    cat_lower = (category or "").lower().strip()

    for bucket in TAXONOMY:
        score = 0
        for kw, weight in bucket["keywords"]:
            if kw in text:
                # Each unique keyword counts once — multi-occurrence doesn't
                # inflate the score, which keeps long articles from
                # dominating short ones unfairly.
                score += weight
        # Category hint bonus
        if cat_lower in CATEGORY_HINTS and CATEGORY_HINTS[cat_lower] == bucket["id"]:
            score += 8
        scores.append((bucket["id"], score))

    return scores


def _pick_bucket(scores: List[Tuple[str, int]]) -> str:
    """
    Choose the winning bucket. Highest score wins. Ties broken by TAXONOMY
    priority order (the list is iterated in order, so the first bucket to
    reach the max stays the winner).
    """
    if not scores:
        return TAXONOMY[0]["id"]
    max_score = max(s for _, s in scores)
    if max_score == 0:
        # No keywords matched — return a sentinel that callers map to fallback
        return ""
    for bucket_id, score in scores:
        if score == max_score:
            return bucket_id
    return TAXONOMY[0]["id"]


def _list_bucket_files(bucket_id: str) -> List[str]:
    """Return sorted list of image filenames in a bucket folder, or []."""
    folder = os.path.join(IMAGE_ROOT_DISK, bucket_id)
    if not os.path.isdir(folder):
        return []
    try:
        files = sorted(
            f for f in os.listdir(folder)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            and not f.startswith(".")
        )
        return files
    except Exception:
        return []


def _slug_stable_pick(slug: str, files: List[str]) -> str:
    """
    Deterministically pick one filename from a list using a hash of the slug.
    Same slug → same file → same image on every rebuild. No randomness.
    """
    if not files:
        return ""
    if len(files) == 1:
        return files[0]
    h = int(hashlib.md5((slug or "").encode("utf-8", "ignore")).hexdigest()[:8], 16)
    return files[h % len(files)]


def _resolve_image(bucket_id: str, slug: str) -> Tuple[str, bool]:
    """
    Returns (web_path, used_fallback). The web_path is what gets written
    into the JSON's `image` field — always relative to site root with a
    leading slash so it works in any template.
    """
    if bucket_id:
        files = _list_bucket_files(bucket_id)
        if files:
            picked = _slug_stable_pick(slug, files)
            return f"{IMAGE_ROOT_WEB}/{bucket_id}/{picked}", False
    # Fallback path — used when no bucket matched or bucket folder is empty
    return f"{IMAGE_ROOT_WEB}/{FALLBACK_REL}", True


def _alt_for(bucket_id: str, title: str) -> str:
    """Build accessibility alt text from the bucket label and article title."""
    bucket = next((b for b in TAXONOMY if b["id"] == bucket_id), None)
    template = bucket["alt_template"] if bucket else "Streamic broadcast technology"
    safe_title = (title or "").strip()[:120]
    if safe_title:
        return f"{template} — illustrating: {safe_title}"
    return template


# ── Main pipeline ─────────────────────────────────────────────────────────────

def process_articles(articles: list, source_label: str) -> Tuple[int, int, Dict[str, int]]:
    """
    Mutate each article in place, adding image / image_category / image_alt.
    Returns (total, fallback_count, per_bucket_count).
    """
    if not isinstance(articles, list):
        print(f"[WARN] {source_label}: expected a list, got {type(articles).__name__}")
        return 0, 0, {}

    total = 0
    fb_count = 0
    per_bucket: Dict[str, int] = {}

    for art in articles:
        if not isinstance(art, dict):
            continue
        slug = art.get("slug", "") or ""
        title = art.get("title", "") or ""
        category = art.get("category", "") or ""

        text = _gather_text(art)
        scores = _score_buckets(text, category)
        bucket_id = _pick_bucket(scores)

        web_path, used_fallback = _resolve_image(bucket_id, slug)

        art["image"]          = web_path
        art["image_category"] = bucket_id or "fallback"
        art["image_alt"]      = _alt_for(bucket_id, title)

        total += 1
        if used_fallback:
            fb_count += 1
        key = bucket_id or "fallback"
        per_bucket[key] = per_bucket.get(key, 0) + 1

    return total, fb_count, per_bucket


def main() -> int:
    print("=== assign_images.py — Streamic visual taxonomy ===")
    print(f"  Image root (disk): {IMAGE_ROOT_DISK}")
    print(f"  Image root (web):  {IMAGE_ROOT_WEB}")
    print()

    any_processed = False

    for path, label in (
        (ARTICLES_FILE, "generated_articles.json"),
        (HF_FILE,       "hf_articles.json"),
    ):
        articles = _read_json(path)
        if articles is None:
            print(f"  ⚠ Skipping {label} (not found)")
            continue
        total, fb, per_bucket = process_articles(articles, label)
        if total == 0:
            print(f"  ⚠ {label}: no articles processed")
            continue

        if not _write_json(path, articles):
            print(f"  ✗ Failed to write {label}")
            return 1

        print(f"  ✓ {label}: {total} articles tagged ({fb} fallback)")
        for bucket_id, count in sorted(per_bucket.items(), key=lambda x: -x[1]):
            print(f"      {bucket_id:<28} {count}")
        print()
        any_processed = True

    if not any_processed:
        print("  ⚠ No article files found — nothing to do")
        return 0

    print("✓ Image assignment complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
