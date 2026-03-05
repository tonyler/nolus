"""
Reddit Scraper - Extracts engagement metrics from Reddit posts using Playwright.
Uses old.reddit.com for simple HTML structure.
Handles /s/ share links via browser redirect.
"""

import re
import time
import logging
from datetime import datetime
from typing import Tuple, Optional, Dict, List

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)


class RedditScraper:
    """Scrapes engagement metrics from Reddit posts using Playwright stealth."""

    def __init__(self):
        self._stealth = Stealth()
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 720},
            locale='en-US',
            timezone_id='America/New_York',
        )
        self._stealth.apply_stealth_sync(self._context)
        logger.info("Reddit scraper initialized (Playwright stealth)")

    def close_driver(self):
        try:
            self._context.close()
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass

    def _to_old_reddit(self, url: str) -> str:
        """Convert URL to old.reddit.com."""
        return re.sub(r'https?://(?:www\.)?reddit\.com', 'https://old.reddit.com', url)

    def _scrape_old_reddit(self, page) -> Optional[Dict]:
        """Extract metrics from an old.reddit.com post page."""
        metrics = {'score': 0, 'comments': 0, 'views': 0, 'date_posted': None, 'author': ''}

        # data-score on .thing div
        thing = page.query_selector('div.thing')
        if thing:
            score = thing.get_attribute('data-score')
            if score:
                try:
                    metrics['score'] = int(float(score))
                except ValueError:
                    pass

            comments = thing.get_attribute('data-comments-count')
            if comments:
                try:
                    metrics['comments'] = int(float(comments))
                except ValueError:
                    pass

            author = thing.get_attribute('data-author')
            if author:
                metrics['author'] = author

        # Fallback score from .score element
        if not metrics['score']:
            score_el = page.query_selector('.score.unvoted')
            if score_el:
                title = score_el.get_attribute('title')
                if title:
                    try:
                        metrics['score'] = int(title)
                    except ValueError:
                        pass

        # Fallback comments from link text
        if not metrics['comments']:
            comments_link = page.query_selector('a.comments')
            if comments_link:
                text = comments_link.inner_text()
                match = re.search(r'(\d+)', text)
                if match:
                    metrics['comments'] = int(match.group(1))

        # Date
        time_el = page.query_selector('time.live-timestamp')
        if time_el:
            dt = time_el.get_attribute('datetime')
            if dt:
                metrics['date_posted'] = dt

        return metrics if (metrics['score'] or metrics['comments']) else None

    def _scrape_new_reddit(self, page) -> Optional[Dict]:
        """Fallback: extract metrics from new reddit page."""
        metrics = {'score': 0, 'comments': 0, 'views': 0, 'date_posted': None, 'author': ''}

        # Score from upvote button or shreddit-post
        score_el = page.query_selector('shreddit-post')
        if score_el:
            score = score_el.get_attribute('score')
            if score:
                try:
                    metrics['score'] = int(score)
                except ValueError:
                    pass
            comment_count = score_el.get_attribute('comment-count')
            if comment_count:
                try:
                    metrics['comments'] = int(comment_count)
                except ValueError:
                    pass
            author = score_el.get_attribute('author')
            if author:
                metrics['author'] = author
            created = score_el.get_attribute('created-timestamp')
            if created:
                metrics['date_posted'] = created

        return metrics if (metrics['score'] or metrics['comments']) else None

    def scrape_post_metrics(self, url: str, timeout: int = 20) -> Tuple[Optional[Dict], str]:
        """Scrape engagement metrics from a single Reddit post.

        Args:
            url: Full URL to the Reddit post
            timeout: Page load timeout in seconds

        Returns:
            Tuple of (metrics_dict, message)
        """
        page = self._context.new_page()
        try:
            logger.info(f"Scraping Reddit post: {url}")

            is_share_link = '/s/' in url

            if is_share_link:
                # Let the browser follow the JS redirect
                page.goto(url, wait_until='domcontentloaded', timeout=timeout * 1000)
                page.wait_for_timeout(3000)
                final_url = page.url
                logger.info(f"Share link resolved to: {final_url}")

                if '/s/' in final_url:
                    return None, f"Share link did not redirect: {url}"

                # Now load via old.reddit for easy parsing
                old_url = self._to_old_reddit(final_url)
                page.goto(old_url, wait_until='domcontentloaded', timeout=timeout * 1000)
                page.wait_for_timeout(2000)
            else:
                old_url = self._to_old_reddit(url)
                page.goto(old_url, wait_until='domcontentloaded', timeout=timeout * 1000)
                page.wait_for_timeout(2000)

            # Check if we landed on old reddit or got redirected to new
            current = page.url
            if 'old.reddit.com' in current:
                metrics = self._scrape_old_reddit(page)
            else:
                metrics = self._scrape_new_reddit(page)

            if metrics:
                logger.info(f"Scraped: {metrics}")
                return metrics, f"Successfully scraped {url}"

            return None, f"Could not extract metrics from {url}"

        except PwTimeout:
            return None, f"Timeout loading {url}"
        except Exception as e:
            error_msg = f"Error scraping {url}: {e}"
            logger.error(error_msg)
            return None, error_msg
        finally:
            page.close()

    def scrape_multiple_posts(self, urls: List[str], delay: int = 3) -> List[Tuple[str, Optional[Dict], str]]:
        """Scrape metrics from multiple Reddit posts.

        Args:
            urls: List of Reddit post URLs
            delay: Delay in seconds between requests

        Returns:
            List of tuples: (url, metrics_or_none, message)
        """
        results = []
        for i, url in enumerate(urls):
            metrics, message = self.scrape_post_metrics(url)
            results.append((url, metrics, message))
            if i < len(urls) - 1:
                time.sleep(delay)
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    scraper = RedditScraper()
    test_url = "https://www.reddit.com/r/cosmosnetwork/s/160WNx2IfK"
    metrics, msg = scraper.scrape_post_metrics(test_url)
    print(f"\n{msg}")
    if metrics:
        print(f"Metrics: {metrics}")
    scraper.close_driver()
