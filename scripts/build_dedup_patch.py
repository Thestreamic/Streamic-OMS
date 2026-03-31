#!/usr/bin/env python3
"""
build_dedup_patch.py  —  The Streamic
====================================================
PASTE THIS DEDUPLICATION HELPER INTO YOUR build.py
====================================================

The duplicate problem: both the main "Latest Broadcast & Media Technology News"
section AND the right-sidebar "Top Broadcast & Media Technology Stories" section
pull from the same generated_articles.json without tracking which slugs have
already been rendered. Result: same article appears in both columns.

FIX: add a shared SlugTracker and pass it to both section builders.

──────────────────────────────────────────────────
HOW TO APPLY
──────────────────────────────────────────────────
1. Open scripts/build.py
2. Add the SlugTracker class near the top (after imports)
3. In whatever function builds the index/homepage, instantiate ONE tracker:
       tracker = SlugTracker()
4. Pass tracker to the section that renders first (main feed):
       main_feed_html   = build_main_feed(articles, tracker)
5. Pass the SAME tracker to the sidebar section:
       sidebar_html     = build_sidebar_stories(articles, tracker)
6. Inside each section builder, call tracker.use(slug) for each article rendered,
   and call tracker.already_used(slug) to skip duplicates.

See the example functions below.
"""

# ── Paste this class into build.py ──────────────────────────────────────────

class SlugTracker:
    """Tracks which article slugs have been rendered to prevent cross-section duplicates."""

    def __init__(self):
        self._used: set[str] = set()

    def already_used(self, slug: str) -> bool:
        return slug in self._used

    def use(self, slug: str) -> None:
        self._used.add(slug)

    def available(self, articles: list, limit: int = None) -> list:
        """Return articles not yet rendered, up to optional limit."""
        result = [a for a in articles if not self.already_used(a.get("slug", ""))]
        return result[:limit] if limit else result


# ── Example: how to wire it into your section builders ──────────────────────

def example_build_main_feed(articles: list, tracker: "SlugTracker", limit: int = 10) -> str:
    """
    Example main feed builder — returns HTML string.
    Replace this with your actual build logic; the key additions are:
      - tracker.already_used(slug) check before rendering
      - tracker.use(slug) after rendering
    """
    html_parts = []
    count = 0
    for article in articles:
        if count >= limit:
            break
        slug = article.get("slug", "")
        if tracker.already_used(slug):
            continue

        # ... your existing article card HTML generation here ...
        title = article.get("title", "")
        html_parts.append(f"<!-- main feed item: {slug} -->")

        tracker.use(slug)   # ← mark as rendered
        count += 1

    return "\n".join(html_parts)


def example_build_sidebar_stories(articles: list, tracker: "SlugTracker", limit: int = 8) -> str:
    """
    Example sidebar builder.
    Only articles NOT already in the main feed will appear here.
    """
    html_parts = []
    count = 0
    for article in articles:
        if count >= limit:
            break
        slug = article.get("slug", "")
        if tracker.already_used(slug):
            continue   # ← skip — already shown in main feed

        # ... your existing sidebar card HTML generation here ...
        title = article.get("title", "")
        html_parts.append(f"<!-- sidebar item: {slug} -->")

        tracker.use(slug)
        count += 1

    return "\n".join(html_parts)


def example_homepage_builder(articles: list) -> str:
    """
    Example top-level homepage builder showing full wiring.
    """
    tracker = SlugTracker()   # ← ONE tracker shared by all sections

    # Build sections in ORDER (main feed first, sidebar second)
    hero_html    = "<!-- hero -->"
    feed_html    = example_build_main_feed(articles, tracker, limit=10)
    sidebar_html = example_build_sidebar_stories(articles, tracker, limit=8)

    return f"{hero_html}\n{feed_html}\n{sidebar_html}"


# ── Quick self-test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_articles = [
        {"slug": "article-a", "title": "Article A"},
        {"slug": "article-b", "title": "Article B"},
        {"slug": "article-a", "title": "Article A (duplicate)"},
        {"slug": "article-c", "title": "Article C"},
    ]
    tracker = SlugTracker()

    # Simulate main feed taking A and B
    tracker.use("article-a")
    tracker.use("article-b")

    # Sidebar should only get C, not A or B
    available = tracker.available(test_articles)
    assert len(available) == 1
    assert available[0]["slug"] == "article-c"
    print("✓ SlugTracker deduplication test passed")
    print(f"  Available for sidebar: {[a['slug'] for a in available]}")
