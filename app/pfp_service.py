"""
Profile Picture Service - Fetches and caches profile pictures from X/Twitter
Uses unavatar.io as a proxy service (no API key required)
"""

import logging
import requests
import threading
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from urllib.parse import quote

logger = logging.getLogger(__name__)


class ProfilePictureService:
    """Service for fetching and caching profile pictures from X/Twitter."""

    UNAVATAR_BASE = "https://unavatar.io/twitter"
    CACHE_TTL_HOURS = 24
    REQUEST_TIMEOUT = 5

    def __init__(self, db_service=None):
        """Initialize the profile picture service.

        Args:
            db_service: Database service for persistent storage
        """
        self.db_service = db_service
        self._memory_cache: Dict[str, tuple] = {}  # name -> (url, timestamp)
        self._cache_lock = threading.Lock()
        logger.info("ProfilePictureService initialized")

    def _get_unavatar_url(self, x_handle: str) -> str:
        """Get the unavatar.io URL for an X handle.

        Args:
            x_handle: X/Twitter handle (without @)

        Returns:
            Profile picture URL from unavatar.io
        """
        handle = x_handle.lstrip('@').lower()
        return f"{self.UNAVATAR_BASE}/{quote(handle)}?fallback=false"

    def _is_cache_valid(self, timestamp: datetime) -> bool:
        """Check if a cached entry is still valid."""
        return datetime.now() - timestamp < timedelta(hours=self.CACHE_TTL_HOURS)

    def get_pfp_url(self, name: str, x_handle: Optional[str] = None) -> Optional[str]:
        """Get profile picture URL for an ambassador.

        Args:
            name: Ambassador name
            x_handle: X/Twitter handle (optional, will try to use name if not provided)

        Returns:
            Profile picture URL or None
        """
        with self._cache_lock:
            if name in self._memory_cache:
                url, timestamp = self._memory_cache[name]
                if self._is_cache_valid(timestamp):
                    return url

        if self.db_service:
            ambassador = self.db_service.get_ambassador(name)
            if ambassador and ambassador.get('pfp_url'):
                with self._cache_lock:
                    self._memory_cache[name] = (ambassador['pfp_url'], datetime.now())
                return ambassador['pfp_url']
            if ambassador and ambassador.get('x_handle'):
                x_handle = ambassador['x_handle']

        handle = x_handle or name
        pfp_url = self._get_unavatar_url(handle)

        with self._cache_lock:
            self._memory_cache[name] = (pfp_url, datetime.now())

        if self.db_service and x_handle:
            self.db_service.upsert_ambassador(name, x_handle=x_handle, pfp_url=pfp_url)

        return pfp_url

    def get_pfp_urls_batch(self, ambassadors: List[Dict]) -> Dict[str, str]:
        """Get profile picture URLs for multiple ambassadors.

        Args:
            ambassadors: List of ambassador dictionaries with 'name' key

        Returns:
            Dictionary mapping name -> profile picture URL
        """
        result = {}
        for amb in ambassadors:
            name = amb.get('name', '')
            if name:
                x_handle = amb.get('x_handle')
                result[name] = self.get_pfp_url(name, x_handle)
        return result

    def update_ambassador_handle(self, name: str, x_handle: str) -> bool:
        """Update an ambassador's X handle and refresh their profile picture.

        Args:
            name: Ambassador name
            x_handle: X/Twitter handle

        Returns:
            True if successful
        """
        pfp_url = self._get_unavatar_url(x_handle)

        with self._cache_lock:
            self._memory_cache[name] = (pfp_url, datetime.now())

        if self.db_service:
            return self.db_service.upsert_ambassador(name, x_handle=x_handle, pfp_url=pfp_url)

        return True

    def clear_cache(self, name: Optional[str] = None):
        """Clear profile picture cache.

        Args:
            name: Optional ambassador name to clear. If None, clears all.
        """
        with self._cache_lock:
            if name:
                self._memory_cache.pop(name, None)
            else:
                self._memory_cache.clear()
        logger.info(f"PFP cache cleared: {name or 'all'}")


pfp_service: Optional[ProfilePictureService] = None


def get_pfp_service(db_service=None) -> ProfilePictureService:
    """Get or create the singleton profile picture service."""
    global pfp_service
    if pfp_service is None:
        pfp_service = ProfilePictureService(db_service)
    return pfp_service
