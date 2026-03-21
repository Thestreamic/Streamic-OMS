/**
 * THE STREAMIC — scripts/generate.js
 * ════════════════════════════════════════════════════════════════
 * Full Groq-assisted article generator.
 * ════════════════════════════════════════════════════════════════
 */

'use strict';

const fs          = require('fs');
const path        = require('path');
const https       = require('https');
const { URL }     = require('url');

// ── CONFIG ────────────────────────────────────────────────────────────────
// Ensure your GitHub Secret is named GROQ_API_KEY
const GROQ_API_KEY = process.env.GROQ_API_KEY || ''; 
const GROQ_MODEL   = 'llama3-70b-8192'; 
const GROQ_URL     = 'https://api.groq.com/openai/v1/chat/completions';

const ROOT         = path.join(__dirname, '..');
const DATA_DIR     = path.join(ROOT, 'data');
const DOCS         = path.join(ROOT, 'docs');
const POSTS_DIR    = path.join(DOCS, 'posts');
const NEWS_F       = path.join(DATA_DIR, 'news.json');
const INDEX_F      = path.join(DATA_DIR, 'generated_articles.json');

const MAX_NEW_ARTICLES    = 5; 
const MAX_STORED_ARTICLES = 400;

if (!fs.existsSync(POSTS_DIR)) fs.mkdirSync(POSTS_DIR, { recursive: true });

// ── AI CALL (Groq) ────────────────────────────────────────────────────────
async function callGroq(prompt) {
  return new Promise((resolve, reject) => {
    if (!GROQ_API_KEY) return reject("Missing GROQ_API_KEY environment variable");

    const payload = JSON.stringify({
      model: GROQ_MODEL,
      messages: [
        { 
          role: "system", 
          content: "You are a professional broadcast technology editor. Write long-form, technical, and original articles in clean HTML (no <html>/<body> tags, just content)." 
        },
        { role: "user", content: prompt }
      ],
      temperature: 0.7
    });

    const options = {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${GROQ_API_KEY.trim()}`,
        'Content-Type': 'application/json'
      },
      timeout: 30000 // 30s timeout
    };

    const req = https.request(GROQ_URL, options, (res) => {
      let data = '';
      res.on('data', d => data += d);
      res.on('end', () => {
        if (res.statusCode !== 200) {
          return reject(`Groq API Error: ${res.statusCode} - ${data}`);
        }
        try {
          const json = JSON.parse(data);
          resolve(json.choices[0].message.content);
        } catch (e) {
          reject(`JSON Parse Error: ${e.message}`);
        }
      });
    });

    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

// ── UTILS ─────────────────────────────────────────────────────────────────
function slugify(text) {
  return text.toString().toLowerCase().trim()
    .replace(/\s+/g, '-')
    .replace(/[^\w\-]+/g, '')
    .replace(/\-\-+/g, '-');
}

// ── MAIN GENERATOR ────────────────────────────────────────────────────────
async function main() {
  console.log('🚀 The Streamic — Groq Article Generator');

  if (!fs.existsSync(NEWS_F)) {
    console.error('❌ Error: data/news.json not found. Run fetch_rss.py first.');
    return;
  }

  const newsData = JSON.parse(fs.readFileSync(NEWS_F, 'utf8'));
  const stored = fs.existsSync(INDEX_F) ? JSON.parse(fs.readFileSync(INDEX_F, 'utf8')) : [];
  const existingUrls = new Set(stored.map(a => a.source_url));

  // Extract candidate items from news.json (handle both object and array formats)
  let candidates = [];
  if (Array.isArray(newsData)) {
    candidates = newsData;
  } else {
    Object.keys(newsData).forEach(cat => {
      newsData[cat].forEach(item => candidates.push({ ...item, category: cat }));
    });
  }

  // Filter for items not already processed
  const toProcess = candidates.filter(c => !existingUrls.has(c.url || c.link)).slice(0, MAX_NEW_ARTICLES);
  console.log(`   → Found ${toProcess.length} new items to generate.`);

  const newArticles = [];

  for (const item of toProcess) {
    const title = item.title;
    const link = item.url || item.link;
    const slug = slugify(title);
    const category = item.category || 'streaming';

    console.log(`\n   [Processing] ${title}`);
    
    const prompt = `Write a comprehensive 1200-word technical analysis article about: "${title}". 
    Focus on broadcast engineering, workflow implications, and industry impact. 
    Source teaser: ${item.teaser || ''}. 
    Format as clean HTML using <h2>, <p>, and <ul>. Do not include markdown code fences.`;

    try {
      const bodyHtml = await callGroq(prompt);
      
      const article = {
        title,
        slug,
        category,
        published: new Date().toISOString().split('T')[0],
        source_url: link,
        source_domain: new URL(link).hostname.replace('www.', ''),
        body_html: bodyHtml,
        word_count: bodyHtml.split(/\s+/).length,
        image_url: item.image_url || 'https://images.unsplash.com/photo-1598488035139-bdbb2231ce04?w=900'
      };

      // Save individual HTML file
      const outPath = path.join(POSTS_DIR, `${slug}.html`);
      fs.writeFileSync(outPath, article.body_html, 'utf8');
      
      newArticles.push(article);
      console.log(`      ✓ Saved: docs/posts/${slug}.html`);
      
      // Brief sleep to respect Groq rate limits
      await new Promise(r => setTimeout(r, 2000));
      
    } catch (err) {
      console.error(`      ❌ Failed ${title}:`, err.message || err);
    }
  }

  // Merge and save index
  const finalIndex = [...newArticles, ...stored].slice(0, MAX_STORED_ARTICLES);
  fs.writeFileSync(INDEX_F, JSON.stringify(finalIndex, null, 2), 'utf8');
  console.log(`\n✅ Done: ${newArticles.length} new articles added to index.`);
}

main().catch(console.error);
