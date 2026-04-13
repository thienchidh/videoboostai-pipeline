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
from datetime import datetime
from typing import List, Dict, Optional, Any

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
        """Search web for trending topics using YouSearch API."""
        try:
            import requests
            api_key = self._get_you_search_key()
            if not api_key:
                logger.warning("YouSearch API key not configured")
                return []

            headers = {"X-API-Key": api_key}
            params = {"query": query, "count": count}
            response = requests.get(
                "https://ydc-index.io/v1/search",
                headers=headers,
                params=params,
                timeout=15
            )
            response.raise_for_status()
            data = response.json()

            topics = []
            for item in data.get("results", {}).get("web", [])[:count]:
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
            logger.warning(f"YouSearch failed: {e}")
            return []

    def _get_you_search_key(self) -> str:
        """Get YouSearch API key from TechnicalConfig."""
        try:
            from modules.pipeline.models import TechnicalConfig
            return TechnicalConfig.load().api_keys.you_search
        except Exception:
            pass
        return ""

    def research_from_keywords(self, keywords: List[str] = None, count: int = 10,
                               days_recent: int = 30) -> List[Dict]:
        """
        Main method: research topics from keywords.
        Searches web for each keyword and aggregates results.
        Deduplicates against recently researched titles from DB.
        """
        keywords = keywords or self.niche_keywords
        all_topics = []

        # Load recent titles from DB to avoid duplicates
        try:
            from db import get_recent_topic_titles
            seen_titles = get_recent_topic_titles(days=days_recent)
            logger.debug(f"Loaded {len(seen_titles)} recent titles from DB for dedup")
        except Exception as e:
            logger.warning(f"Could not load recent titles from DB: {e}, using empty set")
            seen_titles = set()

        for kw in keywords:
            logger.debug(f"Researching keyword: {kw}")
            topics = self.web_search_trending(kw, count=count)
            logger.debug(f"  Search results for '{kw}': {len(topics)} topics")
            for i, topic in enumerate(topics):
                logger.debug(f"    [{i+1}] {topic.get('title', '')[:80]}")
            for topic in topics:
                title = topic.get("title", "")
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    topic["source_keyword"] = kw
                    topic["researched_at"] = datetime.now().isoformat()
                    all_topics.append(topic)
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
