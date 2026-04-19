#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assign_images.py v2 — Streamic visual image assigner (flat layout)
==================================================================

CHANGED FROM v1:
- Reads images from FLAT /docs/assets/ (no bucket subfolders).
- AUTO-RENAMES uploads with spaces/uppercase to lowercase-dashed copies
  (e.g. "MEDIA COMPOSER EDIT.png" → "media-composer-edit.png").
- Scores images by filename-keyword → article-text overlap.
- Writes image_url directly — NO build.py changes required.
- Respects hand-authored protected articles (NAB hero, deep dives, Avid).

PIPELINE WIRING (one line in .github/workflows/generate.yml, before build.py):
    python3 scripts/assign_images.py || echo "Image assigner skipped"

Author: The Streamic editorial engineering (v2)
License: MIT
"""

import hashlib, json, os, re, shutil, sys
from typing import Dict, List, Optional, Tuple

ROOT            = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR        = os.path.join(ROOT, "data")
ARTICLES_FILE   = os.path.join(DATA_DIR, "generated_articles.json")
IMAGE_DIR_DISK  = os.path.join(ROOT, "docs", "assets")
IMAGE_URL_BASE  = "/assets"
FALLBACK_ORDER  = ["abstracs-mix.png", "abstracts.png", "fallback.jpg"]

PROTECTED_SLUG_PATTERNS = [
    lambda s: s.startswith("deepdive-"),
    lambda s: s == "nab-2026-hybrid-technology-year",
    lambda s: s == "Expertinsight1",
    lambda s: "avid-google-cloud-agentic-ai-media-production" in s,
]

RESERVED_FILENAMES = {
    "logo.png", "fallback.jpg",
    "nab_show_banner_news_headline_hero.png",
    "nab-show-banner-news-headline-hero.png",
    "gfx-hero-nab-floor.png", "gfx-hero-nab-floor.jpg",
    "hero-broadcast-male.png", "hero-broadcast-male1png",
    "insight-quic-infographic.jpg", "neil-sadwelkar.jpg",
    "studio-grade-ott-workflow-2026.png",
}

STOP_WORDS = {
    "png", "jpg", "jpeg", "webp", "the", "and", "for", "with", "of",
    "a", "an", "in", "on", "at", "to", "image", "photo", "pic", "copy",
    "final", "v1", "v2", "nab", "2026", "2025",
}


def _sanitize(name: str) -> str:
    """'MEDIA COMPOSER EDIT.png' → 'media-composer-edit.png'"""
    base, ext = os.path.splitext(name)
    base = base.lower()
    base = re.sub(r"[\s_]+", "-", base)
    base = re.sub(r"[^a-z0-9\-]", "", base)
    base = re.sub(r"-+", "-", base).strip("-")
    ext = ext.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    return f"{base}{ext}" if base else ""


def _auto_rename_uploads() -> List[str]:
    """Copy files with spaces/uppercase to sanitized names. Returns list of safe filenames."""
    if not os.path.isdir(IMAGE_DIR_DISK):
        print(f"[WARN] Image directory not found: {IMAGE_DIR_DISK}")
        return []

    safe_list: List[str] = []
    seen: set = set()
    try:
        entries = sorted(os.listdir(IMAGE_DIR_DISK))
    except Exception as e:
        print(f"[ERROR] Cannot list {IMAGE_DIR_DISK}: {e}")
        return []

    for fname in entries:
        src = os.path.join(IMAGE_DIR_DISK, fname)
        if not os.path.isfile(src):
            continue
        if not fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        safe = _sanitize(fname)
        if not safe:
            continue
        dest = os.path.join(IMAGE_DIR_DISK, safe)
        if fname != safe and not os.path.exists(dest):
            try:
                shutil.copy2(src, dest)
                print(f"  ↳ renamed copy: '{fname}' → '{safe}'")
            except Exception as e:
                print(f"  ✗ Could not copy '{fname}' → '{safe}': {e}")
                continue
        if safe not in seen and safe.lower() not in RESERVED_FILENAMES:
            safe_list.append(safe)
            seen.add(safe)
    return sorted(safe_list)


def _filename_keywords(fname: str) -> List[str]:
    base = os.path.splitext(fname)[0]
    parts = re.split(r"[-_]", base.lower())
    return [p for p in parts if p and len(p) >= 3 and p not in STOP_WORDS]


def _article_text(art: dict) -> str:
    parts: List[str] = []
    for k in ("title", "slug", "category", "dek", "deck", "summary",
              "excerpt", "card_summary", "meta_description", "topic_type"):
        v = art.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v)
    for k in ("tags", "technical_keywords", "keywords"):
        v = art.get(k)
        if isinstance(v, list):
            parts.append(" ".join(str(x) for x in v if x))
        elif isinstance(v, str):
            parts.append(v)
    body = art.get("body_html") or art.get("body") or ""
    if body:
        body_text = re.sub(r"<[^>]+>", " ", body)
        body_text = re.sub(r"\s+", " ", body_text)
        parts.append(body_text)
    return " ".join(parts).lower()


def _score_image_for_article(kws: List[str], text: str) -> int:
    score = 0
    for kw in kws:
        if len(kw) <= 4:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                score += 1
        else:
            if kw in text:
                score += 1
    return score


def _slug_stable_pick(slug: str, candidates: List[str]) -> str:
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]
    h = int(hashlib.md5((slug or "").encode("utf-8", "ignore")).hexdigest()[:8], 16)
    return sorted(candidates)[h % len(candidates)]


def _read_json(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Cannot read {path}: {e}")
        return None


def _write_json(path: str, data) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[ERROR] Cannot write {path}: {e}")
        return False


def _is_protected(slug: str) -> bool:
    return any(fn(slug) for fn in PROTECTED_SLUG_PATTERNS)


def _is_existing_local_image(image_url: str) -> bool:
    if not image_url or not isinstance(image_url, str):
        return False
    if not (image_url.startswith("/assets/") or image_url.startswith("assets/")):
        return False
    rel = image_url.lstrip("/")
    disk = os.path.join(ROOT, "docs", rel)
    return os.path.isfile(disk)


def main() -> int:
    print("=== assign_images.py v2 — flat layout, auto-rename ===")
    print(f"  Image dir:  {IMAGE_DIR_DISK}")
    print(f"  URL base:   {IMAGE_URL_BASE}\n")

    print("Step 1: Scanning /docs/assets/ for images …")
    safe_files = _auto_rename_uploads()
    if not safe_files:
        print("  ⚠ No editorial images found. Upload .png/.jpg/.jpeg/.webp to docs/assets/")
        return 0
    print(f"  ✓ {len(safe_files)} candidate images (sanitized):")
    for f in safe_files[:20]:
        print(f"      {f}")
    if len(safe_files) > 20:
        print(f"      … and {len(safe_files) - 20} more")
    print()

    image_kws: Dict[str, List[str]] = {f: _filename_keywords(f) for f in safe_files}

    fallback_file = ""
    for c in FALLBACK_ORDER:
        if c in safe_files:
            fallback_file = c
            break
    if not fallback_file and safe_files:
        fallback_file = safe_files[0]
    print(f"Step 2: Fallback image → {fallback_file or '(none)'}\n")

    print(f"Step 3: Reading {ARTICLES_FILE} …")
    articles = _read_json(ARTICLES_FILE)
    if articles is None:
        print("  ⚠ Articles file not found")
        return 0
    if not isinstance(articles, list):
        print(f"  ⚠ Expected list, got {type(articles).__name__}")
        return 1
    print(f"  ✓ {len(articles)} articles loaded\n")

    print("Step 4: Assigning images (diversity-aware, deterministic) …")
    assigned = skipped_protected = skipped_existing = used_fallback = 0
    per_image: Dict[str, int] = {}

    # Pre-compute article-ordering to make distribution deterministic per rebuild.
    # We process articles in slug-sorted order so the per-image counter fills
    # in the same way every time the pipeline runs.
    articles_iter = sorted(
        [a for a in articles if isinstance(a, dict)],
        key=lambda a: a.get("slug", "") or ""
    )

    # Usage floor — the minimum uses any image has. When picking from a
    # tied-score pool, always prefer an image with uses == floor.
    # This prevents the "6 articles all match 'newsroom' → all get newsroom-anchor.png" bug.

    def _pick_with_diversity(slug: str, top_candidates: List[str]) -> str:
        """Pick the LEAST-USED image from the tied-score pool.
        Ties among least-used → deterministic slug-hash pick (stable across rebuilds)."""
        if not top_candidates:
            return ""
        if len(top_candidates) == 1:
            return top_candidates[0]
        # Find minimum usage among candidates
        min_used = min(per_image.get(c, 0) for c in top_candidates)
        least_used = [c for c in top_candidates if per_image.get(c, 0) == min_used]
        if len(least_used) == 1:
            return least_used[0]
        # Still multiple tied — deterministic slug-hash pick among least-used only
        return _slug_stable_pick(slug, sorted(least_used))

    for art in articles_iter:
        slug = art.get("slug", "") or ""
        if _is_protected(slug):
            skipped_protected += 1
            continue
        if _is_existing_local_image(art.get("image_url", "")):
            skipped_existing += 1
            continue

        text = _article_text(art)
        scored: List[Tuple[str, int]] = []
        for fname, kws in image_kws.items():
            if not kws:
                continue
            s = _score_image_for_article(kws, text)
            if s > 0:
                scored.append((fname, s))

        if scored:
            scored.sort(key=lambda x: -x[1])
            max_score = scored[0][1]
            # Widen the pool: include any image within 70% of the top score.
            # This gives the diversity picker more room to breathe without
            # assigning a completely irrelevant image.
            threshold = max(1, int(max_score * 0.7))
            pool = [f for f, s in scored if s >= threshold]
            chosen = _pick_with_diversity(slug, pool)
        else:
            chosen = fallback_file
            used_fallback += 1

        if chosen:
            url = f"{IMAGE_URL_BASE}/{chosen}"
            art["image_url"]         = url
            art["image"]             = url
            art["image_credit"]      = "The Streamic"
            art["image_license"]     = "Site License"
            art["image_license_url"] = ""
            pretty = os.path.splitext(chosen)[0].replace("-", " ").title()
            art["image_alt"]         = f"Streamic editorial image — {pretty}"
            assigned += 1
            per_image[chosen] = per_image.get(chosen, 0) + 1

    # Preserve original article order in the output JSON (we only sorted
    # locally for deterministic assignment; the original list ordering is
    # what build.py expects).

    print(f"  ✓ Assigned: {assigned}")
    print(f"  ○ Skipped (protected / hand-authored): {skipped_protected}")
    print(f"  ○ Skipped (already has local image):   {skipped_existing}")
    print(f"  ○ Used fallback image:                 {used_fallback}\n")

    if not _write_json(ARTICLES_FILE, articles):
        return 1
    print("  ✓ Wrote updated generated_articles.json\n")

    print("Per-image usage (top 15):")
    for f, c in sorted(per_image.items(), key=lambda x: -x[1])[:15]:
        print(f"  {c:4}  {f}")
    print("\n✓ Image assignment complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
