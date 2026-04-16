#!/usr/bin/python3
"""
scripts/check_ab_results.py — Poll Facebook/TikTok Insights API to check A/B test CTR.

Usage:
    # Check all pending A/B tests (both platforms)
    python scripts/check_ab_results.py

    # Check only Facebook tests
    python scripts/check_ab_results.py --platform facebook

    # Check only tests older than 24 hours
    python scripts/check_ab_results.py --min-age-hours 24

    # Dry-run (don't update DB)
    python scripts/check_ab_results.py --dry-run

    # Verbose debug output
    python scripts/check_ab_results.py -v

Python API:
    from scripts.check_ab_results import ABCaptionChecker
    checker = ABCaptionChecker(dry_run=False)
    results = checker.run(platform="facebook")
    checker.report_to_telegram(results)
"""

import sys
import logging
import argparse
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ── Facebook Insights ───────────────────────────────────────────────────────────

class FacebookInsights:
    """Fetch Facebook Insights for a video post via Graph API."""

    GRAPH_API = "https://graph.facebook.com/v19.0"

    def __init__(self, access_token: str, page_id: str):
        self.access_token = access_token
        self.page_id = page_id
        self._session = None

    def _session(self):
        import requests
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _get(self, path: str, params: dict = None) -> Optional[dict]:
        """GET request to Graph API."""
        import requests
        params = params or {}
        params["access_token"] = self.access_token
        url = f"{self.GRAPH_API}/{path}"
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code >= 400:
                logger.warning(f"FB API {path} → {resp.status_code}: {resp.text[:200]}")
                return None
            return resp.json()
        except Exception as e:
            logger.error(f"FB API error for {path}: {e}")
            return None

    def get_video_insights(self, post_id: str) -> Optional[Dict]:
        """
        Get impressions, reach, and engagement for a video post.

        Returns:
            {
                "impressions": int,
                "reach": int,
                "engagements": int,
                "clicks": int,
                "ctr": float,  # clicks / impressions
            }
            or None on failure.
        """
        # Video insights: /{post-id}/insights?metric=video_impressions,video_views,
        #                 post_impressions,post_reach,post_engagements
        metrics = [
            "video_impressions",
            "video_views",
            "post_impressions",
            "post_reach",
            "post_engagements",
            "post_clicks",
        ]
        path = f"{self.page_id}_{post_id}/insights"
        params = {"metric": ",".join(metrics)}

        data = self._get(path, params)
        if data is None:
            # Try without page_id prefix
            data = self._get(f"{post_id}/insights", params)

        if data is None or "data" not in data:
            return None

        result = {}
        for entry in data.get("data", []):
            name = entry.get("name", "")
            values = entry.get("values", [])
            if values:
                result[name] = values[-1].get("value", 0)

        impressions = result.get("video_impressions") or result.get("post_impressions", 0)
        clicks = result.get("post_clicks", 0)
        reach = result.get("post_reach", 0)
        engagements = result.get("post_engagements", 0)
        views = result.get("video_views", 0)

        ctr = (clicks / impressions) if impressions else 0.0

        return {
            "impressions": int(impressions),
            "reach": int(reach),
            "engagements": int(engagements),
            "clicks": int(clicks),
            "views": int(views),
            "ctr": round(ctr, 6),
        }

    def get_page_access_token(self) -> Optional[str]:
        """Get long-lived page access token from user access token."""
        path = f"{self.page_id}?fields=access_token"
        data = self._get(path)
        if data and "access_token" in data:
            return data["access_token"]
        return self.access_token  # Fallback


# ── TikTok Insights ────────────────────────────────────────────────────────────

class TikTokInsights:
    """Fetch TikTok video insights via Marketing API."""

    API_BASE = "https://open.tiktokapis.com/v2"

    def __init__(self, access_token: str, advertiser_id: str):
        self.access_token = access_token
        self.advertiser_id = advertiser_id

    def _post(self, path: str, json_data: dict) -> Optional[dict]:
        """POST request to TikTok API."""
        import requests
        url = f"{self.API_BASE}/{path}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(url, json=json_data, headers=headers, timeout=30)
            if resp.status_code >= 400:
                logger.warning(f"TikTok API {path} → {resp.status_code}: {resp.text[:200]}")
                return None
            return resp.json()
        except Exception as e:
            logger.error(f"TikTok API error for {path}: {e}")
            return None

    def get_video_insights(self, video_id: str) -> Optional[Dict]:
        """
        Get video stats from TikTok.

        Returns:
            {
                "views": int,
                "likes": int,
                "comments": int,
                "shares": int,
                "ctr": float,  # clicks / views (click-through rate)
            }
            or None on failure.
        """
        # TikTok video insights — requires video/list query
        # The video_id from publish response is the video ID
        query = """
        query GetVideoStats($videoId: String!) {
          video(id: $videoId) {
            id
            view_count
            like_count
            comment_count
            share_count
          }
        }
        """
        # Try the rest/v2/video/query endpoint
        data = self._post("video/query/", {
            "advertiser_id": self.advertiser_id,
            "video_ids": [video_id],
            "fields": ["video_id", "view_count", "like_count", "comment_count", "share_count"],
        })

        if data is None:
            # Fallback: try basic stats endpoint
            return self._get_basic_stats(video_id)

        if data.get("data", {}).get("videos"):
            v = data["data"]["videos"][0]
            views = v.get("view_count", 0)
            clicks = v.get("like_count", 0) + v.get("comment_count", 0)
            ctr = (clicks / views) if views else 0.0
            return {
                "views": int(views),
                "likes": int(v.get("like_count", 0)),
                "comments": int(v.get("comment_count", 0)),
                "shares": int(v.get("share_count", 0)),
                "ctr": round(ctr, 6),
            }

        return None

    def _get_basic_stats(self, video_id: str) -> Optional[Dict]:
        """Try to get basic video stats via public endpoint."""
        import requests
        try:
            # Try user video list endpoint
            data = self._post("video/list/", {
                "advertiser_id": self.advertiser_id,
                "filters": {"video_ids": [video_id]},
                "fields": ["video_id", "view_count"],
            })
            if data and data.get("data", {}).get("videos"):
                v = data["data"]["videos"][0]
                views = v.get("view_count", 0)
                return {
                    "views": int(views),
                    "likes": 0,
                    "comments": 0,
                    "shares": 0,
                    "ctr": 0.0,
                }
        except Exception:
            pass
        return None


# ── CTR Calculator ─────────────────────────────────────────────────────────────

def compute_winner(ctr_a: Dict, ctr_b: Dict, platform: str) -> str:
    """
    Determine winner based on CTR.
    Higher CTR wins. Falls back to impressions tiebreaker.

    For Facebook: use clicks/impressions (ctr field)
    For TikTok: use views as proxy (ctr is likes+comments/views)
    """
    score_a = ctr_a.get("ctr", 0) or 0.0
    score_b = ctr_b.get("ctr", 0) or 0.0

    # Tiebreaker: total impressions/views
    imp_a = ctr_a.get("impressions", ctr_a.get("views", 0))
    imp_b = ctr_b.get("impressions", ctr_b.get("views", 0))

    # Normalise: prefer higher CTR, break ties by higher impressions
    if abs(score_a - score_b) < 0.0001:  # effectively equal
        winner = "a" if imp_a >= imp_b else "b"
        logger.info(f"  Tiebreaker: imp_a={imp_a}, imp_b={imp_b} → winner={winner}")
    else:
        winner = "a" if score_a > score_b else "b"

    return winner


# ── Main Checker ──────────────────────────────────────────────────────────────

class ABCaptionChecker:
    """
    Poll platform Insights APIs for pending A/B tests and update winners.

    Flow:
        1. Load pending ab_caption_tests from DB
        2. For each test with posted_at > min_age_hours:
           a. Poll platform Insights API for CTR
           b. Store CTR in ctr_a field
           c. Decide winner (higher CTR wins)
           d. Update DB with winner
    """

    def __init__(self, dry_run: bool = False, min_age_hours: int = 24):
        self.dry_run = dry_run
        self.min_age_hours = min_age_hours
        self._fb_client: Optional[FacebookInsights] = None
        self._tt_client: Optional[TikTokInsights] = None

    def run(self, platform: str = None) -> List[Dict]:
        """Run the A/B check for pending tests. Returns list of result dicts."""
        self._init_db()
        results: List[Dict] = []

        pending = self._get_pending_tests(platform)
        if not pending:
            logger.info(f"No pending A/B tests found (min_age={self.min_age_hours}h)")
            return results

        logger.info(f"Found {len(pending)} pending A/B tests to check")
        for test in pending:
            result = self._check_test(test)
            results.append(result)

        return results

    def report_to_telegram(self, results: List[Dict]) -> None:
        """Send summary of A/B check results to Telegram."""
        if self.dry_run:
            logger.info("[DRY-RUN] Telegram report skipped")
            return

        if not results:
            return

        ok = [r for r in results if r.get("winner")]
        failed = [r for r in results if not r.get("winner")]

        lines = ["📊 *A/B Caption Check Results*\n"]
        lines.append(f"Checked: {len(results)} | Winners: {len(ok)} | Errors: {len(failed)}\n")
        for r in results:
            platform = r.get("platform", "?")
            test_id = r.get("test_id")
            winner = r.get("winner", "???")
            ctr_a = r.get("ctr_a", {})
            ctr_b = r.get("ctr_b", {})
            if winner != "???":
                w_ctr = ctr_a.get("ctr", 0) if winner == "a" else ctr_b.get("ctr", 0)
                l_ctr = ctr_b.get("ctr", 0) if winner == "a" else ctr_a.get("ctr", 0)
                lines.append(
                    f"✅ Test #{test_id} [{platform}]: "
                    f"Winner = {winner.upper()} "
                    f"(CTR: {w_ctr*100:.2f}% vs {l_ctr*100:.2f}%)"
                )
            else:
                lines.append(f"❌ Test #{test_id} [{platform}]: {r.get('error', 'unknown error')}")

        msg = "\n".join(lines)
        self._send_telegram(msg)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _init_db(self):
        try:
            from db import init_db_full
            init_db_full()
        except Exception as e:
            logger.warning(f"DB init skipped: {e}")

    def _get_pending_tests(self, platform: str = None) -> List[Dict]:
        from db import get_ab_caption_tests_pending
        return get_ab_caption_tests_pending(platform=platform, limit=100)

    def _check_test(self, test: Dict) -> Dict:
        """Check a single A/B test. Returns result dict."""
        test_id = test["id"]
        platform = test["platform"]
        post_id = test.get("post_id")
        posted_at = test.get("posted_at")

        logger.info(f"  Checking test #{test_id} [{platform}] post_id={post_id}")

        if not post_id:
            logger.warning(f"  Test #{test_id}: no post_id yet (still pending posting)")
            return {
                **test,
                "test_id": test_id,
                "winner": None,
                "error": "no post_id",
            }

        if posted_at is None:
            logger.warning(f"  Test #{test_id}: no posted_at")
            return {**test, "test_id": test_id, "winner": None, "error": "no posted_at"}

        # Check minimum age
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.min_age_hours)
        posted_dt = posted_at
        if posted_dt.tzinfo is None:
            posted_dt = posted_dt.replace(tzinfo=timezone.utc)
        if posted_dt > cutoff:
            age_h = (datetime.now(timezone.utc) - posted_dt).total_seconds() / 3600
            logger.info(f"  Test #{test_id}: too young ({age_h:.1f}h < {self.min_age_hours}h) — skipping")
            return {
                **test,
                "test_id": test_id,
                "winner": None,
                "error": f"too young ({age_h:.1f}h)",
            }

        # Poll platform for CTR
        ctr_data = self._fetch_ctr(platform, post_id)
        if ctr_data is None:
            logger.warning(f"  Test #{test_id}: could not fetch CTR")
            return {
                **test,
                "test_id": test_id,
                "winner": None,
                "error": "ctr_fetch_failed",
            }

        logger.info(
            f"  Test #{test_id}: impressions={ctr_data.get('impressions', ctr_data.get('views'))}, "
            f"ctr={ctr_data.get('ctr', 0):.4f}"
        )

        # CTR for variant-B is not yet available (only variant-A is posted).
        # We store variant-A's CTR and mark status. Winner decision requires
        # variant-B to be posted separately in future.
        ctr_a = ctr_data
        ctr_b = {}  # Not yet available

        # Determine winner based on CTR — only set when one variant is 20%+ better
        winner = None
        score_a = ctr_a.get("ctr", 0) or 0.0
        score_b = ctr_b.get("ctr", 0) or 0.0

        if score_a > score_b * 1.2:
            winner = "a"
        elif score_b > score_a * 1.2:
            winner = "b"
        # else: winner = None (inconclusive — need more data)

        if self.dry_run:
            logger.info(f"  [DRY-RUN] Would update test #{test_id}: winner={winner}, ctr_a={ctr_a}")
            return {
                **test,
                "test_id": test_id,
                "winner": winner,
                "ctr_a": ctr_a,
                "ctr_b": ctr_b,
            }

        # Persist to DB
        try:
            from db import update_ab_caption_test
            update_ab_caption_test(
                test_id,
                ctr_a=ctr_a,
                ctr_b=ctr_b,
                winner=winner,
                status="winner_decided",
            )
            if winner:
                logger.info(f"  Test #{test_id}: winner={winner.upper()} (CTR {score_a:.4f} vs {score_b:.4f})")
            else:
                logger.info(f"  Test #{test_id}: inconclusive — CTR {score_a:.4f} vs {score_b:.4f} (need 20%% gap)")
        except Exception as e:
            logger.error(f"  Test #{test_id}: DB update failed: {e}")
            return {**test, "test_id": test_id, "winner": None, "error": str(e)}

        return {
            **test,
            "test_id": test_id,
            "winner": winner,
            "ctr_a": ctr_a,
            "ctr_b": ctr_b,
        }

    def _fetch_ctr(self, platform: str, post_id: str) -> Optional[Dict]:
        """Fetch CTR data from the appropriate platform API."""
        if platform == "facebook":
            client = self._get_fb_client()
            if client is None:
                return None
            time.sleep(0.5)  # Rate limit safety
            return client.get_video_insights(post_id)

        elif platform == "tiktok":
            client = self._get_tt_client()
            if client is None:
                return None
            time.sleep(0.5)
            return client.get_video_insights(post_id)

        else:
            logger.warning(f"Unknown platform: {platform}")
            return None

    def _get_fb_client(self) -> Optional[FacebookInsights]:
        if self._fb_client is not None:
            return self._fb_client
        try:
            from db import get_credential
            access_token = get_credential("facebook", "access_token")
            page_id = get_credential("facebook", "page_id")
            if not access_token or not page_id:
                logger.warning("Facebook credentials not found in DB")
                return None
            self._fb_client = FacebookInsights(access_token, page_id)
            return self._fb_client
        except Exception as e:
            logger.warning(f"Failed to init Facebook client: {e}")
            return None

    def _get_tt_client(self) -> Optional[TikTokInsights]:
        if self._tt_client is not None:
            return self._tt_client
        try:
            from db import get_credential
            access_token = get_credential("tiktok", "access_token")
            advertiser_id = get_credential("tiktok", "advertiser_id")
            if not access_token or not advertiser_id:
                logger.warning("TikTok credentials not found in DB")
                return None
            self._tt_client = TikTokInsights(access_token, advertiser_id)
            return self._tt_client
        except Exception as e:
            logger.warning(f"Failed to init TikTok client: {e}")
            return None

    def _send_telegram(self, message: str):
        try:
            from modules.pipeline.models import TechnicalConfig
            tech = TechnicalConfig.load()
            bot_token = tech.telegram.get("bot_token")
            chat_id = tech.telegram.get("chat_id")
            if not bot_token or not chat_id:
                logger.warning("Telegram not configured; printing message instead")
                print(message)
                return
            import urllib.request, urllib.parse
            encoded = urllib.parse.quote_plus(message)
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={chat_id}&text={encoded}&parse_mode=Markdown"
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("Telegram notification sent")
                else:
                    logger.warning(f"Telegram returned {resp.status}")
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")
            print(message)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check A/B caption test results via FB/TikTok Insights API"
    )
    parser.add_argument(
        "--platform", choices=["facebook", "tiktok"], default=None,
        help="Filter by platform (default: all)"
    )
    parser.add_argument(
        "--min-age-hours", type=int, default=24,
        help="Only check tests older than N hours (default: 24)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Poll APIs but do not update DB"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose debug logging"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("A/B CAPTION CHECKER — VP-030")
    logger.info("=" * 60)
    logger.info(f"  Platform     : {args.platform or 'all'}")
    logger.info(f"  Min age      : {args.min_age_hours}h")
    logger.info(f"  Dry run      : {args.dry_run}")

    checker = ABCaptionChecker(dry_run=args.dry_run, min_age_hours=args.min_age_hours)
    results = checker.run(platform=args.platform)

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("CHECK SUMMARY")
    logger.info("=" * 60)
    for r in results:
        test_id = r.get("test_id")
        platform = r.get("platform", "?")
        winner = r.get("winner", "???")
        if winner and winner != "???":
            ctr = r.get("ctr_a", {}).get("ctr", 0)
            logger.info(f"  ✅ #{test_id} [{platform}] winner={winner.upper()} CTR={ctr*100:.2f}%")
        else:
            logger.info(f"  ❌ #{test_id} [{platform}] {r.get('error', 'unknown')}")

    # Telegram summary
    if not args.dry_run:
        checker.report_to_telegram(results)
