#!/usr/bin/env python3
"""
content_calendar.py - Schedule and track content production pipeline
"""
import os
import sys
import json
import logging
from datetime import datetime, date, time, timedelta
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


class ContentCalendar:
    """Manage content calendar: schedule, track, and trigger production."""

    def __init__(self, project_id: int = None, platform: str = "both"):
        """
        Args:
            project_id: project ID
            platform: 'facebook', 'tiktok', or 'both'
        """
        self.project_id = project_id
        self.platform = platform

    def schedule_idea(self, idea_id: int, platform: str = None,
                     scheduled_date: date = None, scheduled_time: time = None,
                     priority: str = "medium", notes: str = None) -> int:
        """
        Schedule a content idea for a specific platform and time.
        Returns calendar entry ID.
        """
        platform = platform or self.platform
        scheduled_date = scheduled_date or date.today()
        scheduled_time = scheduled_time or time(9, 0)  # Default 9 AM

        try:
            from db import schedule_content_idea
            calendar_id = schedule_content_idea(
                idea_id=idea_id,
                platform=platform,
                scheduled_date=scheduled_date,
                scheduled_time=scheduled_time,
                priority=priority,
                notes=notes,
            )
            logger.info(f"Scheduled idea {idea_id} for {platform} on {scheduled_date}")
            return calendar_id
        except Exception as e:
            logger.error(f"Failed to schedule idea: {e}")
            return None

    def schedule_next_from_queue(self, idea_ids: List[int],
                                 platform: str = None,
                                 start_date: date = None,
                                 interval_days: int = 1,
                                 time_of_day: time = time(9, 0)) -> List[int]:
        """
        Schedule multiple ideas from queue with spacing.
        """
        platform = platform or self.platform
        start_date = start_date or date.today()
        calendar_ids = []

        for i, idea_id in enumerate(idea_ids):
            sched_date = start_date + timedelta(days=i * interval_days)
            cal_id = self.schedule_idea(
                idea_id=idea_id,
                platform=platform,
                scheduled_date=sched_date,
                scheduled_time=time_of_day,
                priority="medium"
            )
            if cal_id:
                calendar_ids.append(cal_id)

        logger.info(f"Scheduled {len(calendar_ids)} items from queue")
        return calendar_ids

    def get_due_items(self, platform: str = None,
                      as_of: datetime = None) -> List[Dict]:
        """
        Get all calendar items that are due for production.
        Returns items where scheduled_date <= today AND status = 'scheduled'.
        """
        as_of = as_of or datetime.now()
        try:
            from db import get_due_calendar_items
            return get_due_calendar_items(as_of.date(), platform=platform)
        except Exception as e:
            logger.error(f"Failed to get due items: {e}")
            return []

    def get_upcoming(self, platform: str = None, days: int = 7) -> List[Dict]:
        """Get upcoming scheduled content for next N days."""
        today = date.today()
        end_date = today + timedelta(days=days)
        try:
            from db import get_upcoming_calendar_items
            return get_upcoming_calendar_items(today, end_date, platform=platform)
        except Exception as e:
            logger.error(f"Failed to get upcoming: {e}")
            return []

    def update_status(self, calendar_id: int, status: str,
                     video_run_id: int = None, social_post_id: int = None,
                     notes: str = None):
        """Update calendar item status."""
        try:
            from db import update_calendar_status
            update_calendar_status(calendar_id, status, video_run_id=video_run_id, notes=notes)
            logger.info(f"Updated calendar {calendar_id} -> {status}")
        except Exception as e:
            logger.error(f"Failed to update calendar status: {e}")

    def mark_in_production(self, calendar_id: int):
        self.update_status(calendar_id, "in_production")

    def mark_posted(self, calendar_id: int, social_post_id: int = None):
        self.update_status(calendar_id, "posted", social_post_id=social_post_id)

    def mark_failed(self, calendar_id: int, error: str = None):
        self.update_status(calendar_id, "failed", notes=error)

    def get_calendar_view(self, start_date: date = None,
                           end_date: date = None) -> Dict[str, List[Dict]]:
        """
        Get calendar view organized by date.
        Returns dict: {date_string: [calendar_items]}
        """
        start_date = start_date or date.today()
        end_date = end_date or (start_date + timedelta(days=30))

        try:
            from db import get_calendar_view as db_get_calendar_view
            return db_get_calendar_view(start_date, end_date)
        except Exception as e:
            logger.error(f"Failed to get calendar view: {e}")
            return {}

    def get_stats(self) -> Dict:
        """Get calendar statistics."""
        try:
            from db import get_calendar_stats
            return get_calendar_stats()
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cal = ContentCalendar(project_id=1)

    print("📅 Calendar Stats:")
    stats = cal.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\n📅 Upcoming (next 7 days):")
    upcoming = cal.get_upcoming(days=7)
    for item in upcoming[:5]:
        print(f"  {item['scheduled_date']} [{item['platform']}] {item['title']}")
