#!/usr/bin/env python3
"""
topic_researcher.py - Research trending topics for content
Uses web search to find trending topics, keywords, and content ideas
"""
import os
import sys
import json
import time
import logging
import requests
from datetime import datetime
from typing import List, Dict, Optional, Any

from modules.pipeline.backoff import Backoff

logger = logging.getLogger(__name__)


class TopicResearcher:
    """Research trending topics from web search and other sources."""

    # Common stopwords to filter from keyword extraction
    _STOPWORDS = {
        # Vietnamese stopwords (single-syllable words and common function words)
        "trong", "của", "là", "và", "có", "được", "cho", "với", "này", "không",
        "những", "một", "các", "tại", "về", "sau", "trước", "khi", "nếu",
        "thì", "hoặc", "vì", "nên", "từ", "lên", "xuống", "ra", "vào",
        "để", "qua", "bị", "đã", "đang", "sẽ", "có thể", "như", "hơn",
        "lượng", "lường", "tiếng", "việt", "nghĩa", "nguồn", "từ", "điểm",
        # English stopwords
        "what", "which", "who", "whom", "this", "that", "these", "those",
        "have", "has", "had", "does", "did", "will", "would", "could", "should",
        "about", "after", "before", "between", "into", "through", "during",
        "been", "being", "from", "they", "them", "their", "will", "with",
        "when", "where", "why", "how", "all", "each", "every", "both",
        "very", "just", "only", "also", "such", "most", "more", "some",
        "any", "much", "many", "several", "several", "definition", "meaning",
        "well", "best", "better", "new", "now", "here", "there", "thus",
    }

    def __init__(self, niche_keywords: List[str], project_id: Optional[int] = None):
        """
        Args:
            niche_keywords: list of niche keywords, e.g. ['productivity', 'time management']
            project_id: project ID for DB storage
        """
        if not niche_keywords:
            raise ValueError("niche_keywords is required")
        self.niche_keywords = niche_keywords
        self.project_id = project_id

    def web_search_trending(self, query: str, count: int = 10) -> List[Dict]:
        """Search web for trending topics using YouSearch API (up to 3 retries with backoff)."""
        api_key = self._get_you_search_key()
        if not api_key:
            logger.warning(f"YouSearch API key not configured for query: '{query}'")
            return []

        headers = {"X-API-Key": api_key}
        params = {"query": query, "count": count}
        logger.info(f"YouSearch request: query='{query}', count={count}")

        backoff = Backoff(base_delay=2.0, max_delay=30.0, factor=2.0)
        last_error = ""
        for attempt in range(3):
            try:
                response = requests.get(
                    "https://ydc-index.io/v1/search",
                    headers=headers,
                    params=params,
                    timeout=15
                )
                logger.info(f"YouSearch response status: {response.status_code}")
                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}"
                    logger.warning(f"YouSearch API error (attempt {attempt+1}/3): status={response.status_code}, body={response.text[:200]}")
                    backoff.sleep(attempt)
                    continue

                data = response.json()
                results = data.get("results", {}).get("web", [])
                logger.info(f"YouSearch returned {len(results)} results for query: '{query}'")

                topics = []
                for item in results[:count]:
                    title = item.get("title", "")
                    description = item.get("description", "") or item.get("url", "")
                    url = item.get("url", "")
                    # Extract keywords from title/description words
                    words = (title + " " + description).split()
                    keywords = list(set(w.lower() for w in words if len(w) > 4))[:5]
                    topics.append({
                        "title": title,
                        "summary": description[:200],
                        "keywords": keywords,
                        "source_url": url
                    })
                return topics
            except Exception as e:
                last_error = str(e)
                logger.warning(f"YouSearch request failed (attempt {attempt+1}/3): {e}")
                backoff.sleep(attempt)
                continue

        logger.error(f"YouSearch exhausted all retries, last error: {last_error}")
        return []

    def _get_you_search_key(self) -> str:
        """Get YouSearch API key from TechnicalConfig."""
        try:
            from modules.pipeline.models import TechnicalConfig
            return TechnicalConfig.load().api_keys.you_search
        except Exception:
            pass
        return ""

    def _is_good_keyword(self, word: str) -> bool:
        """Return True if word is a meaningful keyword (not stopword or garbage)."""
        w = word.lower().strip(".,!?;:'\"()[]{}")
        # Must be >= 5 chars
        if len(w) < 5:
            return False
        # No digits
        if any(c.isdigit() for c in w):
            return False
        # No pure punctuation
        if all(not c.isalnum() for c in w):
            return False
        # Not a stopword
        if w in self._STOPWORDS:
            return False
        return True

    def extract_keywords_from_topic(self, topic: Dict) -> List[str]:
        """Extract 3-5 meaningful keywords from topic title + description.

        Filters out Vietnamese/English stopwords, single words, and garbage.
        Only keeps compound words (likely real topics) for future research.
        """
        title = topic.get("title", "")
        description = topic.get("description", "") or topic.get("url", "")
        text = title + " " + description
        words = text.split()
        keywords = set()
        for w in words:
            w_stripped = w.lower().strip(".,!?;:'\"()[]{}")
            if self._is_good_keyword(w_stripped):
                keywords.add(w_stripped)
        return list(keywords)[:5]

    def _expand_keyword(self, kw: str) -> List[str]:
        """Expand a keyword into compound search queries for better coverage.

        Instead of searching just "productivity", search for more specific
        compound queries that return fewer generic Wikipedia results.
        """
        suffixes = [
            "tips", "techniques", "methods", "hacks", "strategies",
            "for students", "for workers", "2024", "best practices",
        ]
        queries = [kw]  # Always include the base keyword
        for suffix in suffixes[:3]:  # Limit to 3 variations to avoid too many searches
            queries.append(f"{kw} {suffix}")
        return queries

    def research_from_keywords(self, keywords: List[str] = None, count: int = 10) -> List[Dict]:
        """
        Main method: research topics from keywords.

        Uses compound search queries (keyword + suffixes) instead of bare keywords
        to get more specific, non-Wikipedia results.

        True deduplication of generated ideas is handled by check_duplicate_ideas()
        using semantic similarity (sentence-transformers).
        """
        keywords = keywords or self.niche_keywords
        all_topics = []

        for kw in keywords:
            # Expand to compound queries for more specific results
            queries = self._expand_keyword(kw)
            for query in queries:
                search_count = max(count, 10)
                logger.info(f"Researching query: '{query}', count={search_count}")
                topics = self.web_search_trending(query, count=search_count)
                logger.info(f"  Search results for '{query}': {len(topics)} topics")
                for i, topic in enumerate(topics):
                    logger.info(f"    [{i+1}] {topic.get('title', '')[:80]}")
                for topic in topics:
                    topic["source_keyword"] = kw
                    topic["researched_at"] = datetime.now().isoformat()
                    all_topics.append(topic)
                    # Only save GOOD keywords (filtered by _is_good_keyword)
                    extracted = self.extract_keywords_from_topic(topic)
                    for kw_extracted in extracted:
                        if self._is_good_keyword(kw_extracted):
                            try:
                                from db import save_keyword
                                save_keyword(kw_extracted, source_topic_id=None)
                            except Exception:
                                pass  # Non-fatal
                time.sleep(0.5)  # Rate limit

        return all_topics

    def analyze_keywords(self, topics: List[Dict]) -> Dict[str, int]:
        """
        Analyze and count keyword frequency across topics.
        Returns dict of keyword -> frequency.
        """
        keyword_counts = {}
        for topic in topics:
            for kw in topic.get("keywords", []):
                kw_lower = kw.lower()
                keyword_counts[kw_lower] = keyword_counts.get(kw_lower, 0) + 1
        return dict(sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True))

    def save_to_db(self, topics: List[Dict], source_type: str = "web_search",
                   source_query: str = None) -> int:
        """Save researched topics to DB, return source_id."""
        if not self.project_id:
            logger.warning("No project_id, cannot save to DB")
            return None

        try:
            from db import save_topic_sources
            source_id = save_topic_sources(source_type, source_query, topics)
            logger.info(f"Saved {len(topics)} topics to topic_sources.id={source_id}")
            return source_id
        except Exception as e:
            logger.error(f"Failed to save topics to DB: {e}")
            return None

    def get_competitor_topics(self, competitors: List[str]) -> List[Dict]:
        """Get topics from competitor pages (placeholder for future scraping)."""
        # Future: scrape competitor pages for their top content
        logger.info(f"Competitor research not yet implemented: {competitors}")
        return []

    def get_hashtag_trends(self, platform: str = "tiktok") -> List[str]:
        """Get trending hashtags for the niche (placeholder)."""
        base_hashtags = [
            "#nangsuat", "#quanlythoigian", "#productivity",
            "#thoigian", "#lamviechieu", "#congviec",
            "#hieuqua", "#thoigianbien", "#matngay",
            "#caidatngay", "#tietkiemthoigian"
        ]
        return base_hashtags


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    researcher = TopicResearcher(niche_keywords=["productivity", "time management", "năng suất"])

    print("🔍 Researching trending topics...")
    topics = researcher.research_from_keywords(count=10)
    print(f"Found {len(topics)} topics:")
    for t in topics[:5]:
        print(f"  - {t.get('title', 'Untitled')}")

    kw_analysis = researcher.analyze_keywords(topics)
    print(f"\nTop keywords: {list(kw_analysis.items())[:10]}")
