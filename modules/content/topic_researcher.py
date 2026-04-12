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

    def __init__(self, niche_keywords: List[str] = None, project_id: int = None):
        """
        Args:
            niche_keywords: list of niche keywords, e.g. ['productivity', 'time management']
            project_id: project ID for DB storage
        """
        self.niche_keywords = niche_keywords or ["productivity", "time management", "năng suất"]
        self.project_id = project_id

    def web_search_trending(self, query: str, count: int = 10) -> List[Dict]:
        """Search web for trending topics using YouSearch API."""
        try:
            import requests
            api_key = self._get_you_search_key()
            if not api_key:
                logger.warning("YouSearch API key not configured, using fallback topics")
                return self._fallback_topics(query)

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
            logger.warning(f"YouSearch failed: {e}, using fallback topics")
            return self._fallback_topics(query)

    def _get_you_search_key(self) -> str:
        """Get YouSearch API key from config."""
        try:
            from core.paths import PROJECT_ROOT
            import yaml
            cfg_path = PROJECT_ROOT / "configs" / "technical" / "config_technical.yaml"
            if cfg_path.exists():
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                return cfg.get("api", {}).get("keys", {}).get("you_search", "")
        except Exception:
            pass
        return ""

    def _fallback_topics(self, query: str) -> List[Dict]:
        """Fallback static topics when web search unavailable."""
        return [
            {
                "title": f"Top 5 cách quản lý thời gian hiệu quả",
                "summary": "Những phương pháp được chứng minh giúp tăng năng suất làm việc",
                "keywords": ["time management", "productivity", "efficiency", "planning"]
            },
            {
                "title": f"3 thói quen buổi sáng giúp tăng năng suất cả ngày",
                "summary": "Bắt đầu ngày đúng cách để làm việc hiệu quả hơn",
                "keywords": ["morning routine", "habits", "productivity", "energy"]
            },
            {
                "title": f"Phương pháp Pomodoro: Làm việc 25 phút nghỉ 5 phút",
                "summary": "Kỹ thuật quản lý thời gian phổ biến nhất thế giới",
                "keywords": ["pomodoro", "focus", "time management", "work session"]
            },
            {
                "title": f"Làm thế nào để không bị phân tâm khi làm việc?",
                "summary": "Mẹo giữ tập trung trong thời đại thông tin",
                "keywords": ["focus", "concentration", "distraction", "deep work"]
            },
            {
                "title": f"3 sai lầm phổ biến khi lập kế hoạch ngày",
                "summary": "Những lỗi khiến bạn không hoàn thành công việc",
                "keywords": ["planning", "to-do list", "time blocking", "prioritization"]
            }
        ]

    def research_from_keywords(self, keywords: List[str] = None, count: int = 10) -> List[Dict]:
        """
        Main method: research topics from keywords.
        Searches web for each keyword and aggregates results.
        """
        keywords = keywords or self.niche_keywords
        all_topics = []
        seen_titles = set()

        for kw in keywords:
            logger.info(f"Researching keyword: {kw}")
            topics = self.web_search_trending(kw, count=count)
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
