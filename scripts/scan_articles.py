"""
scripts/scan_articles.py — Rebuild data/generated_articles.json from hand-authored HTML.

Workflow:
  1. Upload article HTML to docs/articles/<slug>.html (must carry <!-- HAND_AUTHORED -->)
  2. Upload image to docs/assets/articles/<filename>
  3. Commit — GitHub Actions runs: scan_articles.py → build.py → deploy

This script replaces the old RSS/AI generation pipeline. It:
  - Scans docs/articles/ for every *.html file
  - Only picks files with the <!-- HAND_AUTHORED --> marker on top
  - Extracts title, dek, date, image, category, body from each file
  - Writes data/generated_articles.json for build.py to consume

build.py already skips HTML regeneration for HAND_AUTHORED files, so your
uploaded HTML is never overwritten. This scanner only refreshes the JSON
index so build.py's homepage ("Latest Insights") picks up new articles.

Requirements:
  - Python 3.8+ (stdlib only — no pip installs)
  - HTML files follow the pattern produced by build.py's article_page()
"""
import json
import os
import re
import sys
from datetime import datetime
from html.parser import HTMLParser

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT     = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARTS_D   = os.path.join(ROOT, "docs", "articles")
DATA_D   = os.path.join(ROOT, "data")
JSON_OUT = os.path.join(DATA_D, "generated_articles.json")

# ── Valid categories (must match CAT dict in build.py) ────────────────────
VALID_CATS = {
    "featured", "streaming", "cloud", "graphics", "playout",
    "infrastructure", "ai-post-production", "newsroom",
}
DEFAULT_CAT = "infrastructure"

# ── Category inference map ────────────────────────────────────────────────
# Maps breadcrumb link filenames back to category slugs.
# e.g. "infrastructure.html" → "infrastructure", "ai-post-production.html"
# → "ai-post-production". Keeps the scanner resilient if the HTML uses
# a category page link instead of a data-category body attribute.
CAT_FROM_LINK = {
    "featured.html":            "featured",
    "streaming.html":           "streaming",
    "cloud.html":               "cloud",
    "graphics.html":            "graphics",
    "playout.html":             "playout",
    "infrastructure.html":      "infrastructure",
    "ai-post-production.html":  "ai-post-production",
    "newsroom.html":            "newsroom",
}


class ArticleExtractor(HTMLParser):
    """Walks the article HTML once and pulls every field we need."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        # Output fields
        self.title = ""
        self.dek = ""
        self.meta_desc = ""
        self.published = ""
        self.image_url = ""
        self.category = ""
        self.body_parts = []

        # State flags
        self._in_art_wrap = False
        self._art_wrap_depth = 0
        self._in_h1 = False
        self._in_art_dek = False
        self._in_art_body = False
        self._art_body_depth = 0
        self._in_breadcrumb = False
        self._breadcrumb_depth = 0
        self._first_img_captured = False
        self._first_time_captured = False
        self._current_tag_stack = []

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _attr(attrs, name):
        for k, v in attrs:
            if k == name:
                return v or ""
        return ""

    # ── tag handlers ─────────────────────────────────────────────────────
    def handle_starttag(self, tag, attrs):
        self._current_tag_stack.append(tag)

        # <meta name="description" content="...">
        if tag == "meta":
            if self._attr(attrs, "name") == "description":
                self.meta_desc = self._attr(attrs, "content").strip()
            return

        # Body class holds data-category (if build.py wrote it)
        if tag == "body":
            dc = self._attr(attrs, "data-category")
            if dc and dc in VALID_CATS:
                self.category = dc
            return

        cls = self._attr(attrs, "class")

        # Enter .art-wrap — everything we care about is inside this block
        if tag == "div" and "art-wrap" in cls.split():
            self._in_art_wrap = True
            self._art_wrap_depth = 1
            return

        if self._in_art_wrap:
            # Track nested div depth so we know when art-wrap closes
            if tag == "div":
                self._art_wrap_depth += 1

            # Enter the .art-breadcrumb div — category inference happens
            # ONLY inside this block. It sits right after <main> and contains
            # "Home → Category" links. Restricting to this block avoids
            # false positives from the footer's category index links later.
            if tag == "div" and "art-breadcrumb" in cls.split():
                self._in_breadcrumb = True
                self._breadcrumb_depth = 1
                return

            # Track nested divs inside breadcrumb (rare but safe)
            if tag == "div" and self._in_breadcrumb:
                self._breadcrumb_depth += 1

            # <a> inside breadcrumb — use href to infer category. Skip the
            # homepage link (featured.html) — the real category is the
            # second link.
            if tag == "a" and self._in_breadcrumb:
                href = self._attr(attrs, "href")
                if href:
                    fn = href.split("/")[-1].split("?")[0].split("#")[0]
                    if fn in CAT_FROM_LINK and fn != "featured.html":
                        self.category = CAT_FROM_LINK[fn]

            # <h1> — article title
            if tag == "h1":
                self._in_h1 = True
                return

            # <p class="art-dek"> — article description
            if tag == "p" and "art-dek" in cls.split():
                self._in_art_dek = True
                return

            # <time datetime="..."> — first one wins
            if tag == "time" and not self._first_time_captured:
                dt = self._attr(attrs, "datetime")
                if dt:
                    self.published = dt.strip()[:10]
                    self._first_time_captured = True
                return

            # First <img> inside a <figure> — article hero image
            if tag == "img" and not self._first_img_captured:
                # Only accept if we're currently inside a <figure>
                if "figure" in self._current_tag_stack:
                    src = self._attr(attrs, "src")
                    if src:
                        self.image_url = self._normalise_img(src)
                        self._first_img_captured = True
                return

            # Enter .art-body — article HTML body
            if tag == "div" and "art-body" in cls.split():
                self._in_art_body = True
                self._art_body_depth = 1
                return

            # Capture every tag inside .art-body verbatim
            if self._in_art_body:
                if tag == "div":
                    self._art_body_depth += 1
                # Re-serialise the tag with its attributes preserved
                attr_str = "".join(f' {k}="{v}"' for k, v in attrs if v is not None)
                self.body_parts.append(f"<{tag}{attr_str}>")

    def handle_endtag(self, tag):
        if self._current_tag_stack and self._current_tag_stack[-1] == tag:
            self._current_tag_stack.pop()

        if self._in_art_body:
            if tag == "div":
                self._art_body_depth -= 1
                if self._art_body_depth == 0:
                    self._in_art_body = False
                    return
            # Capture closing tag verbatim (except the art-body wrapper)
            self.body_parts.append(f"</{tag}>")
            return

        if tag == "h1":
            self._in_h1 = False
        elif tag == "p" and self._in_art_dek:
            self._in_art_dek = False
        elif tag == "div":
            # Close breadcrumb first (inner block)
            if self._in_breadcrumb:
                self._breadcrumb_depth -= 1
                if self._breadcrumb_depth == 0:
                    self._in_breadcrumb = False
                    return
            if self._in_art_wrap:
                self._art_wrap_depth -= 1
                if self._art_wrap_depth == 0:
                    self._in_art_wrap = False

    def handle_startendtag(self, tag, attrs):
        # Handles self-closing tags like <img />
        self.handle_starttag(tag, attrs)
        # Don't fake an endtag for void elements; HTMLParser will do the right thing

    def handle_data(self, data):
        if self._in_h1 and not self.title:
            # Collect title text (may span multiple chunks)
            pass
        if self._in_h1:
            self.title += data
        elif self._in_art_dek:
            self.dek += data
        elif self._in_art_body:
            self.body_parts.append(data)

    # ── post-processing ──────────────────────────────────────────────────
    @staticmethod
    def _normalise_img(src):
        """Turn ../assets/foo.png / assets/foo.png / /assets/foo.png → /assets/foo.png
        Leaves http(s)://... untouched."""
        s = src.strip()
        if s.startswith("http://") or s.startswith("https://"):
            return s
        # Strip leading ../ segments
        while s.startswith("../"):
            s = s[3:]
        if not s.startswith("/"):
            s = "/" + s
        return s

    def finalise(self):
        """Return the extracted dict, with text fields cleaned up."""
        return {
            "title":       re.sub(r"\s+", " ", self.title).strip(),
            "dek":         re.sub(r"\s+", " ", self.dek).strip(),
            "meta_desc":   self.meta_desc,
            "published":   self.published,
            "image_url":   self.image_url,
            "category":    self.category if self.category in VALID_CATS else DEFAULT_CAT,
            "body_html":   "".join(self.body_parts).strip(),
        }


def scan_article(path):
    """Extract one article's metadata. Returns dict or None if unsuitable."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    # Only hand-authored files participate
    if "<!-- HAND_AUTHORED -->" not in raw:
        return None

    slug = os.path.splitext(os.path.basename(path))[0]

    # Skip how-to guide article pages — they have their own section on the site
    # (docs/howto.html) and build.py writes them from HOWTO_GUIDE_CONTENT
    # already. Including them in Latest Insights would double-list them.
    if slug.startswith("guide-"):
        return None

    parser = ArticleExtractor()
    try:
        parser.feed(raw)
    except Exception as e:
        print(f"  ⚠ parse error in {slug}: {e}", file=sys.stderr)
        return None

    data = parser.finalise()

    # Hard requirements — skip the file if any are missing
    if not data["title"]:
        print(f"  ⚠ {slug}: no <h1> title found, skipping", file=sys.stderr)
        return None
    if not data["published"]:
        # Fall back to file mtime date if no <time> tag found
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        data["published"] = mtime.strftime("%Y-%m-%d")
        print(f"  ℹ {slug}: no <time> tag, using file mtime {data['published']}")

    # Compute word count from plain body
    plain = re.sub(r"<[^>]+>", " ", data["body_html"])
    plain = re.sub(r"\s+", " ", plain).strip()
    word_count = len(plain.split())

    # Source domain for the news-card footer — always "The Streamic"
    # for hand-authored pieces
    source_domain = "thestreamic.in"

    # Card summary: reuse dek or meta description, capped at ~160 chars
    card_summary = (data["dek"] or data["meta_desc"] or "").strip()

    return {
        "slug":              slug,
        "title":             data["title"],
        "dek":               data["dek"],
        "card_summary":      card_summary,
        "meta_description":  data["meta_desc"] or data["dek"],
        "published":         data["published"],
        "category":          data["category"],
        "image_url":         data["image_url"],
        "source_url":        "",          # hand-authored has no external source
        "source_domain":     source_domain,
        "is_editorial":      True,
        "editorial":         True,        # legacy alias used in build.py
        "generated_by":      "gpt_manual_editorial",  # bypasses word-count gate
        "body_html":         data["body_html"],
        "word_count":        word_count,
        "quality_score":     90,          # hand-authored ⇒ always high quality
    }


def main():
    if not os.path.isdir(ARTS_D):
        print(f"✗ articles directory not found: {ARTS_D}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(DATA_D, exist_ok=True)

    articles = []
    skipped_no_marker = 0
    skipped_guides = 0

    for fn in sorted(os.listdir(ARTS_D)):
        if not fn.endswith(".html"):
            continue
        path = os.path.join(ARTS_D, fn)

        with open(path, "r", encoding="utf-8") as f:
            head_sample = f.read(400)
        if "<!-- HAND_AUTHORED -->" not in head_sample:
            skipped_no_marker += 1
            continue
        if fn.startswith("guide-"):
            skipped_guides += 1
            continue

        record = scan_article(path)
        if record:
            articles.append(record)
            print(f"  ✓ {record['slug']}  ({record['category']}, {record['word_count']}w, {record['published']})")

    # Sort newest first
    articles.sort(key=lambda a: a["published"], reverse=True)

    # Preserve any existing file before overwriting (belt-and-braces backup)
    if os.path.exists(JSON_OUT):
        bak = JSON_OUT + ".bak"
        try:
            with open(JSON_OUT, "r", encoding="utf-8") as src, \
                 open(bak, "w", encoding="utf-8") as dst:
                dst.write(src.read())
        except Exception:
            pass  # backup is best-effort

    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    print()
    print(f"📝 Wrote {len(articles)} articles → {os.path.relpath(JSON_OUT, ROOT)}")
    if skipped_no_marker:
        print(f"   (skipped {skipped_no_marker} files without HAND_AUTHORED marker)")
    if skipped_guides:
        print(f"   (skipped {skipped_guides} how-to guide files — they live on howto.html)")


if __name__ == "__main__":
    main()
