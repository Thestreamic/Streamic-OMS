"""
scripts/rewrite_feed.py
=======================
Local-first RSS -> value-added Streamic articles.

Goals:
- publish at most 20 strong RSS-derived stories per run
- keep source credit/link
- avoid heavy API dependence
- generate detailed, useful internal pages from title + teaser only
- preserve existing URLs/templates/build flow
"""

import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

ROOT     = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NEWS_F   = os.path.join(ROOT, "data", "news.json")
POOLS_F  = os.path.join(ROOT, "data", "image_pools.json")
OUTPUT_F = os.path.join(ROOT, "data", "generated_articles.json")

MAX_STORIES_PER_RUN = 20
MAX_TOTAL_KEPT      = 400
CARD_WORD_TARGET    = 170
BODY_WORD_TARGET    = 520
MIN_PER_CATEGORY    = 1
MAX_PER_CATEGORY    = 5

CAT_META = {
    "featured":           {"label":"Featured",            "icon":"⭐","color":"#1d1d1f","page":"featured.html",              "weight": 1.15},
    "streaming":          {"label":"Streaming",           "icon":"📡","color":"#0071e3","page":"streaming.html",             "weight": 1.10},
    "cloud":              {"label":"Cloud Production",    "icon":"☁️","color":"#5856d6","page":"cloud.html",                 "weight": 1.08},
    "graphics":           {"label":"Graphics",            "icon":"🎨","color":"#FF9500","page":"graphics.html",              "weight": 0.92},
    "playout":            {"label":"Playout",             "icon":"▶️","color":"#34C759","page":"playout.html",               "weight": 1.02},
    "infrastructure":     {"label":"Infrastructure",      "icon":"🏗️","color":"#8E8E93","page":"infrastructure.html",        "weight": 1.10},
    "ai-post-production": {"label":"AI & Post-Production","icon":"🎬","color":"#FF2D55","page":"ai-post-production.html",   "weight": 1.05},
    "newsroom":           {"label":"Newsroom",            "icon":"📰","color":"#D4AF37","page":"newsroom.html",              "weight": 1.12},
}

TRUSTED_SOURCE_BONUS = {
    "AWS": 8, "TV Technology": 8, "BroadcastBeat": 7, "Haivision": 6,
    "Telestream": 6, "Vizrt": 6, "Harmonic": 6, "Frame.io": 5,
    "Avid Press Room": 5, "Streaming Media Blog": 6, "Microsoft Security": 7,
}

KEYWORD_BONUS = {
    "nab": 10, "ibc": 8, "cloud": 7, "ai": 7, "automation": 6,
    "streaming": 7, "ott": 7, "cdn": 7, "latency": 6, "sports": 5,
    "newsroom": 7, "st 2110": 9, "smpte": 8, "jpeg xs": 8, "drm": 6,
    "ad insertion": 7, "ssai": 7, "media asset": 6, "metadata": 6,
}

BOILERPLATE = re.compile(
    r"\b(today announced|is pleased to announce|proud to introduce|we are excited|leading provider of|industry-leading|state-of-the-art|cutting-edge|revolutionary|game-changing|best-in-class|world-class)\b",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    return re.sub(r"\s{2,}", " ", BOILERPLATE.sub("", text or "")).strip()


def _split_sents(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", _clean(text)) if s.strip()]


def _hash_int(*parts: str) -> int:
    return int(hashlib.md5("::".join(parts).encode()).hexdigest(), 16)


def make_slug(title, pub_date, cat=""):
    date_part  = (pub_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    cat_part   = re.sub(r"[^\w]", "-", (cat or "").lower()).strip("-")[:12]
    title_part = re.sub(r"[^\w\s-]", "", title.lower())
    title_part = re.sub(r"[\s_]+", "-", title_part).strip("-")
    prefix     = f"{date_part}-{cat_part}-" if cat_part else f"{date_part}-"
    return f"{prefix}{title_part[:65 - len(prefix)]}"


def pick_image(cat, slug, pools):
    cat_pool = pools.get("cat_pools", {}).get(cat, [])
    if not cat_pool:
        cat_pool = [p for lst in pools.get("cat_pools", {}).values() for p in lst] or ["photo-1598488035139-bdbb2231ce04"]
    idx = _hash_int(cat, slug) % len(cat_pool)
    return {
        "image_url":         f"https://images.unsplash.com/{cat_pool[idx]}?w=1200&auto=format&fit=crop&q=80",
        "image_credit":      "Photo: Unsplash — free to use under the Unsplash License",
        "image_license":     "Unsplash License",
        "image_license_url": "https://unsplash.com/license",
    }


def score_item(item):
    title  = (item.get("title") or "").lower()
    teaser = (item.get("teaser") or item.get("description") or "").lower()
    text = f"{title} {teaser}"
    cat = item.get("category") or "featured"
    src = item.get("source") or item.get("source_domain") or ""
    score = 40.0 * CAT_META.get(cat, {"weight": 1.0})["weight"]
    score += TRUSTED_SOURCE_BONUS.get(src, 0)
    for kw, bonus in KEYWORD_BONUS.items():
        if kw in text:
            score += bonus
    if item.get("image"):
        score += 3
    if len(teaser.split()) >= 12:
        score += 6
    pub = (item.get("published") or item.get("pubDate") or "")[:10]
    if pub:
        try:
            days = (datetime.now(timezone.utc).date() - datetime.fromisoformat(pub).date()).days
            score += max(0, 10 - days)
        except Exception:
            pass
    # deterministically break ties
    score += (_hash_int(title, src) % 100) / 1000.0
    return score


def flatten_news(news_raw):
    if isinstance(news_raw, list):
        items = news_raw
    else:
        items = []
        for cat, rows in (news_raw or {}).items():
            for row in (rows or []):
                row = dict(row)
                row.setdefault("category", cat)
                items.append(row)
    return items


def select_best_items(news_items):
    scored = []
    for row in news_items:
        if not row.get("title"):
            continue
        row = dict(row)
        row["category"] = row.get("category") or "featured"
        row["score"] = score_item(row)
        scored.append(row)
    scored.sort(key=lambda x: (x["score"], x.get("published") or x.get("pubDate") or ""), reverse=True)

    selected = []
    per_cat = defaultdict(int)
    used_titles = set()

    # Pass 1: ensure category diversity
    for row in scored:
        cat = row["category"]
        title_key = row["title"].strip().lower()
        if per_cat[cat] >= MIN_PER_CATEGORY or title_key in used_titles:
            continue
        selected.append(row)
        per_cat[cat] += 1
        used_titles.add(title_key)
        if len(selected) >= min(MAX_STORIES_PER_RUN, len(CAT_META)):
            break

    # Pass 2: fill by score with per-category caps
    for row in scored:
        if len(selected) >= MAX_STORIES_PER_RUN:
            break
        cat = row["category"]
        title_key = row["title"].strip().lower()
        if title_key in used_titles or per_cat[cat] >= MAX_PER_CATEGORY:
            continue
        selected.append(row)
        per_cat[cat] += 1
        used_titles.add(title_key)

    selected.sort(key=lambda x: (x.get("published") or x.get("pubDate") or "", x["score"]), reverse=True)
    return selected


def _sentence_bank(slug, cat):
    cat_label = CAT_META.get(cat, CAT_META["featured"])["label"]
    return {
        "impact": [
            f"For {cat_label.lower()} teams, the headline matters less than the operational knock-on effects: tooling changes, workflow adjustments, and where the next engineering bottleneck appears.",
            "The real question for broadcasters is whether this changes cost, speed, reliability, or editorial control in a measurable way over the next two planning cycles.",
            "This is the kind of development that often looks incremental in a press release but becomes meaningful once it touches ingest, monitoring, distribution, or post-production throughput.",
            "Most engineering leads will read this through a practical lens: what gets easier to automate, what becomes easier to scale, and what new dependency enters the stack.",
        ],
        "ops": [
            "Operationally, teams should look at validation, rollback, observability, and staff readiness before they treat the announcement as production-safe.",
            "The likely first checkpoint is integration: whether the change fits existing MAM, playout, graphics, cloud, or control-room workflows without introducing extra manual handling.",
            "Where this becomes valuable is in day-to-day execution: fewer handoffs, better metadata flow, faster publishing, or more predictable output under deadline pressure.",
            "The decision is rarely about one feature alone; it is about whether the surrounding vendor support, interoperability, and operational maturity are good enough for real deployment.",
        ],
        "view": [
            "The Streamic view is that teams should treat this as a planning signal rather than a hype signal: review the architecture, map the dependencies, and decide whether a pilot is justified.",
            "For most organisations, the best next step is not a rushed rollout but a controlled test against a live workflow pain point that already costs time or introduces risk.",
            "This story fits a broader pattern across media technology: software-defined workflows are winning when they remove repetitive labour without adding fragile complexity.",
            "What makes the story worth tracking is not just the vendor claim, but the way it lines up with current pressure on efficiency, flexibility, and multi-platform delivery.",
        ],
    }


def _pick(pool, seed, n=1):
    idxs = list(range(len(pool)))
    idxs.sort(key=lambda i: _hash_int(seed, str(i)))
    return [pool[i] for i in idxs[:n]]


def build_card_summary(title, teaser, cat, source):
    teaser = _clean(teaser)
    sents = _split_sents(f"{title}. {teaser}")
    lead = sents[1] if len(sents) > 1 else teaser or title
    bank = _sentence_bank(title, cat)
    parts = [lead]
    parts.extend(_pick(bank["impact"], title+cat, 1))
    parts.extend(_pick(bank["ops"], source+cat, 1))
    summary = " ".join(parts)
    words = summary.split()
    return " ".join(words[:CARD_WORD_TARGET])


def build_article_body(title, teaser, slug, cat="featured", source=""):
    teaser = _clean(teaser)
    sents = _split_sents(f"{title}. {teaser}")
    lead = sents[0] if sents else title
    detail = sents[1] if len(sents) > 1 else teaser
    bank = _sentence_bank(slug, cat)
    impact = _pick(bank["impact"], slug+"impact", 2)
    ops    = _pick(bank["ops"], slug+"ops", 2)
    view   = _pick(bank["view"], slug+"view", 2)
    cat_ctx = CAT_META.get(cat, CAT_META["featured"])["label"]

    paras = [
        f"<p><strong>{lead}</strong> {detail}</p>",
        f"<p>This item sits inside the broader {cat_ctx.lower()} conversation, where buyers and operators are under pressure to increase flexibility without increasing operational drag.</p>",
        f"<p>{impact[0]}</p>",
        f"<p>{impact[1]}</p>",
        f"<p><strong>What changed in practice:</strong> the story points to a shift in how teams may handle deployment, integration, or scaling over the next few quarters.</p>",
        f"<p>{ops[0]}</p>",
        f"<p>{ops[1]}</p>",
        f"<p><strong>Why it matters:</strong> engineering leaders are increasingly judged on whether they can simplify operations while preserving resilience, observability, and editorial speed.</p>",
        f"<p>{view[0]}</p>",
        f"<p>{view[1]}</p>",
        f"<p>The operational takeaway is straightforward: evaluate the change against a real workflow bottleneck, not against vendor language alone, and use the source material as the technical reference point for any deeper review.</p>",
    ]
    body = "\n".join(paras)
    wc = len(re.sub(r"<[^>]+>", " ", body).split())
    return body, wc


def main():
    print("=== rewrite_feed.py ===")
    with open(NEWS_F, "r", encoding="utf-8") as f:
        news_raw = json.load(f)
    with open(POOLS_F, "r", encoding="utf-8") as f:
        pools = json.load(f)

    existing = []
    if os.path.exists(OUTPUT_F):
        with open(OUTPUT_F, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except Exception:
                existing = []

    existing_by_slug = {a.get("slug"): a for a in existing if a.get("slug")}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    selected = select_best_items(flatten_news(news_raw))
    print(f"Selected best RSS items this run: {len(selected)}")

    fresh_articles = []
    touched_slugs = set()
    for item in selected:
        cat    = item.get("category", "featured")
        meta   = CAT_META.get(cat, CAT_META["featured"])
        title  = (item.get("title") or "").strip()
        teaser = (item.get("teaser") or item.get("description") or "").strip()
        pub    = (item.get("published") or item.get("pubDate") or today)[:10]
        src_url= item.get("url") or item.get("link") or ""
        src_dom= item.get("source") or item.get("source_domain") or ""
        slug   = make_slug(title, pub, cat)
        touched_slugs.add(slug)

        image_meta = pick_image(cat, slug, pools)
        body_html, word_count = build_article_body(title, teaser, slug, cat, src_dom)
        article = {
            "category":         cat,
            "cat_label":        meta["label"],
            "cat_icon":         meta["icon"],
            "cat_color":        meta["color"],
            "cat_page":         meta["page"],
            "title":            title,
            "slug":             slug,
            "dek":              teaser[:180] if teaser else title,
            "meta_description": teaser[:220] if teaser else title,
            "card_summary":     build_card_summary(title, teaser, cat, src_dom),
            "body_html":        body_html,
            "word_count":       word_count,
            "source_url":       src_url,
            "source_domain":    src_dom,
            "published":        pub,
            "story_rank":       item.get("score", 0),
            "analysis_level":   "local_editorial",
            "generated_by":     "rewrite_feed_local",
            **image_meta,
        }
        # preserve existing higher-quality human/editorial overrides when present
        old = existing_by_slug.get(slug, {})
        if old.get("is_editorial") or old.get("editorial"):
            article.update({k: old[k] for k in old.keys() if k not in {"story_rank"}})
        elif old:
            for k in ["card_summary", "body_html", "word_count", "generated_by", "quality_score", "needs_gemini"]:
                if old.get(k):
                    article[k] = old[k]
        fresh_articles.append(article)

    untouched_existing = [a for a in existing if a.get("slug") not in touched_slugs]
    merged = fresh_articles + untouched_existing
    merged.sort(key=lambda a: (a.get("published") or "", a.get("story_rank") or 0), reverse=True)
    merged = merged[:MAX_TOTAL_KEPT]

    with open(OUTPUT_F, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"✓ generated_articles.json: {len(merged)} total ({len(fresh_articles)} refreshed from latest RSS)")


if __name__ == "__main__":
    main()
