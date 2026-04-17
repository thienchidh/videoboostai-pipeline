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

    def extract_keywords_from_topic(self, topic: Dict) -> List[str]:
        """Extract 3-5 keywords from topic title + description for next research cycle."""
        title = topic.get("title", "")
        description = topic.get("description", "") or topic.get("url", "")
        text = title + " " + description
        words = text.split()
        keywords = set()
        for w in words:
            w_lower = w.lower().strip(".,!?;:'\"()[]{}")
            if len(w_lower) > 4 and not w_lower.isdigit():
                keywords.add(w_lower)
        return list(keywords)[:5]

    def research_from_keywords(self, keywords: List[str] = None, count: int = 10) -> List[Dict]:
        """
        Main method: research topics from keywords.
        Searches web for each keyword and aggregates results.

        Note: Title dedup against recent DB topics was REMOVED - it was too aggressive
        and blocked all YouSearch results because common keywords always return the same
        Wikipedia/Dictionary pages. True deduplication of generated ideas is handled by
        check_duplicate_ideas() using semantic similarity (sentence-transformers), which
        compares idea MEANING not exact title matches.
        """
        keywords = keywords or self.niche_keywords
        all_topics = []

        for kw in keywords:
            # Search with higher count per keyword to account for some filtering
            search_count = max(count, 10)  # at least 10 per keyword
            logger.info(f"Researching keyword: '{kw}', search_count={search_count}")
            topics = self.web_search_trending(kw, count=search_count)
            logger.info(f"  Search results for '{kw}': {len(topics)} topics")
            for i, topic in enumerate(topics):
                logger.info(f"    [{i+1}] {topic.get('title', '')[:80]}")
            for topic in topics:
                topic["source_keyword"] = kw
                topic["researched_at"] = datetime.now().isoformat()
                all_topics.append(topic)
                extracted = self.extract_keywords_from_topic(topic)
                for kw_extracted in extracted:
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
