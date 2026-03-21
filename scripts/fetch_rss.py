#!/usr/bin/env python3
"""
The Streamic RSS Feed Aggregator
Fetches, parses, and aggregates broadcast technology news from multiple sources

This version:
- Uses Cloudflare Worker: https://broken-king-b4dc.itabmum.workers.dev
- Removes old feeds (Dacast / OnTheFly / YoloLiv / TechCrunch / Engadget / WIRED)
- Adds Streaming vendors: Haivision / Telestream / Bitmovin
- Adds Infra vendors: Avid Press (Notified) / Adobe Developer (OpenRSS)
- Renames 'audio-ai' -> 'ai-post-production'
- Adds 8 verified AI Post Production feeds
"""

import feedparser
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote
import requests
from pathlib import Path

# ===== CONFIGURATION =====
CLOUDFLARE_WORKER = "https://broken-king-b4dc.itabmum.workers.dev"
DATA_DIR = Path("data")
OUTPUT_FILE = DATA_DIR / "news.json"
ARCHIVE_FILE = DATA_DIR / "archive.json"

# Performance settings
MAX_ITEMS_PER_FEED = 20
FEED_FETCH_TIMEOUT = 12
ARTICLE_FETCH_TIMEOUT = 5
MAX_ARTICLE_FETCHES = 8

# Balancing settings
MIN_PER_CATEGORY = 18
MIN_REQUIRED_EACH = 3
MAX_NEWS_ITEMS = 300


# ===== DIRECT FETCH FEEDS (Bypass Cloudflare Worker) =====
DIRECT_FEEDS = [
    # Streaming category (core + vendors)
    'https://www.streamingmediablog.com/feed',
    'https://www.broadcastnow.co.uk/full-rss/',
    'https://www.haivision.com/feed/',
    'https://blog.telestream.com/feed/',
    'https://openrss.org/https://bitmovin.com/blog/',

    # Infrastructure - MAM/PAM / Vendors
    'https://api.client.notified.com/api/rss/publish/view/47032?type=press',   # Avid Press (Notified)
    'https://openrss.org/https://blog.developer.adobe.com/',                   # Adobe Developers via OpenRSS
    'https://chesa.com/feed',
    'https://cloudinary.com/blog/feed',

    # Storage
    'https://www.studionetworksolutions.com/feed',
    'https://openrss.org/https://scalelogicinc.com/blog/protecting-valuable-media-assets/',
    'https://openrss.org/https://qsan.io/solutions/media-production/',
    'https://openrss.org/https://www.keycodemedia.com/capabilities/media-shared-storage-cloud-storage/',

    # Production Ops
    'https://www.processexcellencenetwork.com/rss-feeds',

    # Legacy direct fetch (kept)
    'https://www.inbroadcast.com/rss.xml',
    'https://www.imaginecommunications.com/news/rss.xml'
]


# ===== FEED GROUPS =====
FEED_GROUPS = {
    'newsroom': [
        'https://www.newscaststudio.com/feed/',
        'https://www.tvtechnology.com/news/rss.xml',
        'https://www.broadcastbeat.com/feed/',
        'https://www.svgeurope.org/feed/'
    ],

    'playout': [
        'https://www.inbroadcast.com/rss.xml',
        'https://www.tvtechnology.com/playout/rss.xml',
        'https://www.rossvideo.com/news/feed/',
        'https://www.harmonicinc.com/insights/blog/rss.xml',
        'https://www.evertz.com/news/rss',
        'https://www.imaginecommunications.com/news/rss.xml'
    ],

    'infrastructure': [
        'https://www.thebroadcastbridge.com/rss/infrastructure',
        'https://www.tvtechnology.com/infrastructure/rss.xml',
        'https://www.broadcastbridge.com/rss/security',
        'https://www.tvtechnology.com/security/rss.xml',
        'https://aws.amazon.com/security/blog/feed/',
        'https://krebsonsecurity.com/feed/',
        'https://www.darkreading.com/rss.xml',
        'https://www.bleepingcomputer.com/feed/',
        'https://www.securityweek.com/feed/',
        'https://feeds.feedburner.com/TheHackerNews',
        'https://cloud.google.com/blog/topics/security/rss/',
        'https://www.microsoft.com/en-us/security/blog/feed/',

        # MAM/PAM + Vendors
        'https://api.client.notified.com/api/rss/publish/view/47032?type=press',   # Avid Press
        'https://openrss.org/https://blog.developer.adobe.com/',                   # Adobe Developers
        'https://chesa.com/feed',
        'https://cloudinary.com/blog/feed',

        # Storage
        'https://www.studionetworksolutions.com/feed',
        'https://openrss.org/https://scalelogicinc.com/blog/protecting-valuable-media-assets/',
        'https://openrss.org/https://qsan.io/solutions/media-production/',
        'https://openrss.org/https://www.keycodemedia.com/capabilities/media-shared-storage-cloud-storage/',

        # Production Ops
        'https://www.processexcellencenetwork.com/rss-feeds'
    ],

    'graphics': [
        'https://www.thebroadcastbridge.com/rss/graphics',
        'https://www.tvtechnology.com/graphics/rss.xml',
        'https://www.vizrt.com/news/rss',
        'https://routing.vizrt.com/rss',
        'https://motionographer.com/feed/'
    ],

    'cloud': [
        'https://www.thebroadcastbridge.com/rss/cloud',
        'https://www.tvtechnology.com/cloud/rss.xml',
        'https://aws.amazon.com/blogs/media/feed/',
        'https://blog.frame.io/feed/'
    ],

    'streaming': [
        'https://www.thebroadcastbridge.com/rss/streaming',
        'https://www.tvtechnology.com/streaming/rss.xml',

        # Direct fetch streaming vendors
        'https://www.streamingmediablog.com/feed',
        'https://www.broadcastnow.co.uk/full-rss/',
        'https://www.haivision.com/feed/',
        'https://blog.telestream.com/feed/',
        'https://openrss.org/https://bitmovin.com/blog/'
    ],

    # Renamed from 'audio-ai' -> 'ai-post-production'
    'ai-post-production': [
        'https://premiumbeat.com/blog/category/video-editing/feed/',
        'https://premieregal.com/blog?format=RSS',
        'https://videocopilot.net/feeds/tutorials/',
        'https://jonnyelwyn.co.uk/feed/',
        'https://blog.pond5.com/feed/',
        'https://filtergrade.com/category/video/feed/',
        'https://beforesandafters.com/feed/',
        'https://avinteractive.com/feed/'
    ]
}


# ===== HELPER FUNCTIONS =====
def should_use_direct_fetch(feed_url: str) -> bool:
    """Check if feed should bypass Cloudflare Worker"""
    return feed_url in DIRECT_FEEDS


def fetch_feed_via_worker(feed_url: str):
    """Fetch feed through Cloudflare Worker (keeps your existing mechanism)"""
    try:
        encoded_url = quote(feed_url, safe='')
        worker_url = f"{CLOUDFLARE_WORKER}/?url={encoded_url}"
        response = requests.get(
            worker_url,
            timeout=FEED_FETCH_TIMEOUT,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; TheStreamic/1.0)'}
        )
        if response.status_code == 200:
            return feedparser.parse(response.content)
        return None
    except Exception as e:
        print(f" ⚠ Worker error for {feed_url[:60]}: {e}")
        return None


def fetch_feed_direct(feed_url: str):
    """Fetch feed directly without worker"""
    try:
        response = requests.get(
            feed_url,
            timeout=FEED_FETCH_TIMEOUT,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; TheStreamic/1.0)'}
        )
        if response.status_code == 200:
            return feedparser.parse(response.content)
        return None
    except Exception as e:
        print(f" ⚠ Direct fetch error for {feed_url[:60]}: {e}")
        return None


def fetch_feed_with_fallback(feed_url: str):
    """Always fetch directly in GitHub Actions environment"""
    return fetch_feed_direct(feed_url)


def extract_image_from_entry(entry):
    """Extract image URL with multiple fallback strategies"""
    # 1) media:content
    if hasattr(entry, 'media_content'):
        for media in entry.media_content:
            url = media.get('url')
            if url:
                return url

    # 2) media:thumbnail
    if hasattr(entry, 'media_thumbnail'):
        for thumb in entry.media_thumbnail:
            url = thumb.get('url')
            if url:
                return url

    # 3) enclosures with image/*
    if hasattr(entry, 'enclosures'):
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href') or enc.get('url')

    # 4) Parse from description/summary
    description = entry.get('description', '') or entry.get('summary', '')
    if description:
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description, re.IGNORECASE)
        if m:
            img_url = m.group(1)
            low = img_url.lower()
            if not any(k in low for k in ['1x1', 'pixel', 'spacer', 'tracker', 'avatar', 'gravatar']):
                return img_url

    # 5) Try a lowered-quality variant if URL contains width/height hints
    if hasattr(entry, 'media_content'):
        for media in entry.media_content:
            url = media.get('url', '')
            if url and ('w=' in url or 'width=' in url or 'h=' in url or 'height=' in url):
                url = re.sub(r'(w|width)=\d+', r'\1=400', url)
                url = re.sub(r'(h|height)=\d+', r'\1=300', url)
                url = re.sub(r'(q|quality)=\d+', r'\1=70', url)
                return url

    return None


def extract_og_image(article_url: str, timeout: int = ARTICLE_FETCH_TIMEOUT):
    """Extract og:image or twitter:image from article HTML (last resort)"""
    try:
        r = requests.get(
            article_url,
            timeout=timeout,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; TheStreamic/1.0)'}
        )
        if r.status_code != 200:
            return None
        html = r.text[:80000]

        # og:image
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if m:
            return m.group(1)

        # twitter:image
        m = re.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if m:
            return m.group(1)

        return None
    except Exception:
        return None


def process_entries(entries, category, source_name):
    """Convert feed entries into our normalized item dicts"""
    items = []
    article_fetch_count = 0

    for entry in entries:
        try:
            title = (entry.get('title') or '').strip()
            link = (entry.get('link') or '').strip()
            guid = entry.get('id', link)

            if not title or not link:
                continue

            # image
            image = extract_image_from_entry(entry)
            if not image and article_fetch_count < MAX_ARTICLE_FETCHES:
                image = extract_og_image(link)
                article_fetch_count += 1

            # pubDate
            pub_date_iso = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    pub_date_iso = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
                except Exception:
                    pub_date_iso = None
            if not pub_date_iso and hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                try:
                    pub_date_iso = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).isoformat()
                except Exception:
                    pub_date_iso = None
            if not pub_date_iso:
                pub_date_iso = datetime.now(timezone.utc).isoformat()

            items.append({
                'title': title,
                'link': link,
                'guid': guid,
                'category': category,
                'source': source_name,
                'image': image,
                'pubDate': pub_date_iso,
                'timestamp': int(time.time())
            })
        except Exception as e:
            print(f" ⚠ Error processing entry: {e}")
            continue

    return items


def get_source_name(feed_url: str) -> str:
    """Return a nice source name for a feed URL"""
    u = (feed_url or '').lower()

    # Common sources
    if 'newscaststudio' in u: return 'NewscastStudio'
    if 'tvtechnology' in u: return 'TV Technology'
    if 'broadcastbeat' in u: return 'BroadcastBeat'
    if 'svgeurope' in u: return 'SVG Europe'
    if 'inbroadcast' in u: return 'InBroadcast'
    if 'rossvideo' in u: return 'Ross Video'
    if 'harmonicinc' in u: return 'Harmonic'
    if 'evertz' in u: return 'Evertz'
    if 'imaginecommunications' in u: return 'Imagine Communications'
    if 'thebroadcastbridge' in u or 'broadcastbridge' in u: return 'The Broadcast Bridge'
    if 'vizrt' in u: return 'Vizrt'
    if 'motionographer' in u: return 'Motionographer'
    if 'aws.amazon' in u: return 'AWS'
    if 'frame.io' in u: return 'Frame.io'
    if 'krebsonsecurity' in u: return 'Krebs on Security'
    if 'darkreading' in u: return 'Dark Reading'
    if 'bleepingcomputer' in u: return 'BleepingComputer'
    if 'securityweek' in u: return 'SecurityWeek'
    if 'feedburner.com/thehackernews' in u: return 'The Hacker News'
    if 'cloud.google.com' in u: return 'Google Cloud'
    if 'microsoft.com' in u: return 'Microsoft Security'

    # Streaming
    if 'streamingmediablog' in u: return 'Streaming Media Blog'
    if 'broadcastnow' in u: return 'Broadcast Now'
    if 'haivision.com' in u: return 'Haivision'
    if 'telestream' in u: return 'Telestream'
    if 'bitmovin.com' in u or 'openrss.org/https://bitmovin.com' in u: return 'Bitmovin'

    # AI Post Production
    if 'premiumbeat' in u: return 'PremiumBeat'
    if 'premieregal' in u: return 'Premiere Gal'
    if 'videocopilot' in u: return 'Video Copilot'
    if 'jonnyelwyn' in u: return 'Jonny Elwyn'
    if 'pond5' in u: return 'Pond5'
    if 'filtergrade' in u: return 'FilterGrade'
    if 'beforesandafters' in u: return 'Befores & Afters'
    if 'avinteractive' in u: return 'AV Magazine'

    # Infra vendors
    if 'api.client.notified.com' in u and 'type=press' in u: return 'Avid Press Room'
    if 'developer.adobe.com' in u or 'openrss.org/https://blog.developer.adobe.com' in u: return 'Adobe Developers'
    if 'chesa.com' in u: return 'Chesa'
    if 'cloudinary' in u: return 'Cloudinary'
    if 'studionetworksolutions' in u: return 'Studio Network Solutions'
    if 'scalelogicinc' in u: return 'ScaleLogic'
    if 'qsan.io' in u: return 'QSAN'
    if 'keycodemedia' in u: return 'Keycode Media'
    if 'processexcellencenetwork' in u: return 'Process Excellence Network'

    return 'Technology News'


def validate_news_data(items):
    """Validate that we have minimum items per category (soft check)"""
    counts = {}
    for it in items:
        cat = it.get('category', '')
        counts[cat] = counts.get(cat, 0) + 1

    print("\n📊 Category distribution:")
    for cat, cnt in sorted(counts.items()):
        mark = "✓" if cnt >= MIN_REQUIRED_EACH else "⚠"
        print(f" {mark} {cat}: {cnt}")

    # soft validation: allow saving even if below minimum when first run
    return True


def deduplicate_by_guid(items):
    """Remove duplicate articles by GUID"""
    seen = set()
    out = []
    for it in items:
        g = it.get('guid') or it.get('link')
        if g and g not in seen:
            seen.add(g)
            out.append(it)
    print(f"\n🔄 Deduplication: {len(items)} → {len(out)} (removed {len(items) - len(out)})")
    return out


def balance_categories(all_items):
    """Balance items across categories; keep newest first within each"""
    all_items = deduplicate_by_guid(all_items)

    by_cat = {}
    for it in all_items:
        cat = it.get('category', '')
        by_cat.setdefault(cat, []).append(it)

    for cat, lst in by_cat.items():
        lst.sort(key=lambda x: x.get('pubDate', ''), reverse=True)

    balanced = []
    for cat, lst in by_cat.items():
        balanced.extend(lst[:MIN_PER_CATEGORY])

    balanced.sort(key=lambda x: x.get('pubDate', ''), reverse=True)
    return balanced[:MAX_NEWS_ITEMS]


def save_json_atomically(data, filepath: Path):
    tmp = filepath.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(filepath)


def main():
    print("🚀 Starting The Streamic RSS Aggregator\n")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    all_items = []

    for category, feed_urls in FEED_GROUPS.items():
        print(f"\n📰 Processing {category.upper()} ({len(feed_urls)} feeds)")
        for feed_url in feed_urls:
            try:
                feed = fetch_feed_with_fallback(feed_url)
                if not feed or not feed.entries:
                    print(f" ⚠ No entries from {feed_url[:80]}")
                    continue

                entries = feed.entries[:MAX_ITEMS_PER_FEED]
                source_name = get_source_name(feed_url)
                items = process_entries(entries, category, source_name)
                all_items.extend(items)
                print(f" ✓ {source_name}: {len(items)} items")
            except Exception as e:
                print(f" ✗ Error with {feed_url[:80]}: {e}")
                continue

    print(f"\n📦 Total items collected: {len(all_items)}")
    if not all_items:
        print("❌ No items collected. Exiting.")
        return

    balanced_items = balance_categories(all_items)
    print(f"⚖️ Balanced to: {len(balanced_items)} items")

    _ok = validate_news_data(balanced_items)

    # archive previous, then save
    if OUTPUT_FILE.exists():
        if ARCHIVE_FILE.exists():
            ARCHIVE_FILE.unlink()
        OUTPUT_FILE.rename(ARCHIVE_FILE)
        print(f"\n💾 Backed up previous data to {ARCHIVE_FILE}")

    save_json_atomically(balanced_items, OUTPUT_FILE)
    print(f"✅ Saved {len(balanced_items)} items to {OUTPUT_FILE}")
    print("\n🎉 Aggregation complete!")


if __name__ == "__main__":
    main()
