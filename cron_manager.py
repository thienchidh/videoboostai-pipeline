"""
cron_manager.py — VideoBoostAI Scheduler

Manages recurring video generation jobs using the `schedule` package.
Jobs persist to ~/.openclaw/workspace-videopipeline/.cron_jobs.json
"""

import os
import json
import time
import logging
import threading
from pathlib import Path
from typing import Callable, Optional

try:
    import schedule
except ImportError:
    import subprocess
    subprocess.check_call(["pip", "install", "schedule", "-q"])
    import schedule

logger = logging.getLogger(__name__)

JOBS_FILE = Path.home() / ".openclaw/workspace-videopipeline/.cron_jobs.json"


class CronManager:
    """Manages scheduled jobs for video pipeline."""

    def __init__(self, config_path: Optional[str] = None):
        self.jobs = {}  # name -> schedule.Job
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._load_jobs()
        if config_path:
            self.load_from_config(config_path)

    def add_job(self, name: str, schedule_str: str, func: Callable, *args, **kwargs) -> bool:
        """Register a recurring job.
        
        schedule_str examples:
            - "daily 09:00"     → run every day at 9am
            - "hourly"          → run every hour
            - "every 10 minutes" → run every 10 minutes
            - "every day at 09:00" → same as daily 09:00
        """
        try:
            job = self._schedule_job(schedule_str, func, *args, **kwargs)
            self.jobs[name] = {"job": job, "schedule": schedule_str, "args": args, "kwargs": kwargs}
            self._save_jobs()
            logger.info(f"✅ Job added: {name} ({schedule_str})")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to add job {name}: {e}")
            return False

    def _schedule_job(self, schedule_str: str, func: Callable, *args, **kwargs):
        """Parse schedule string and register job."""
        s = schedule_str.strip().lower()
        
        if s == "hourly":
            return schedule.every().hour.do(func, *args, **kwargs)
        elif s.startswith("every "):
            # "every 10 minutes", "every 30 seconds", etc.
            parts = s.split()
            if len(parts) >= 3:
                quantity = int(parts[1])
                unit = parts[2].rstrip("s")  # remove plural
                if unit == "minute":
                    return schedule.every(quantity).minutes.do(func, *args, **kwargs)
                elif unit == "second":
                    return schedule.every(quantity).seconds.do(func, *args, **kwargs)
                elif unit == "hour":
                    return schedule.every(quantity).hours.do(func, *args, **kwargs)
        elif s.startswith("daily") or "every day at" in s:
            # "daily 09:00" or "every day at 09:00"
            parts = s.split()
            if len(parts) >= 2:
                time_str = parts[-1] if ":" in parts[-1] else "09:00"
            else:
                time_str = "09:00"
            return schedule.every().day.at(time_str).do(func, *args, **kwargs)
        
        # Default: daily at 9am
        return schedule.every().day.at("09:00").do(func, *args, **kwargs)

    def remove_job(self, name: str) -> bool:
        if name in self.jobs:
            self.jobs[name]["job"].cancel()
            del self.jobs[name]
            self._save_jobs()
            logger.info(f"🗑 Job removed: {name}")
            return True
        return False

    def list_jobs(self) -> list:
        """Return list of job info dicts."""
        result = []
        for name, data in self.jobs.items():
            job = data["job"]
            result.append({
                "name": name,
                "schedule": data["schedule"],
                "next_run": str(job.next_run) if job.next_run else "N/A",
                "enabled": True
            })
        return result

    def run_pending(self):
        """Run any due jobs (call this frequently)."""
        schedule.run_pending()

    def start_loop(self, interval: float = 30.0):
        """Start background loop that checks for due jobs."""
        self._running = True
        
        def loop():
            while self._running:
                self.run_pending()
                time.sleep(interval)
        
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        logger.info("⏰ Scheduler loop started")

    def stop_loop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def load_from_config(self, config_path: str):
        """Load and register jobs from a video config file with scheduler section."""
        try:
            cfg = json.load(open(config_path))
            sched = cfg.get("scheduler", {})
            if not sched.get("enabled", False):
                logger.info("Scheduler disabled in config")
                return
            
            for job_def in sched.get("jobs", []):
                name = job_def.get("name", "unnamed")
                schedule_str = job_def.get("schedule", "daily 09:00")
                config_file = job_def.get("config", "")
                
                # Create job function
                def make_job(cfg_file):
                    def job():
                        self._run_video_pipeline(cfg_file)
                    return job
                
                self.add_job(name, schedule_str, make_job(config_file))
                
        except Exception as e:
            logger.error(f"Failed to load scheduler config: {e}")

    def _run_video_pipeline(self, config_path: str):
        """Run the video pipeline for a given config."""
        logger.info(f"🚀 Triggering video pipeline: {config_path}")
        try:
            # Import here to avoid circular imports
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from video_pipeline_v3 import VideoPipelineV3
            
            pipeline = VideoPipelineV3(config_path)
            result = pipeline.run()
            
            if result:
                logger.info(f"🎉 Pipeline complete: {result}")
                # Attempt social media publish (stubs)
                self._publish_to_social(result, config_path)
            else:
                logger.error("💥 Pipeline failed")
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            import traceback
            traceback.print_exc()

    def _publish_to_social(self, video_path: str, config_path: str):
        """Stub publish to social platforms."""
        try:
            import json
            cfg = json.load(open(config_path))
            title = cfg.get("video", {}).get("title", "Video")
            desc = cfg.get("video", {}).get("description", "")
            
            from modules.social import FacebookPublisher, TikTokPublisher
            FacebookPublisher().publish(video_path, title, desc)
            TikTokPublisher().publish(video_path, title, desc, tags=["video"])
        except Exception as e:
            logger.error(f"Social publish error: {e}")

    def _load_jobs(self):
        """Load persisted job metadata (schedule strings only, not live job objects)."""
        if JOBS_FILE.exists():
            try:
                data = json.load(open(JOBS_FILE))
                logger.info(f"Loaded {len(data)} persisted job(s)")
            except Exception:
                pass

    def _save_jobs(self):
        """Persist job metadata (schedule strings only)."""
        JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {name: {"schedule": d["schedule"]} for name, d in self.jobs.items()}
        json.dump(data, open(JOBS_FILE, "w"))
        logger.info(f"Saved {len(data)} job(s) to {JOBS_FILE}")

    def run_once(self, name: str) -> bool:
        """Manually trigger a job by name."""
        if name in self.jobs:
            job = self.jobs[name]["job"]
            # Cancel and run immediately
            job.cancel()
            logger.info(f"▶️  Running job: {name}")
            try:
                self.jobs[name]["kwargs"].get("func", lambda: None)()
            except Exception as e:
                logger.error(f"Job {name} error: {e}")
            return True
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    
    # Test: import only
    print("✅ CronManager imported OK")
    print(f"   Jobs file: {JOBS_FILE}")
    
    # Test scheduling
    cm = CronManager()
    cm.add_job("test_job", "every 30 seconds", lambda: print("🕐 test tick"))
    print("\n📋 Current jobs:", cm.list_jobs())