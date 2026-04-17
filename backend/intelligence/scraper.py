"""
Real-time sports intelligence scraper.

Sources (all free, no API key required):
  - Google News RSS  — team-specific injury/lineup searches
  - BBC Sport RSS    — football headlines
  - Sky Sports RSS   — football/multi-sport
  - ESPN RSS         — international sports
  - Guardian Sport   — football analytics

Returns raw article dicts ready for NLP extraction.
"""
from __future__ import annotations
import re
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

import feedparser
import httpx
import trafilatura

# ── Feed sources ──────────────────────────────────────────────────────

GOOGLE_NEWS_TEMPLATE = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=en-US&gl=US&ceid=US:en&num=10"
)

STATIC_FEEDS = [
    ("bbc_sport",     "https://feeds.bbci.co.uk/sport/football/rss.xml"),
    ("sky_sports",    "https://www.skysports.com/rss/12040"),
    ("espn_soccer",   "https://www.espn.com/espn/rss/soccer/news"),
    ("guardian",      "https://www.theguardian.com/football/rss"),
    ("goal_com",      "https://www.goal.com/feeds/en/news"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

INJURY_KEYWORDS = [
    "injur", "suspend", "doubt", "ruled out", "miss", "absent",
    "lineup", "team news", "squad", "fit", "return", "fit for",
    "crisis", "blow", "setback", "unavailable", "confirmed",
]


class IntelligenceScraper:
    """Fetches sports news for a set of teams."""

    def __init__(self, timeout: float = 10.0):
        self._client = httpx.Client(
            timeout=timeout,
            headers=HEADERS,
            follow_redirects=True,
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ── Public API ────────────────────────────────────────────────────

    def fetch_for_match(
        self,
        home_team: str,
        away_team: str,
        hours: int = 48,
    ) -> list[dict]:
        """Fetch all intelligence articles relevant to a match."""
        articles: list[dict] = []

        for team in [home_team, away_team]:
            articles.extend(self._team_google_news(team, hours))

        # Optionally enrich with static feeds (filtered by team name)
        articles.extend(
            self._filter_static_feeds([home_team, away_team], hours)
        )

        return _deduplicate(articles)

    def fetch_article_text(self, url: str) -> Optional[str]:
        """Extract clean article body from a URL using trafilatura."""
        try:
            r = self._client.get(url, timeout=8.0)
            if r.status_code == 200:
                text = trafilatura.extract(
                    r.text,
                    include_comments=False,
                    include_tables=False,
                    no_fallback=False,
                )
                return text[:2500] if text else None
        except Exception as e:
            logger.debug(f"Article fetch failed {url}: {e}")
        return None

    # ── Internal helpers ──────────────────────────────────────────────

    def _team_google_news(self, team: str, hours: int) -> list[dict]:
        keywords = " OR ".join(
            f'"{kw}"' for kw in ["injury", "suspended", "lineup", "team news", "miss"]
        )
        query = f'"{team}" ({keywords})'
        url = GOOGLE_NEWS_TEMPLATE.format(
            query=_urlencode(query)
        )
        return self._parse_feed(url, source="google_news", team=team, hours=hours)

    def _filter_static_feeds(self, teams: list[str], hours: int) -> list[dict]:
        results: list[dict] = []
        for source_name, feed_url in STATIC_FEEDS:
            try:
                articles = self._parse_feed(feed_url, source=source_name, hours=hours)
                for art in articles:
                    text_to_check = (art.get("title", "") + " " + art.get("snippet", "")).lower()
                    if any(t.lower() in text_to_check for t in teams):
                        if _has_injury_keyword(text_to_check):
                            results.append(art)
            except Exception as e:
                logger.debug(f"Static feed {source_name} failed: {e}")
        return results

    def _parse_feed(
        self,
        url: str,
        source: str,
        team: Optional[str] = None,
        hours: int = 48,
    ) -> list[dict]:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        articles: list[dict] = []
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:12]:
                pub = _parse_date(entry)
                if pub and pub < cutoff:
                    continue
                title = entry.get("title", "")
                snippet = _strip_html(entry.get("summary", ""))[:600]
                articles.append({
                    "title":     title,
                    "url":       entry.get("link", ""),
                    "published": pub.isoformat() if pub else None,
                    "source":    source,
                    "team":      team or "",
                    "snippet":   snippet,
                    "text":      None,   # filled lazily if needed
                })
        except Exception as e:
            logger.warning(f"Feed parse error [{source}]: {e}")
        return articles


# ── Utilities ─────────────────────────────────────────────────────────

def _urlencode(s: str) -> str:
    return s.replace(" ", "+").replace('"', "%22").replace("(", "%28").replace(")", "%29")


def _has_injury_keyword(text: str) -> bool:
    return any(kw in text for kw in INJURY_KEYWORDS)


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


def _parse_date(entry) -> Optional[datetime]:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6])
        except Exception:
            pass
    return None


def _deduplicate(articles: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for a in articles:
        key = a.get("url") or a.get("title", "")
        if key and key not in seen:
            seen.add(key)
            out.append(a)
    return out
