"""
SheetsService - Wrapper around LocalDataService

Provides the interface expected by app.py while delegating
to LocalDataService for actual data operations.
"""

import logging
import re
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any

from local_data_service import LocalDataService
from db_service import DatabaseService
from ambassador_service import AmbassadorService

logger = logging.getLogger(__name__)


class SheetsService:
    """Service class that wraps LocalDataService with the interface expected by app.py."""

    def __init__(self):
        """Initialize the service with LocalDataService backend."""
        self.db_service = DatabaseService()
        self.local_service = LocalDataService(self.db_service)
        self.ambassador_service = AmbassadorService(self.db_service)
        logger.info("SheetsService initialized with LocalDataService backend")

    def _invalidate_cache(self) -> None:
        """Clear all cached data."""
        self.local_service.clear_cache()
        logger.info("Cache invalidated")

    def get_x_leaderboard(self, year: Optional[int] = None, month: Optional[int] = None) -> Tuple[List[Dict], int]:
        """Get X/Twitter leaderboard data.

        Args:
            year: Filter by year (None for current)
            month: Filter by month (None for current)

        Returns:
            Tuple of (leaderboard list, total impressions)
        """
        return self.local_service.get_x_leaderboard(year, month)

    def get_reddit_leaderboard(self, year: Optional[int] = None, month: Optional[int] = None) -> List[Dict]:
        """Get Reddit leaderboard data.

        Args:
            year: Filter by year (None for current)
            month: Filter by month (None for current)

        Returns:
            List of ambassador statistics
        """
        return self.local_service.get_reddit_leaderboard(year, month)

    def get_total_leaderboard(self, year: Optional[int] = None, month: Optional[int] = None) -> List[Dict]:
        """Get combined leaderboard from both X and Reddit.

        Args:
            year: Filter by year (None for current)
            month: Filter by month (None for current)

        Returns:
            List of combined ambassador statistics with x_views, reddit_views, total_views
        """
        raw_leaderboard = self.local_service.get_total_leaderboard(year, month)

        # Transform to expected format (x_impressions -> x_views for app.py compatibility)
        result = []
        for item in raw_leaderboard:
            result.append({
                'name': item['name'],
                'x_views': item.get('x_impressions', 0),
                'reddit_views': item.get('reddit_views', 0),
                'total_views': item.get('x_impressions', 0) + item.get('reddit_views', 0)
            })

        # Sort by total_views descending
        result.sort(key=lambda x: x['total_views'], reverse=True)
        return result

    def get_available_months(self) -> List[Tuple[int, int]]:
        """Get list of available months with data.

        Returns:
            List of (year, month) tuples, most recent first
        """
        return self.local_service.get_available_months()

    def get_x_daily_stats(self, year: int, month: int) -> Optional[Dict[str, List]]:
        """Get daily X stats for graphing.

        Args:
            year: Year to query
            month: Month to query

        Returns:
            Dictionary with 'dates' and 'impressions' lists, or None if no data
        """
        return self.local_service.get_x_daily_stats(year, month)

    def get_reddit_daily_stats(self, year: int, month: int) -> Optional[Dict[str, List]]:
        """Get daily Reddit stats for graphing.

        Args:
            year: Year to query
            month: Month to query

        Returns:
            Dictionary with 'dates' and 'scores' lists, or None if no data
        """
        return self.local_service.get_reddit_daily_stats(year, month)

    def get_daily_impressions_for_graph(self, year: int, month: int) -> Optional[Dict[str, List]]:
        """Get combined daily stats for the total leaderboard graph.

        Args:
            year: Year to query
            month: Month to query

        Returns:
            Dictionary with 'dates', 'x_impressions', 'reddit_views' lists, or None
        """
        return self.local_service.get_daily_impressions_for_graph(year, month)

    def add_content(
        self,
        content_url: str,
        ambassador: Optional[str] = None,
        discord_avatar_url: Optional[str] = None,
        submitter_discord_id: Optional[str] = None,
        submitter_username: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Add new content submission.

        Args:
            content_url: URL of the content (X or Reddit)
            ambassador: Ambassador name (optional - auto-detected from handle)
            discord_avatar_url: Discord avatar URL for submitter (optional)
            submitter_discord_id: Discord user ID of submitter (optional)
            submitter_username: Discord username of submitter (optional)

        Returns:
            Tuple of (success, message)
        """
        return self.local_service.add_content(
            content_url,
            ambassador,
            discord_avatar_url,
            submitter_discord_id,
            submitter_username
        )

    def update_reddit_stats(self, year: Optional[int] = None, month: Optional[int] = None) -> Tuple[bool, str]:
        """Trigger Reddit stats refresh.

        Args:
            year: Year to refresh (None for current)
            month: Month to refresh (None for current)

        Returns:
            Tuple of (success, message)
        """
        return self.local_service.update_reddit_stats(year, month)

    def resolve_ambassador_from_handle(self, handle: str, platform: str = 'x') -> Optional[str]:
        """Look up ambassador name from platform handle.

        Args:
            handle: Platform handle (X handle or Reddit username)
            platform: 'x' or 'reddit'

        Returns:
            Ambassador name or None if not found
        """
        return self.ambassador_service.resolve_ambassador_from_handle(handle, platform)

    def update_x_post_ambassador_from_handle(self, tweet_id: str, author_handle: str) -> Tuple[bool, str]:
        """Update X post's ambassador based on scraped author handle.

        Args:
            tweet_id: Tweet ID
            author_handle: Scraped author handle

        Returns:
            Tuple of (success, message)
        """
        result = self.ambassador_service.update_x_post_ambassador_from_handle(tweet_id, author_handle)
        if result[0]:
            self.local_service.clear_cache()
        return result

    def get_current_month_x_posts(self) -> List[Dict]:
        """Get X posts for current month that need scraping.

        Returns:
            List of post dictionaries with Tweet_URL and Ambassador keys
        """
        return self.ambassador_service.get_current_month_x_posts()

    def update_x_post_metrics(self, tweet_url: str, metrics: Dict) -> Tuple[bool, str]:
        """Update X post metrics from scraper.

        Args:
            tweet_url: Tweet URL
            metrics: Dictionary with impressions, likes, retweets, replies, date_posted, author_handle

        Returns:
            Tuple of (success, message)
        """
        result = self.ambassador_service.update_x_post_metrics(tweet_url, metrics)
        if result[0]:
            self.local_service.clear_cache()
        return result

    def record_daily_snapshot(self) -> Tuple[bool, str]:
        """Record a daily snapshot of current totals.

        Returns:
            Tuple of (success, message)
        """
        return self.local_service.record_daily_snapshot()

    def get_daily_views(self, year: int, month: int) -> Optional[Dict[str, List]]:
        """Get daily views (change per day) from cumulative snapshots.

        Args:
            year: Year to query
            month: Month to query

        Returns:
            Dictionary with 'dates' and 'daily_views' lists, or None if no data
        """
        return self.local_service.get_daily_views(year, month)

    def export_daily_snapshots_csv(self, year: int, month: int) -> Optional[str]:
        """Export daily snapshots to CSV format.

        Args:
            year: Year to export
            month: Month to export

        Returns:
            CSV string or None if no data
        """
        return self.local_service.export_daily_snapshots_csv(year, month)
