#!/usr/bin/env python3
"""
rewrite_feed.py  —  The Streamic
Converts data/news.json (raw RSS) → data/generated_articles.json

Key additions over original:
  • BLOCKED_DOMAINS  — exclude off-topic RSS sources (VFX blogs, entertainment)
  • BLOCKED_KEYWORDS — exclude articles whose title/description matches VFX/entertainment terms
  • Deduplication    — slugs seen in a single run are not added twice
  • Category mapping — BroadcastBeat / TVBEurope sources get correct category tags
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR       = Path(__file__).parent.parent / "data"
NEWS_FILE      = DATA_DIR / "news.json"
ARTICLES_FILE  = DATA_DIR / "generated_articles.json"

# ── Source filtering ──────────────────────────────────────────────────────────
# Domains whose articles should NEVER appear on The Streamic.
# Add any off-topic RSS source here — full domain match (case-insensitive).
BLOCKED_DOMAINS = {
    "beforesandafters.com",
    "beforeandaftersmag.com",
    "fxguide.com",
    "vfxblog.com",
    "motionographer.com",
    "animationmagazine.net",
    "awn.com",
    "cartoonbrew.com",
    "hollywoodreporter.com",
    "deadline.com",
    "variety.com",
    "thewrap.com",
    "indiewire.com",
    "screendaily.com",
}

# Title / description keywords that indicate off-topic content.
# Any article whose title OR description contains one of these phrases is dropped.
# All comparisons are case-insensitive.
BLOCKED_KEYWORDS = [
    # VFX / animation / entertainment
    "vfx breakdown",
    "visual effects breakdown",
    "season 4",
    "stranger things",
    "the witcher",
    "game of thrones",
    "animation breakdown",
    "behind the vfx",
    "cgi breakdown",
    "how to animate",
    "motion graphics reel",
    # General entertainment — not broadcast tech
    "box office",
    "streaming ratings",
    "celebrity",
    "film review",
    "movie review",
    "tv review",
    "series review",
]

# ── Source → Category mapping ─────────────────────────────────────────────────
SOURCE_CATEGORY_MAP = {
    "broadcastbeat":        "Broadcast Technology",
    "tvbeurope":            "Broadcast Technology",
    "tvtechnology":         "Broadcast Technology",
    "ibc":                  "Broadcast Technology",
    "tvnewscheck":          "Broadcast Technology",
    "streamingmediablog":   "Streaming Technology",
    "streamingmedia":       "Streaming Technology",
    "ottverse":             "Streaming Technology",
    "haivision":            "IP & Cloud",
    "harmonic":             "IP & Cloud",
    "telestream":           "Workflow & MAM",
    "mediapulse":           "Workflow & MAM",
    "mediatransit":         "Workflow & MAM",
    "aja":                  "Hardware & Infrastructure",
    "blackmagicdesign":     "Hardware & Infrastructure",
    "belden":               "Infrastructure",
    "evertz":               "Infrastructure",
    "miranda":              "Infrastructure",
    "redtech":              "Broadcast Technology",
    "broadcastsystems":     "Broadcast Technology",
}

DEFAULT_CATEGORY = "Broadcast Technology"


# ── Helpers ───────────────────────────────────────────────────────────────────
def make_slug(title: str, date_str: str, category: str) -> str:
    date_part = date_str[:10] if date_str else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cat_slug  = re.sub(r"[^a-z0-9]+", "-", (category or "news").lower()).strip("-")
    title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:55]
    return f"{date_part}-{cat_slug}-{title_slug}"


def is_blocked(item: dict) -> bool:
    """Return True if this item should be excluded from The Streamic."""
    # Domain block
    source_url = (item.get("link") or item.get("url") or "").lower()
    for domain in BLOCKED_DOMAINS:
        if domain in source_url:
            return True

    # Source name block (for feeds where URL isn't stored but source name is)
    source_name = (item.get("source") or item.get("source_name") or "").lower()
    for domain in BLOCKED_DOMAINS:
        # Match on domain root (e.g. "beforesandafters" in "Befores & Afters")
        domain_root = domain.split(".")[0].replace("-", "")
        if domain_root in source_name.replace(" ", "").replace("&", ""):
            return True

    # Keyword block (title + description)
    text_to_check = " ".join([
        item.get("title", ""),
        item.get("description", ""),
        item.get("summary", ""),
    ]).lower()
    for kw in BLOCKED_KEYWORDS:
        if kw.lower() in text_to_check:
            return True

    return False


def infer_category(item: dict) -> str:
    source = (
        item.get("source") or item.get("source_name") or
        item.get("feed_name") or ""
    ).lower().replace(" ", "").replace("&", "").replace("-", "")

    for key, cat in SOURCE_CATEGORY_MAP.items():
        if key in source:
            return cat
    return DEFAULT_CATEGORY


def parse_date(item: dict) -> str:
    for field in ("published", "pubDate", "date", "updated"):
        val = item.get(field)
        if val:
            # Normalise to YYYY-MM-DD
            m = re.search(r"(\d{4}-\d{2}-\d{2})", str(val))
            if m:
                return m.group(1)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def build_article_stub(item: dict) -> dict:
    title    = (item.get("title") or "").strip()
    date_str = parse_date(item)
    category = infer_category(item)
    slug     = make_slug(title, date_str, category)

    description = (
        item.get("description") or
        item.get("summary") or
        item.get("content") or ""
    ).strip()
    # Strip HTML from description for use as initial body_html / dek
    plain_desc = re.sub(r"<[^>]+>", " ", description)
    plain_desc = re.sub(r"\s+", " ", plain_desc).strip()

    # Wrap in a minimal HTML paragraph so build.py can render it
    initial_body = f"<p>{plain_desc}</p>" if plain_desc else ""

    return {
        "slug":             slug,
        "title":            title,
        "date":             date_str,
        "category":         category,
        "source":           item.get("source") or item.get("source_name") or "",
        "source_url":       item.get("link") or item.get("url") or "",
        "body_html":        initial_body,
        "word_count":       len(plain_desc.split()) if plain_desc else 0,
        "dek":              plain_desc[:200] if plain_desc else "",
        "card_summary":     plain_desc[:200] if plain_desc else "",
        "meta_description": f"{title}. {plain_desc[:120]}" if plain_desc else title,
        "is_editorial":     False,
        "image_url":        item.get("image") or item.get("image_url") or "",
        "tags":             item.get("tags") or [],
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not NEWS_FILE.exists():
        print(f"[ERROR] {NEWS_FILE} not found — run fetch_rss.py first")
        return

    with open(NEWS_FILE, "r", encoding="utf-8") as f:
        news_data = json.load(f)

    # news.json may be a list or a dict with a key like "articles" or "items"
    if isinstance(news_data, dict):
        raw_items = (
            news_data.get("articles") or
            news_data.get("items") or
            news_data.get("entries") or
            list(news_data.values())[0] if news_data else []
        )
    else:
        raw_items = news_data

    print(f"[INFO] {len(raw_items)} raw RSS items loaded from news.json")

    # Load existing articles (preserve manually edited / editorial ones)
    existing: list[dict] = []
    if ARTICLES_FILE.exists():
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing_slugs = {a["slug"] for a in existing}

    # Filter and build new stubs
    added   = 0
    blocked = 0
    dupes   = 0
    seen_slugs_this_run: set[str] = set()

    for item in raw_items:
        if is_blocked(item):
            blocked += 1
            title = item.get("title", "")[:60]
            print(f"  [BLOCKED] {title}")
            continue

        stub = build_article_stub(item)
        slug = stub["slug"]

        if slug in existing_slugs or slug in seen_slugs_this_run:
            dupes += 1
            continue

        existing.append(stub)
        existing_slugs.add(slug)
        seen_slugs_this_run.add(slug)
        added += 1

    # Sort by date descending
    existing.sort(key=lambda a: a.get("date", ""), reverse=True)

    with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] news.json → generated_articles.json")
    print(f"  Added:   {added} new articles")
    print(f"  Blocked: {blocked} off-topic items")
    print(f"  Dupes:   {dupes} skipped")
    print(f"  Total:   {len(existing)} articles in store")


if __name__ == "__main__":
    main()
