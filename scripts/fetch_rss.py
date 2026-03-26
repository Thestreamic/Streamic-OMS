#!/usr/bin/env python3
"""
The Streamic RSS Feed Aggregator
Fetches, parses, and aggregates broadcast technology news from multiple sources
"""

import feedparser
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote
import requests
from pathlib import Path

# ── Broadcast relevance filter ────────────────────────────────────────────────
_BROADCAST_KEYWORDS = [
    "broadcast", "streaming", "codec", "encoder", "decoder", "nab", "ibc",
    "ott", "cdn", "video", "audio", "production", "playout", "camera",
    "studio", "graphics", "newsroom", "mam", "pam", "nmos", "st 2110",
    "sdi", "ip workflow", "cloud production", "media", "television", "tv",
    "satellite", "transmission", "post-production", "editing", "vfx",
    "live event", "ingest", "workflow", "signal", "4k", "hdr", "hevc",
    "h.264", "h.265", "av1", "hls", "mpeg", "mxf", "srt", "rist", "ndi",
    "remote production", "remi", "ob van", "multiviewer", "intercom",
    "jpeg xs", "jpeg2000", "ip media", "media server", "channel", "network",
    "vendor", "nab show", "ibc show", "mediatech", "media tech", "vizrt",
    "evertz", "grass valley", "harmonic", "haivision", "telestream", "ateme",
    "bitmovin", "envivio", "aws media", "azure media", "cloud encode",
    "live ip", "ip broadcast", "media workflow", "broadcast technology",
    "media production", "post production", "color grade", "colour grade",
    "software-defined", "ip transition", "ip infrastructure", "media asset",
    "newscast", "tvbe", "tvbeurope", "svgeurope", "broadcastbeat",
]
_REJECT_KEYWORDS = [
    "led wall sleep", "retail led", "sleep study", "led display sleep",
    "fashion week", "luxury hotel", "real estate", "restaurant review",
    "fitness app", "health app", "cryptocurrency", "nft ", "web3 ",
    "gaming headset", "smart home", "wearable", "e-commerce",
]

def is_broadcast_item(title: str, description: str = "") -> bool:
    text = (title + " " + description).lower()
    if any(k in text for k in _REJECT_KEYWORDS):
        return False
    return any(k in text for k in _BROADCAST_KEYWORDS)

# ===== CONFIGURATION =====
CLOUDFLARE_WORKER = "https://broken-king-b4dc.itabmum.workers.dev"
DATA_DIR = Path("data")
OUTPUT_FILE = DATA_DIR / "news.json"
ARCHIVE_FILE = DATA_DIR / "archive.json"

MAX_ITEMS_PER_FEED = 8
FEED_FETCH_TIMEOUT = 12
ARTICLE_FETCH_TIMEOUT = 5
MAX_ARTICLE_FETCHES = 5
MIN_PER_CATEGORY = 6
MIN_REQUIRED_EACH = 2
MAX_NEWS_ITEMS = 120

DIRECT_FEEDS = [
    'https://www.tvtechnology.com/news/rss.xml',
    'https://www.broadcastbeat.com/feed/',
    'https://www.streamingmediablog.com/feed',
    'https://www.haivision.com/feed/',
    'https://blog.telestream.com/feed/',
    'https://www.harmonicinc.com/insights/blog/rss.xml',
    'https://jonnyelwyn.co.uk/feed/',
    'https://beforesandafters.com/feed/',
    'https://aws.amazon.com/blogs/media/feed/',
    'https://openrss.org/https://bitmovin.com/blog/',
]

CATEGORY_FEEDS = {
    'newsroom': [
        'https://www.tvtechnology.com/news/rss.xml',
        'https://www.broadcastbeat.com/feed/',
        'https://www.inbroadcast.com/rss.xml',
        'https://api.client.notified.com/api/rss/publish/view/47032?type=press',
        'https://www.rossvideo.com/news/feed/',
    ],
    'playout': [
        'https://www.tvtechnology.com/playout/rss.xml',
        'https://www.inbroadcast.com/rss.xml',
        'https://www.harmonicinc.com/insights/blog/rss.xml',
        'https://www.imaginecommunications.com/news/rss.xml',
    ],
    'infrastructure': [
        'https://www.tvtechnology.com/infrastructure/rss.xml',
        'https://www.haivision.com/feed/',
        'https://www.inbroadcast.com/rss.xml',
        'https://www.evertz.com/news/rss',
    ],
    'graphics': [
        'https://www.tvtechnology.com/graphics/rss.xml',
        'https://www.vizrt.com/news/rss',
        'https://motionographer.com/feed/',
    ],
    'cloud': [
        'https://www.tvtechnology.com/cloud/rss.xml',
        'https://aws.amazon.com/blogs/media/feed/',
        'https://openrss.org/https://bitmovin.com/blog/',
    ],
    'streaming': [
        'https://www.tvtechnology.com/streaming/rss.xml',
        'https://www.streamingmediablog.com/feed',
        'https://www.haivision.com/feed/',
        'https://blog.telestream.com/feed/',
    ],
    'ai-post-production': [
        'https://jonnyelwyn.co.uk/feed/',
        'https://beforesandafters.com/feed/',
        'https://blog.pond5.com/feed/',
        'https://aws.amazon.com/blogs/media/feed/',
    ],
}

# ===== HELPER FUNCTIONS =====
def fetch_feed_direct(feed_url: str):
    try:
        response = requests.get(feed_url, timeout=FEED_FETCH_TIMEOUT, headers={'User-Agent': 'Mozilla/5.0 (compatible; TheStreamic/1.0)'})
        return feedparser.parse(response.content) if response.status_code == 200 else None
    except Exception as e:
        print(f" ⚠ Error: {e}")
        return None

def fetch_feed_with_fallback(feed_url: str):
    return fetch_feed_direct(feed_url)

def extract_image_from_entry(entry):
    if hasattr(entry, 'media_content'):
        for media in entry.media_content:
            if media.get('url'): return media.get('url')
    if hasattr(entry, 'media_thumbnail'):
        for thumb in entry.media_thumbnail:
            if thumb.get('url'): return thumb.get('url')
    description = entry.get('description', '') or entry.get('summary', '')
    if description:
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description, re.IGNORECASE)
        if m: return m.group(1)
    return None

def extract_og_image(article_url: str):
    try:
        r = requests.get(article_url, timeout=ARTICLE_FETCH_TIMEOUT, headers={'User-Agent': 'TheStreamic/1.0'})
        if r.status_code != 200: return None
        html = r.text[:80000]
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        return m.group(1) if m else None
    except: return None

def process_entries(entries, category, source_name):
    items = []
    for entry in entries:
        try:
            title = (entry.get('title') or '').strip()
            link = (entry.get('link') or '').strip()
            if not title or not link: continue
            
            image = extract_image_from_entry(entry)
            pub_date = datetime.now(timezone.utc).isoformat()
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()

            items.append({
                'title': title, 'link': link, 'guid': entry.get('id', link),
                'category': category, 'source': source_name, 'image': image,
                'pubDate': pub_date, 'timestamp': int(time.time())
            })
        except: continue
    return items

def get_source_name(feed_url: str) -> str:
    u = feed_url.lower()
    if 'tvtechnology' in u: return 'TV Technology'
    if 'broadcastbeat' in u: return 'BroadcastBeat'
    if 'haivision' in u: return 'Haivision'
    if 'telestream' in u: return 'Telestream'
    if 'aws.amazon' in u: return 'AWS'
    if 'bitmovin' in u: return 'Bitmovin'
    return 'Industry News'

def deduplicate_by_guid(items):
    seen, out = set(), []
    for it in items:
        g = it.get('guid') or it.get('link')
        if g not in seen:
            seen.add(g)
            out.append(it)
    return out

def balance_categories(all_items):
    all_items = deduplicate_by_guid(all_items)
    by_cat = {}
    for it in all_items:
        by_cat.setdefault(it['category'], []).append(it)
    
    balanced = []
    for cat, lst in by_cat.items():
        lst.sort(key=lambda x: x.get('pubDate', ''), reverse=True)
        balanced.extend(lst[:MIN_PER_CATEGORY])
    
    balanced.sort(key=lambda x: x.get('pubDate', ''), reverse=True)
    return balanced[:MAX_NEWS_ITEMS]

def validate_news_data(items):
    return True

def save_json_atomically(data, filepath: Path):
    tmp = filepath.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(filepath)

def main():
    print("🚀 Starting The Streamic RSS Aggregator")
    all_items = []

    # FIX: Correct dictionary name used here
    for category, feed_urls in CATEGORY_FEEDS.items():
        print(f"\n📰 Processing {category.upper()} ({len(feed_urls)} feeds)")
        
        for feed_url in feed_urls:
            try:
                feed = fetch_feed_with_fallback(feed_url)
                if not feed or not hasattr(feed, 'entries') or not feed.entries:
                    continue

                entries = feed.entries[:MAX_ITEMS_PER_FEED]
                source_name = get_source_name(feed_url)
                items = process_entries(entries, category, source_name)
                
                broadcast_items = [
                    it for it in items 
                    if is_broadcast_item(it.get("title",""), it.get("teaser",""))
                ]
                all_items.extend(broadcast_items)
                print(f" ✓ {source_name}: {len(broadcast_items)} items")

            except Exception as e:
                print(f" ✗ Error: {e}")
                continue

    # INDENTATION FIX: These lines align with the 'for' loop above
    print(f"\n📦 Total items collected: {len(all_items)}")
    
    if not all_items:
        print("❌ No items collected. Exiting.")
        return

    balanced_items = balance_categories(all_items)
    
    if OUTPUT_FILE.exists():
        if ARCHIVE_FILE.exists(): ARCHIVE_FILE.unlink()
        OUTPUT_FILE.rename(ARCHIVE_FILE)

    save_json_atomically(balanced_items, OUTPUT_FILE)
    print(f"✅ Saved {len(balanced_items)} items to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
