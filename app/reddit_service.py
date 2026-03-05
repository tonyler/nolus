"""
Reddit API service - Fetches engagement metrics from Reddit posts.
Uses Reddit's official OAuth API (free tier).
"""

import re
import logging
from datetime import datetime
from typing import Tuple, Optional, Dict, List
import time
import os

import requests

logger = logging.getLogger(__name__)


class RedditService:
    """Fetches Reddit post metrics via the official API."""

    def __init__(self):
        self._client_id = os.getenv('REDDIT_CLIENT_ID', '')
        self._client_secret = os.getenv('REDDIT_CLIENT_SECRET', '')
        self._user_agent = 'NolusDashboard/1.0'
        self._token = None
        self._token_expires = 0

        if not self._client_id or not self._client_secret:
            logger.warning("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set")

        logger.info("RedditService initialized")

    def _authenticate(self) -> bool:
        """Get OAuth token using client credentials."""
        now = time.time()
        if self._token and now < self._token_expires:
            return True

        try:
            resp = requests.post(
                'https://www.reddit.com/api/v1/access_token',
                auth=(self._client_id, self._client_secret),
                data={'grant_type': 'client_credentials'},
                headers={'User-Agent': self._user_agent},
                timeout=10,
            )

            if resp.status_code != 200:
                logger.error(f"Reddit auth failed: {resp.status_code} {resp.text[:200]}")
                return False

            data = resp.json()
            self._token = data['access_token']
            self._token_expires = now + data.get('expires_in', 3600) - 60
            logger.info("Reddit OAuth token acquired")
            return True
        except Exception as e:
            logger.error(f"Reddit auth error: {e}")
            return False

    def _api_get(self, endpoint: str) -> Optional[Dict]:
        """Make authenticated GET request to oauth.reddit.com."""
        if not self._authenticate():
            return None

        try:
            resp = requests.get(
                f'https://oauth.reddit.com{endpoint}',
                headers={
                    'Authorization': f'Bearer {self._token}',
                    'User-Agent': self._user_agent,
                },
                timeout=15,
            )

            if resp.status_code != 200:
                logger.warning(f"Reddit API {resp.status_code}: {endpoint}")
                return None

            return resp.json()
        except Exception as e:
            logger.error(f"Reddit API error: {e}")
            return None

    def _extract_post_id(self, url: str) -> Optional[str]:
        """Extract Reddit post ID (t3_ format) from various URL formats."""
        # /comments/{id}
        match = re.search(r'/comments/(\w+)', url)
        if match:
            return match.group(1)

        # redd.it/{id}
        match = re.search(r'redd\.it/(\w+)', url)
        if match:
            return match.group(1)

        # /s/{id} share links - ID is not the post ID, need API lookup
        # These will be resolved by fetching the URL info
        return None

    def fetch_post_metrics(self, url: str) -> Tuple[Optional[Dict], str]:
        """Fetch engagement metrics for a single Reddit post.

        Args:
            url: Full URL to the Reddit post

        Returns:
            Tuple of (metrics_dict, message)
        """
        try:
            logger.info(f"Fetching Reddit metrics: {url}")

            post_id = self._extract_post_id(url)

            if post_id:
                data = self._api_get(f'/api/info?id=t3_{post_id}')
            else:
                # For share links or unknown formats, try fetching URL info
                data = self._api_get(f'/api/info?url={url}')

            if not data:
                return None, f"No API response for {url}"

            children = data.get('data', {}).get('children', [])
            if not children:
                return None, f"Post not found: {url}"

            post = children[0].get('data', {})
            created_utc = post.get('created_utc', 0)
            date_posted = datetime.utcfromtimestamp(created_utc).isoformat() if created_utc else None

            metrics = {
                'score': int(post.get('score', 0)),
                'comments': int(post.get('num_comments', 0)),
                'views': int(post.get('view_count') or 0),
                'date_posted': date_posted,
                'author': post.get('author', ''),
            }

            logger.info(f"Fetched: {metrics}")
            return metrics, f"Successfully fetched {url}"

        except Exception as e:
            error_msg = f"Error fetching {url}: {e}"
            logger.error(error_msg)
            return None, error_msg

    def fetch_multiple_posts(self, urls: List[str], delay: int = 1) -> List[Tuple[str, Optional[Dict], str]]:
        """Fetch metrics for multiple Reddit posts.

        Args:
            urls: List of Reddit post URLs
            delay: Delay in seconds between requests

        Returns:
            List of tuples: (url, metrics_or_none, message)
        """
        results = []
        for i, url in enumerate(urls):
            metrics, message = self.fetch_post_metrics(url)
            results.append((url, metrics, message))
            if i < len(urls) - 1:
                time.sleep(delay)
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    service = RedditService()
    test_url = "https://www.reddit.com/r/cosmosnetwork/comments/1iih8h3/nolus_the_future_of_cosmos_defi/"
    metrics, msg = service.fetch_post_metrics(test_url)
    print(f"\n{msg}")
    if metrics:
        print(f"Metrics: {metrics}")
