"""
PlayIntel News Engine — Full-pipeline article fetcher + AI rewriter.

Sources: BBC Sport, Sky Sports, The Guardian, The Sun, ESPN, Mirror Football,
         FourFourTwo, Caught Offside, transfermarkt-style transfer news.

Pipeline:
  1. Fetch RSS feeds from all sources
  2. Extract FULL article text via trafilatura (not just RSS summary)
  3. Rewrite with Gemini Flash → 400-600 word human-like journalism
  4. Categorise: Transfer | Injury | Match Preview | Match Report | General
  5. Save to DB — deduplicated by source URL
"""
from __future__ import annotations
import hashlib
import re
import time
import httpx
import feedparser
from datetime import datetime, timedelta
from loguru import logger

try:
    import trafilatura
    _HAS_TRAFILATURA = True
except ImportError:
    _HAS_TRAFILATURA = False

# ─────────────────────────────────────────────────────────────────────────────
# RSS Sources — multi-sport
# ─────────────────────────────────────────────────────────────────────────────
NEWS_FEEDS = [
    # ── Football ──────────────────────────────────────────────────────
    {"url": "https://feeds.bbci.co.uk/sport/football/rss.xml",              "name": "BBC Sport",             "cat": "football"},
    {"url": "https://www.skysports.com/rss/12040",                           "name": "Sky Sports",            "cat": "football"},
    {"url": "https://www.theguardian.com/football/rss",                      "name": "The Guardian",          "cat": "football"},
    {"url": "https://www.espn.com/espn/rss/soccer/news",                     "name": "ESPN Soccer",           "cat": "football"},
    {"url": "https://www.fourfourtwo.com/rss",                               "name": "FourFourTwo",           "cat": "football"},
    {"url": "https://www.caughtoffside.com/feed/",                           "name": "Caught Offside",        "cat": "transfers"},
    {"url": "https://www.skysports.com/rss/12604",                           "name": "Sky Sports Transfers",  "cat": "transfers"},
    {"url": "https://www.theguardian.com/football/transfers/rss",            "name": "Guardian Transfers",    "cat": "transfers"},
    {"url": "https://www.bbc.co.uk/sport/football/gossip-column/rss.xml",    "name": "BBC Gossip",            "cat": "transfers"},
    # ── Basketball ────────────────────────────────────────────────────
    {"url": "https://www.espn.com/espn/rss/nba/news",                        "name": "ESPN NBA",              "cat": "basketball"},
    {"url": "https://feeds.bbci.co.uk/sport/basketball/rss.xml",             "name": "BBC Basketball",        "cat": "basketball"},
    # ── Tennis ────────────────────────────────────────────────────────
    {"url": "https://feeds.bbci.co.uk/sport/tennis/rss.xml",                 "name": "BBC Tennis",            "cat": "tennis"},
    # ── F1 / Motorsport ───────────────────────────────────────────────
    {"url": "https://feeds.bbci.co.uk/sport/formula1/rss.xml",               "name": "BBC F1",                "cat": "motorsport"},
    # ── Cricket ───────────────────────────────────────────────────────
    {"url": "https://feeds.bbci.co.uk/sport/cricket/rss.xml",                "name": "BBC Cricket",           "cat": "cricket"},
    # ── Rugby ─────────────────────────────────────────────────────────
    {"url": "https://feeds.bbci.co.uk/sport/rugby-union/rss.xml",            "name": "BBC Rugby",             "cat": "rugby"},
    # ── American Football ─────────────────────────────────────────────
    {"url": "https://www.espn.com/espn/rss/nfl/news",                        "name": "ESPN NFL",              "cat": "american-football"},
]

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _fetch_og_image(url: str) -> str | None:
    """Extract og:image from article HTML."""
    if not url:
        return None
    try:
        r = httpx.get(url, headers=_BROWSER_HEADERS, timeout=10, follow_redirects=True)
        # Try property="og:image" format
        m = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r.text, re.IGNORECASE
        )
        if not m:
            # Try content="..." property="og:image" format
            m = re.search(
                r'<meta[^>]+content=["\']([^"\']{10,})["\'][^>]+property=["\']og:image["\']',
                r.text, re.IGNORECASE
            )
        if m:
            img = m.group(1).strip()
            if img.startswith("http") and len(img) > 15:
                return img[:1000]
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Gemini prompt — produces a proper 400-600 word journalistic article
# ─────────────────────────────────────────────────────────────────────────────
_ARTICLE_PROMPT = """\
You are a senior football journalist at a major sports publication. \
Rewrite the raw source material below into a complete, polished article \
of 400–600 words. Follow this exact structure:

**HEADLINE**: One punchy headline (under 90 characters)
**STANDFIRST**: One compelling sentence that makes readers want to read on (under 160 characters)
**TAGS**: Comma-separated names of clubs, players, competitions mentioned (max 10)
**CATEGORY**: One of: transfers | injuries | match-preview | match-report | general

ARTICLE BODY:
- Paragraph 1 (lead): The single most important fact — who, what, when
- Paragraph 2–3 (context): Why this matters. Team form, player background, competition context
- Paragraph 4 (analysis): What this means for upcoming fixtures or the betting angle
- Paragraph 5 (outlook): What happens next — expected timeline, other clubs involved, or next match

Rules:
- Write in active, confident voice. No passive constructions where possible.
- Use specific numbers, dates, and names — no vague statements
- Never say "In conclusion", "It is worth noting", "According to reports"
- Never refer to yourself or PlayIntel
- Include the original source as context but write it fresh — do not copy sentences
- If the story is about an injury, name the player, severity, and how many matches they will miss
- If transfer: name the clubs, fee estimate if known, contract length if known

Source material:
{text}
"""


def _make_slug(title: str, url: str) -> str:
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    base = re.sub(r"[^a-z0-9]+", "-", title.lower())[:60].strip("-")
    return f"{base}-{h}"


_SPORT_CATEGORIES = {"basketball", "tennis", "motorsport", "cricket", "rugby", "american-football"}


def _detect_category(title: str, body: str, source_cat: str = "") -> str:
    """Detect article category from content keywords. Respects non-football source categories."""
    # Preserve sport-specific categories directly from feed config
    if source_cat in _SPORT_CATEGORIES:
        return source_cat
    text = (title + " " + body).lower()
    if any(w in text for w in ["sign", "transfer", "deal", "fee", "bid", "move", "loan", "contract", "join"]):
        return "transfers"
    if any(w in text for w in ["injur", "suspended", "suspension", "doubtful", "ruled out", "miss", "fitness"]):
        return "injuries"
    if any(w in text for w in ["preview", "ahead of", "face", "meet", "clash", "take on", "vs", "matchday"]):
        return "match-preview"
    if any(w in text for w in ["result", "score", "win", "loss", "defeat", "draw", "goal", "minutes", "full-time"]):
        return "match-report"
    return "general"


def fetch_recent_articles(hours: int = 12, max_per_feed: int = 6) -> list[dict]:
    """Pull recent items from all RSS feeds."""
    articles = []
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    for feed_cfg in NEWS_FEEDS:
        try:
            parsed = feedparser.parse(feed_cfg["url"])
            count = 0
            for entry in parsed.entries:
                if count >= max_per_feed:
                    break
                pub = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        pub = datetime(*entry.published_parsed[:6])
                    except Exception:
                        pass
                if pub and pub < cutoff:
                    continue

                link = getattr(entry, "link", "")
                if not link:
                    continue

                summary_raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
                articles.append({
                    "title": getattr(entry, "title", "").strip(),
                    "url": link,
                    "summary_raw": re.sub(r"<[^>]+>", " ", summary_raw).strip()[:800],
                    "published_at": pub,
                    "source_name": feed_cfg["name"],
                    "category": feed_cfg["cat"],
                })
                count += 1
        except Exception as e:
            logger.warning(f"Feed {feed_cfg['name']} failed: {e}")

    logger.info(f"News fetcher: {len(articles)} items from {len(NEWS_FEEDS)} feeds")
    return articles


def fetch_full_article_text(url: str) -> str:
    """
    Fetch the full article body from any URL.
    Uses trafilatura with real browser headers for maximum extraction.
    Falls back to httpx if trafilatura fetch fails.
    """
    if not url:
        return ""
    try:
        if _HAS_TRAFILATURA:
            # First try trafilatura's built-in fetcher
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=False,
                    no_fallback=False,
                )
                if text and len(text) > 300:
                    return text[:4000]

        # Fallback: httpx with browser headers
        r = httpx.get(url, headers=_BROWSER_HEADERS, timeout=15, follow_redirects=True)
        if r.status_code == 200 and _HAS_TRAFILATURA:
            text = trafilatura.extract(r.text, include_comments=False)
            if text and len(text) > 300:
                return text[:4000]
    except Exception as e:
        logger.debug(f"Full text fetch failed for {url}: {e}")
    return ""


_GEMINI_MODEL = "gemini-2.0-flash"


def rewrite_with_gemini(api_key: str, article: dict) -> dict | None:
    """
    Rewrite an article using Gemini Flash.
    Returns a published (AI-rewritten) dict, or a draft (raw) dict if Gemini is unavailable.
    Raw drafts are NOT served publicly — they queue for a retry rewrite.
    """
    # Get full article text — prefer full body over RSS summary
    full_text = fetch_full_article_text(article["url"])
    source_text = full_text if len(full_text) > 300 else article.get("summary_raw", "")

    if len(source_text) < 80:
        logger.debug(f"Skipping article — too little text: {article['title'][:50]}")
        return None

    # Fetch the source article's og:image — matches the actual subject (player/team/event)
    image_url = _fetch_og_image(article["url"])

    # Try Gemini rewrite
    if api_key:
        result = _call_gemini(api_key, article, source_text)
        if result:
            result["image_url"] = image_url
            return result

    # Gemini unavailable — save as draft, not published
    # Draft articles are held back from the public feed until rewritten
    logger.info(f"Gemini unavailable — queuing as draft: {article['title'][:50]}")
    raw = _build_raw_article(article, source_text)
    raw["image_url"] = image_url
    return raw


def _call_gemini(api_key: str, article: dict, source_text: str) -> dict | None:
    """Call Gemini API to rewrite article. Returns None on any failure."""
    prompt = _ARTICLE_PROMPT.format(text=source_text[:3500])
    gemini_url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_GEMINI_MODEL}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 2048,
            "temperature": 0.75,
            "topP": 0.9,
        },
    }

    for attempt in range(2):
        try:
            resp = httpx.post(gemini_url, json=payload, timeout=45)
            if resp.status_code == 429:
                if attempt == 0:
                    logger.debug("Gemini rate limit — waiting 15s")
                    time.sleep(15)
                    continue
                else:
                    logger.debug("Gemini quota exhausted — falling back to raw text")
                    return None
            if resp.status_code != 200:
                logger.debug(f"Gemini returned {resp.status_code} — falling back")
                return None
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            if len(raw) < 200:
                logger.debug(f"Gemini response too short ({len(raw)} chars) — falling back")
                return None
            result = _parse_gemini_output(raw, article)
            if result and len(result.get("body", "")) > 200:
                return result
            return None
        except Exception as e:
            logger.warning(f"Gemini attempt {attempt + 1} failed: {e}")
            time.sleep(3)
    return None


_BOILERPLATE_PHRASES = [
    "sign up", "newsletter", "subscribe", "subscription", "sign in", "log in",
    "cookie", "privacy policy", "terms of use", "all rights reserved",
    "follow us", "share this", "click here", "read more", "more stories",
    "advertisement", "promoted", "sponsored", "related articles",
    "you might also like", "most popular", "trending", "recommended",
    "get full access", "premium article", "member reward", "exclusive feature",
    "straight to your inbox", "footballing quizzes", "best features",
    "breaking news", "latest news", "news alerts",
]


def _build_raw_article(article: dict, source_text: str) -> dict:
    """
    Build an article record from raw extracted text (no AI rewrite).
    Filters boilerplate and cleans into readable paragraphs.
    """
    lines = [l.strip() for l in source_text.split("\n") if l.strip()]

    paragraphs = []
    for line in lines:
        # Skip short lines, bare URLs, and boilerplate
        if len(line) < 60:
            continue
        if line.lower().startswith("http"):
            continue
        low = line.lower()
        if any(phrase in low for phrase in _BOILERPLATE_PHRASES):
            continue
        paragraphs.append(line)

    body = "\n\n".join(paragraphs[:18]) if paragraphs else source_text[:3000]

    # First sentence as standfirst
    first_para = paragraphs[0] if paragraphs else article.get("summary_raw", "")
    first_sent = first_para.split(". ")[0]
    standfirst = (first_sent[:157] + "...") if len(first_sent) > 160 else first_sent

    category = _detect_category(article["title"], body, source_cat=article.get("category", ""))

    return {
        "title":       article["title"],
        "summary":     standfirst,
        "body":        body,
        "tags":        "",
        "category":    category,
        "source_url":  article["url"],
        "source_name": article["source_name"],
        "published_at": article.get("published_at"),
        "slug":        _make_slug(article["title"], article["url"]),
        "image_url":   None,   # set by caller after og:image fetch
        "status":      "draft",  # raw text — holds back from public feed until Gemini rewrites
    }


def _parse_gemini_output(raw: str, article: dict) -> dict:
    """
    Parse structured Gemini output.
    Handles both the exact prompt format and looser variations Gemini may return.
    """
    title      = article["title"]
    standfirst = ""
    tags       = ""
    category   = article.get("category", "general")
    body_lines = []
    in_body    = False

    # Regex to strip any bold markdown prefix like **HEADLINE**: or HEADLINE:
    _strip = lambda prefix, s: re.sub(
        rf"\*{{0,2}}{re.escape(prefix)}\*{{0,2}}:?\s*", "", s, flags=re.IGNORECASE
    ).strip().strip("*").strip()

    for line in raw.strip().split("\n"):
        stripped = line.strip()
        up = stripped.upper()

        if re.match(r"\*{0,2}HEADLINE\*{0,2}:?", stripped, re.IGNORECASE):
            t = _strip("HEADLINE", stripped)
            if len(t) > 10:
                title = t[:512]
        elif re.match(r"\*{0,2}(STANDFIRST|SUBHEADLINE|SUBTITLE|LEDE)\*{0,2}:?", stripped, re.IGNORECASE):
            s = re.sub(r"\*{0,2}(STANDFIRST|SUBHEADLINE|SUBTITLE|LEDE)\*{0,2}:?\s*", "", stripped, flags=re.IGNORECASE).strip().strip("*")
            if s:
                standfirst = s[:512]
        elif re.match(r"\*{0,2}TAGS?\*{0,2}:?", stripped, re.IGNORECASE):
            t = re.sub(r"\*{0,2}TAGS?\*{0,2}:?\s*", "", stripped, flags=re.IGNORECASE).strip().strip("*")
            if t:
                tags = t[:512]
        elif re.match(r"\*{0,2}CATEGOR(Y|IES)\*{0,2}:?", stripped, re.IGNORECASE):
            c = re.sub(r"\*{0,2}CATEGOR(Y|IES)\*{0,2}:?\s*", "", stripped, flags=re.IGNORECASE).strip().strip("*").lower()
            if c in ("transfers", "injuries", "match-preview", "match-report", "general"):
                category = c
        elif re.match(r"\*{0,2}ARTICLE\s+BODY\*{0,2}:?", stripped, re.IGNORECASE) or up == "ARTICLE BODY:":
            in_body = True
        elif in_body:
            body_lines.append(line)

    body = "\n\n".join(
        p.strip() for p in "\n".join(body_lines).split("\n\n") if p.strip()
    )

    # If no ARTICLE BODY section found, extract body by skipping header lines
    if not body or len(body) < 200:
        content_lines = []
        skip_headers = {"HEADLINE", "STANDFIRST", "SUBHEADLINE", "SUBTITLE", "LEDE", "TAGS", "TAG", "CATEGORY", "CATEGORIES", "ARTICLE BODY"}
        for line in raw.strip().split("\n"):
            s = line.strip()
            if not s:
                content_lines.append("")
                continue
            # Skip lines that look like structured headers
            is_header = any(re.match(rf"\*{{0,2}}{h}\*{{0,2}}:?", s, re.IGNORECASE) for h in skip_headers)
            if not is_header:
                content_lines.append(line)
        body = "\n\n".join(
            p.strip() for p in "\n".join(content_lines).split("\n\n") if p.strip()
        )

    # Last resort — use raw as body
    if not body or len(body) < 100:
        body = raw.strip()

    if not standfirst and body:
        first_sent = body.split(". ")[0]
        standfirst = (first_sent[:157] + "...") if len(first_sent) > 160 else first_sent

    if category not in ("transfers", "injuries", "match-preview", "match-report"):
        category = _detect_category(title, body, source_cat=article.get("category", ""))

    return {
        "title":       title,
        "summary":     standfirst,
        "body":        body,
        "tags":        tags,
        "category":    category,
        "source_url":  article["url"],
        "source_name": article["source_name"],
        "published_at": article.get("published_at"),
        "slug":        _make_slug(title, article["url"]),
        "image_url":   None,   # set by caller after og:image fetch
        "status":      "published",  # Gemini-rewritten — safe for public feed
    }


def run_news_pipeline_sync(db, api_key: str, hours: int = 12, max_articles: int = 25) -> int:
    """
    Synchronous pipeline — used by scheduler and API trigger.
    Returns number of articles saved.
    """
    from sqlalchemy import select as _sel
    from data.db_models.models import NewsArticle

    if not api_key:
        logger.warning("No Gemini API key — news pipeline skipped")
        return 0

    raw_articles = fetch_recent_articles(hours=hours)
    if not raw_articles:
        return 0

    urls = [a["url"] for a in raw_articles]
    existing_urls = {
        row[0] for row in db.execute(
            _sel(NewsArticle.source_url).where(NewsArticle.source_url.in_(urls))
        ).fetchall()
    }

    new_articles = [a for a in raw_articles if a["url"] not in existing_urls]
    logger.info(f"News pipeline: {len(new_articles)} new articles to process")

    saved = 0
    for art in new_articles[:max_articles]:
        result = rewrite_with_gemini(api_key, art)
        if not result:
            continue
        try:
            row = NewsArticle(
                title=result["title"],
                slug=result["slug"],
                source_url=result["source_url"],
                source_name=result["source_name"],
                category=result["category"],
                summary=result["summary"],
                body=result["body"],
                tags=result.get("tags", ""),
                published_at=result.get("published_at"),
                image_url=result.get("image_url"),
                status=result.get("status", "published"),
            )
            db.add(row)
            db.commit()
            saved += 1
            logger.info(f"News [{result['status']}]: [{result['category']}] {result['title'][:60]}")
        except Exception as e:
            db.rollback()
            # Slug collision — try with a unique suffix
            if "UNIQUE" in str(e) and "slug" in str(e):
                try:
                    import uuid
                    result["slug"] = result["slug"][:60] + "-" + uuid.uuid4().hex[:6]
                    row = NewsArticle(
                        title=result["title"], slug=result["slug"],
                        source_url=result["source_url"], source_name=result["source_name"],
                        category=result["category"], summary=result["summary"],
                        body=result["body"], tags=result.get("tags", ""),
                        published_at=result.get("published_at"),
                        image_url=result.get("image_url"),
                        status=result.get("status", "published"),
                    )
                    db.add(row)
                    db.commit()
                    saved += 1
                except Exception:
                    db.rollback()
            else:
                logger.debug(f"News save error: {e}")
        time.sleep(1.2)  # gentle rate limiting

    logger.info(f"News pipeline complete — {saved} articles saved")
    return saved


def retry_draft_articles(db, api_key: str, max_articles: int = 10) -> int:
    """
    Attempt to rewrite articles currently in 'draft' status using Gemini.
    Promotes successful rewrites to 'published'.
    Called by the scheduler every 30 minutes so drafts don't stay hidden forever.
    Returns number of articles promoted to published.
    """
    from sqlalchemy import select as _sel
    from data.db_models.models import NewsArticle

    if not api_key:
        return 0

    drafts = db.execute(
        _sel(NewsArticle)
        .where(NewsArticle.status == "draft")
        .order_by(NewsArticle.created_at.asc())
        .limit(max_articles)
    ).scalars().all()

    if not drafts:
        return 0

    logger.info(f"Draft retry: attempting to rewrite {len(drafts)} draft articles")
    promoted = 0

    for article_row in drafts:
        # Build a minimal article dict for the rewriter
        article = {
            "url":         article_row.source_url,
            "title":       article_row.title,
            "summary_raw": article_row.summary or "",
            "source_name": article_row.source_name,
            "category":    article_row.category,
            "published_at": article_row.published_at,
        }

        full_text = fetch_full_article_text(article["url"])
        source_text = full_text if len(full_text) > 300 else article["summary_raw"]

        if len(source_text) < 80:
            continue

        result = _call_gemini(api_key, article, source_text)
        if not result:
            # Gemini still unavailable — try again next cycle
            continue

        # Fetch og:image if we don't have one yet
        if not article_row.image_url:
            result["image_url"] = _fetch_og_image(article["url"])
        else:
            result["image_url"] = article_row.image_url

        try:
            article_row.title     = result["title"]
            article_row.summary   = result["summary"]
            article_row.body      = result["body"]
            article_row.tags      = result.get("tags", article_row.tags or "")
            article_row.category  = result["category"]
            article_row.image_url = result["image_url"]
            article_row.status    = "published"
            db.commit()
            promoted += 1
            logger.info(f"Draft promoted: {article_row.title[:60]}")
        except Exception as e:
            db.rollback()
            logger.debug(f"Draft promotion error: {e}")

        time.sleep(1.5)  # rate limiting between Gemini calls

    logger.info(f"Draft retry complete — {promoted}/{len(drafts)} promoted to published")
    return promoted
