"""
Database service for local SQLite storage.
Replaces direct Google Sheets reads for faster dashboard loading.
"""

import sqlite3
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from threading import Lock
import os

logger = logging.getLogger(__name__)


class DatabaseService:
    """Handles all local SQLite database operations."""

    def __init__(self, db_path: str = 'data/nolus_ambassador.db'):
        """Initialize database service.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._lock = Lock()
        self._ensure_db_directory()
        self._initialize_database()

    def _ensure_db_directory(self):
        """Create database directory if it doesn't exist."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"Created database directory: {db_dir}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_database(self):
        """Create database schema if it doesn't exist."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                # X/Twitter posts table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS x_posts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ambassador TEXT NOT NULL,
                        tweet_url TEXT NOT NULL,
                        tweet_id TEXT NOT NULL UNIQUE,
                        impressions INTEGER DEFAULT 0,
                        likes INTEGER DEFAULT 0,
                        retweets INTEGER DEFAULT 0,
                        replies INTEGER DEFAULT 0,
                        date_posted TEXT,
                        submitted_date TEXT,
                        month TEXT NOT NULL,
                        year INTEGER NOT NULL,
                        last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(tweet_id)
                    )
                ''')

                # Reddit posts table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS reddit_posts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ambassador TEXT NOT NULL,
                        url TEXT NOT NULL,
                        post_id TEXT NOT NULL UNIQUE,
                        score INTEGER DEFAULT 0,
                        comments INTEGER DEFAULT 0,
                        views INTEGER DEFAULT 0,
                        date_posted TEXT,
                        submitted_date TEXT,
                        month TEXT NOT NULL,
                        year INTEGER NOT NULL,
                        last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(post_id)
                    )
                ''')

                # Daily snapshots table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL UNIQUE,
                        x_impressions INTEGER DEFAULT 0,
                        x_likes INTEGER DEFAULT 0,
                        x_retweets INTEGER DEFAULT 0,
                        x_replies INTEGER DEFAULT 0,
                        x_posts INTEGER DEFAULT 0,
                        reddit_score INTEGER DEFAULT 0,
                        reddit_comments INTEGER DEFAULT 0,
                        reddit_views INTEGER DEFAULT 0,
                        reddit_posts INTEGER DEFAULT 0,
                        month TEXT NOT NULL,
                        year INTEGER NOT NULL,
                        last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(date)
                    )
                ''')

                # Create indexes for common queries
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_x_posts_month_year
                    ON x_posts(month, year)
                ''')

                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_x_posts_ambassador
                    ON x_posts(ambassador)
                ''')

                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_reddit_posts_month_year
                    ON reddit_posts(month, year)
                ''')

                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_reddit_posts_ambassador
                    ON reddit_posts(ambassador)
                ''')

                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_snapshots_month_year
                    ON snapshots(month, year)
                ''')

                # Ambassadors table for profile data
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS ambassadors (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        x_handle TEXT,
                        pfp_url TEXT,
                        last_updated TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                conn.commit()
                logger.info("Database schema initialized successfully")

            except Exception as e:
                logger.error(f"Error initializing database: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()

    # X Posts Methods

    def upsert_x_posts(self, posts: List[Dict[str, Any]]) -> int:
        """Insert or update X posts.

        Args:
            posts: List of post dictionaries with keys matching schema

        Returns:
            Number of posts updated
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                count = 0

                for post in posts:
                    cursor.execute('''
                        INSERT INTO x_posts (
                            ambassador, tweet_url, tweet_id, impressions, likes,
                            retweets, replies, date_posted, submitted_date, month, year
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(tweet_id) DO UPDATE SET
                            impressions = excluded.impressions,
                            likes = excluded.likes,
                            retweets = excluded.retweets,
                            replies = excluded.replies,
                            last_updated = CURRENT_TIMESTAMP
                    ''', (
                        post.get('ambassador'),
                        post.get('tweet_url'),
                        post.get('tweet_id'),
                        post.get('impressions', 0),
                        post.get('likes', 0),
                        post.get('retweets', 0),
                        post.get('replies', 0),
                        post.get('date_posted'),
                        post.get('submitted_date'),
                        post.get('month'),
                        post.get('year')
                    ))
                    count += 1

                conn.commit()
                logger.info(f"Upserted {count} X posts")
                return count

            except Exception as e:
                logger.error(f"Error upserting X posts: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()

    def get_x_posts(self, month: Optional[str] = None, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get X posts, optionally filtered by month/year.

        Args:
            month: Month name (e.g., 'Dec')
            year: Year (e.g., 2025)

        Returns:
            List of post dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if month and year:
                cursor.execute('''
                    SELECT * FROM x_posts
                    WHERE month = ? AND year = ?
                    ORDER BY date_posted DESC
                ''', (month, year))
            else:
                cursor.execute('SELECT * FROM x_posts ORDER BY date_posted DESC')

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        finally:
            conn.close()

    # Reddit Posts Methods

    def upsert_reddit_posts(self, posts: List[Dict[str, Any]]) -> int:
        """Insert or update Reddit posts.

        Args:
            posts: List of post dictionaries with keys matching schema

        Returns:
            Number of posts updated
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                count = 0

                for post in posts:
                    cursor.execute('''
                        INSERT INTO reddit_posts (
                            ambassador, url, post_id, score, comments,
                            views, date_posted, submitted_date, month, year
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(post_id) DO UPDATE SET
                            score = excluded.score,
                            comments = excluded.comments,
                            views = excluded.views,
                            last_updated = CURRENT_TIMESTAMP
                    ''', (
                        post.get('ambassador'),
                        post.get('url'),
                        post.get('post_id'),
                        post.get('score', 0),
                        post.get('comments', 0),
                        post.get('views', 0),
                        post.get('date_posted'),
                        post.get('submitted_date'),
                        post.get('month'),
                        post.get('year')
                    ))
                    count += 1

                conn.commit()
                logger.info(f"Upserted {count} Reddit posts")
                return count

            except Exception as e:
                logger.error(f"Error upserting Reddit posts: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()

    def get_reddit_posts(self, month: Optional[str] = None, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get Reddit posts, optionally filtered by month/year.

        Args:
            month: Month name (e.g., 'Dec')
            year: Year (e.g., 2025)

        Returns:
            List of post dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if month and year:
                cursor.execute('''
                    SELECT * FROM reddit_posts
                    WHERE month = ? AND year = ?
                    ORDER BY date_posted DESC
                ''', (month, year))
            else:
                cursor.execute('SELECT * FROM reddit_posts ORDER BY date_posted DESC')

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        finally:
            conn.close()

    # Snapshots Methods

    def upsert_snapshots(self, snapshots: List[Dict[str, Any]]) -> int:
        """Insert or update daily snapshots.

        Args:
            snapshots: List of snapshot dictionaries with keys matching schema

        Returns:
            Number of snapshots updated
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                count = 0

                for snapshot in snapshots:
                    cursor.execute('''
                        INSERT INTO snapshots (
                            date, x_impressions, x_likes, x_retweets, x_replies, x_posts,
                            reddit_score, reddit_comments, reddit_views, reddit_posts,
                            month, year
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(date) DO UPDATE SET
                            x_impressions = excluded.x_impressions,
                            x_likes = excluded.x_likes,
                            x_retweets = excluded.x_retweets,
                            x_replies = excluded.x_replies,
                            x_posts = excluded.x_posts,
                            reddit_score = excluded.reddit_score,
                            reddit_comments = excluded.reddit_comments,
                            reddit_views = excluded.reddit_views,
                            reddit_posts = excluded.reddit_posts,
                            last_updated = CURRENT_TIMESTAMP
                    ''', (
                        snapshot.get('date'),
                        snapshot.get('x_impressions', 0),
                        snapshot.get('x_likes', 0),
                        snapshot.get('x_retweets', 0),
                        snapshot.get('x_replies', 0),
                        snapshot.get('x_posts', 0),
                        snapshot.get('reddit_score', 0),
                        snapshot.get('reddit_comments', 0),
                        snapshot.get('reddit_views', 0),
                        snapshot.get('reddit_posts', 0),
                        snapshot.get('month'),
                        snapshot.get('year')
                    ))
                    count += 1

                conn.commit()
                logger.info(f"Upserted {count} snapshots")
                return count

            except Exception as e:
                logger.error(f"Error upserting snapshots: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()

    def get_snapshots(self, month: Optional[str] = None, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get snapshots, optionally filtered by month/year.

        Args:
            month: Month name (e.g., 'Dec')
            year: Year (e.g., 2025)

        Returns:
            List of snapshot dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if month and year:
                cursor.execute('''
                    SELECT * FROM snapshots
                    WHERE month = ? AND year = ?
                    ORDER BY date ASC
                ''', (month, year))
            else:
                cursor.execute('SELECT * FROM snapshots ORDER BY date ASC')

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        finally:
            conn.close()

    def update_x_post_ambassador(self, tweet_id: str, ambassador: str) -> bool:
        """Update ambassador for an X post.

        Args:
            tweet_id: Tweet ID
            ambassador: New ambassador name

        Returns:
            True if updated, False otherwise
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE x_posts SET ambassador = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE tweet_id = ?
                ''', (ambassador, tweet_id))
                conn.commit()
                updated = cursor.rowcount > 0
                if updated:
                    logger.info(f"Updated ambassador to '{ambassador}' for tweet {tweet_id}")
                return updated
            except Exception as e:
                logger.error(f"Error updating X post ambassador: {e}")
                conn.rollback()
                return False
            finally:
                conn.close()

    def update_reddit_post_ambassador(self, post_id: str, ambassador: str) -> bool:
        """Update ambassador for a Reddit post.

        Args:
            post_id: Reddit post ID
            ambassador: New ambassador name

        Returns:
            True if updated, False otherwise
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE reddit_posts SET ambassador = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE post_id = ?
                ''', (ambassador, post_id))
                conn.commit()
                updated = cursor.rowcount > 0
                if updated:
                    logger.info(f"Updated ambassador to '{ambassador}' for reddit post {post_id}")
                return updated
            except Exception as e:
                logger.error(f"Error updating Reddit post ambassador: {e}")
                conn.rollback()
                return False
            finally:
                conn.close()

    # Ambassador Methods

    def upsert_ambassador(self, name: str, x_handle: Optional[str] = None, pfp_url: Optional[str] = None) -> bool:
        """Insert or update an ambassador's profile data.

        Args:
            name: Ambassador name
            x_handle: X/Twitter handle (without @)
            pfp_url: Profile picture URL

        Returns:
            True if successful
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO ambassadors (name, x_handle, pfp_url)
                    VALUES (?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        x_handle = COALESCE(excluded.x_handle, ambassadors.x_handle),
                        pfp_url = COALESCE(excluded.pfp_url, ambassadors.pfp_url),
                        last_updated = CURRENT_TIMESTAMP
                ''', (name, x_handle, pfp_url))
                conn.commit()
                logger.info(f"Upserted ambassador: {name}")
                return True
            except Exception as e:
                logger.error(f"Error upserting ambassador: {e}")
                conn.rollback()
                return False
            finally:
                conn.close()

    def get_ambassador(self, name: str) -> Optional[Dict[str, Any]]:
        """Get ambassador profile data by name.

        Args:
            name: Ambassador name

        Returns:
            Ambassador dictionary or None
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM ambassadors WHERE name = ?', (name,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_all_ambassadors(self) -> List[Dict[str, Any]]:
        """Get all ambassadors with their profile data.

        Returns:
            List of ambassador dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM ambassadors ORDER BY name')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_ambassadors_map(self) -> Dict[str, Dict[str, Any]]:
        """Get a map of ambassador names to their profile data.

        Returns:
            Dictionary mapping name -> {x_handle, pfp_url}
        """
        ambassadors = self.get_all_ambassadors()
        return {amb['name']: amb for amb in ambassadors}

    def get_database_stats(self) -> Dict[str, Any]:
        """Get statistics about database contents.

        Returns:
            Dictionary with table counts and last update times
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) as count FROM x_posts')
            x_count = cursor.fetchone()['count']

            cursor.execute('SELECT COUNT(*) as count FROM reddit_posts')
            reddit_count = cursor.fetchone()['count']

            cursor.execute('SELECT COUNT(*) as count FROM snapshots')
            snapshot_count = cursor.fetchone()['count']

            cursor.execute('SELECT MAX(last_updated) as last_update FROM x_posts')
            x_last_update = cursor.fetchone()['last_update']

            cursor.execute('SELECT MAX(last_updated) as last_update FROM reddit_posts')
            reddit_last_update = cursor.fetchone()['last_update']

            cursor.execute('SELECT MAX(last_updated) as last_update FROM snapshots')
            snapshot_last_update = cursor.fetchone()['last_update']

            return {
                'x_posts_count': x_count,
                'reddit_posts_count': reddit_count,
                'snapshots_count': snapshot_count,
                'x_posts_last_update': x_last_update,
                'reddit_posts_last_update': reddit_last_update,
                'snapshots_last_update': snapshot_last_update
            }

        finally:
            conn.close()
