"""
Discord Bot for Nolus Ambassador Dashboard

Monitors specific Discord channels for X and Reddit links,
extracts them, and saves to the database using LocalDataService.
Schedules scraping of all saved posts every 4 hours.
"""

import os
import re
import sys
import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional, Tuple, List, Dict

import discord
from discord import app_commands
from discord.ext import commands, tasks

# Add app directory to path for imports
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from local_data_service import LocalDataService
from db_service import DatabaseService
from config_loader import get_config
from ambassador_service import AmbassadorService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load configuration
config = get_config()


def _validate_discord_config() -> Tuple[int, int]:
    """Validate Discord configuration and return channel IDs.

    Returns:
        Tuple of (x_channel_id, reddit_channel_id)

    Raises:
        ValueError: If configuration is invalid or missing
    """
    x_channel_id = config.get('discord.x_channel_id')
    reddit_channel_id = config.get('discord.reddit_channel_id')

    # Required fields
    if x_channel_id is None:
        raise ValueError("Missing required config field: discord.x_channel_id")
    if reddit_channel_id is None:
        raise ValueError("Missing required config field: discord.reddit_channel_id")

    # Validate types
    if not isinstance(x_channel_id, int):
        raise ValueError("discord.x_channel_id must be an integer")

    if not isinstance(reddit_channel_id, int):
        raise ValueError("discord.reddit_channel_id must be an integer")

    return x_channel_id, reddit_channel_id


# Validate config and get channel IDs
try:
    X_CHANNEL_ID, REDDIT_CHANNEL_ID = _validate_discord_config()
except ValueError as e:
    logger.error(f"Invalid Discord configuration: {e}")
    raise

logger.info(f"Discord channels configured - X: {X_CHANNEL_ID}, Reddit: {REDDIT_CHANNEL_ID}")

# URL patterns with length limits for safety
X_URL_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:twitter\.com|x\.com)/(?:\w{1,50}/status/\d{10,20}|i(?:/web)?/status/\d{10,20})'
)
REDDIT_URL_PATTERN = re.compile(r'https?://(?:www\.)?(?:reddit\.com/r/\w{1,50}/(?:comments|s)/\w{5,20}|reddit\.com/user/\w{1,50}/comments/\w{5,10}|redd\.it/\w{5,10})(?:[/?#][^\s]*)?')


class NolusBot(commands.Bot):
    """Discord bot for handling ambassador content submissions."""

    def __init__(self):
        """Initialize the Discord bot with required intents."""
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.guilds = True

        super().__init__(
            command_prefix='!',
            intents=intents,
            description='Nolus Ambassador Content Bot',
            case_insensitive=True,
            help_command=None
        )

        # Initialize services
        self.db_service = DatabaseService()
        self.local_service = LocalDataService(self.db_service)
        self.ambassador_service = AmbassadorService(self.db_service)

        # Rate limiting: track submission timestamps per user
        self.user_submission_timestamps: Dict[int, List[float]] = defaultdict(list)
        self.submissions_per_hour = 20
        self.rate_limit_window = 3600  # 1 hour in seconds

        # Scraper state
        self.scraper = None
        self.scrape_lock = False

    def _check_rate_limit(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """Check if user has exceeded rate limits.

        Args:
            user_id: Discord user ID

        Returns:
            Tuple of (is_allowed, error_message)
        """
        now = datetime.now().timestamp()
        timestamps = self.user_submission_timestamps[user_id]

        # Remove old timestamps outside the window
        timestamps[:] = [ts for ts in timestamps if now - ts < self.rate_limit_window]

        if len(timestamps) >= self.submissions_per_hour:
            return False, f"Rate limit exceeded. Max {self.submissions_per_hour} submissions per hour."

        timestamps.append(now)
        return True, None

    def _extract_urls(self, content: str, platform: str) -> List[str]:
        """Extract URLs from message content based on platform.

        Args:
            content: Message content
            platform: 'x' or 'reddit'

        Returns:
            List of extracted URLs
        """
        pattern = X_URL_PATTERN if platform == 'x' else REDDIT_URL_PATTERN
        return pattern.findall(content)

    async def on_ready(self):
        """Called when bot is ready and connected."""
        logger.info(f'Bot logged in as {self.user.name} (ID: {self.user.id})')
        logger.info(f'Connected to {len(self.guilds)} guilds')
        logger.info(f'Monitoring X channel: {X_CHANNEL_ID}')
        logger.info(f'Monitoring Reddit channel: {REDDIT_CHANNEL_ID}')

        # Start the scheduled scraping task
        if not self.scrape_posts_task.is_running():
            self.scrape_posts_task.start()
            logger.info("Started scheduled scraping task (every 4 hours)")

    async def on_error(self, event, *args, **kwargs):
        """Log errors and continue running."""
        logger.error(f"Error in {event}", exc_info=True)

    async def close(self):
        """Graceful shutdown."""
        logger.info("Bot shutting down...")
        await super().close()

    async def on_message(self, message: discord.Message):
        """Handle incoming messages."""
        try:
            # Ignore bot's own messages
            if message.author.bot:
                return

            # Check if message is in monitored channels
            if message.channel.id not in (X_CHANNEL_ID, REDDIT_CHANNEL_ID):
                return

            # Check rate limit
            is_allowed, rate_error = self._check_rate_limit(message.author.id)
            if not is_allowed:
                try:
                    await message.reply(rate_error)
                except discord.DiscordException as e:
                    logger.error(f"Failed to send rate limit message: {e}")
                return

            # Determine expected platform based on channel
            is_x_channel = message.channel.id == X_CHANNEL_ID
            platform = 'X' if is_x_channel else 'Reddit'
            platform_key = 'x' if is_x_channel else 'reddit'

            # Extract URLs based on channel type
            urls = self._extract_urls(message.content, platform_key)

            if not urls:
                # No relevant URLs found, skip silently
                return

            # Use Discord poster identity as fallback (and for Reddit attribution/PFP).
            submitter_name = message.author.display_name or message.author.name
            submitter_avatar = str(message.author.display_avatar.url) if message.author.display_avatar else None
            submitter_discord_id = str(message.author.id)
            submitter_username = message.author.name

            # Process each URL
            results = []
            for url in urls:
                success, msg = self.local_service.add_content(
                    url,
                    ambassador=submitter_name,
                    discord_avatar_url=submitter_avatar,
                    submitter_discord_id=submitter_discord_id,
                    submitter_username=submitter_username
                )
                results.append((url, success, msg))
                log_level = logging.INFO if success else logging.WARNING
                logger.log(
                    log_level,
                    f"Processed URL by {submitter_name} ({submitter_discord_id}): {url} - "
                    f"{'Success' if success else 'Failed'}: {msg}"
                )

            # Notify user about duplicates
            duplicates = [url for url, success, msg in results if not success and msg == "duplicate"]
            if duplicates:
                try:
                    await message.reply(
                        "This post was already submitted.",
                        delete_after=10
                    )
                except discord.DiscordException as e:
                    logger.error(f"Failed to send duplicate notice: {e}")

            # Only ping @everyone if at least one URL was successfully added
            has_success = any(success for _, success, _ in results)
            if has_success:
                try:
                    await message.channel.send("@everyone")
                except discord.DiscordException as e:
                    logger.error(f"Failed to send notification: {e}")

        except Exception as e:
            logger.error(f"Unexpected error in on_message: {e}", exc_info=True)

    @tasks.loop(hours=4)
    async def scrape_posts_task(self):
        """Scheduled task to scrape all posts every 4 hours."""
        if self.scrape_lock:
            logger.warning("Scrape task already running, skipping...")
            return

        self.scrape_lock = True
        logger.info("Starting scheduled scrape of all posts...")

        try:
            # Import scraper here to avoid circular imports
            from x_scraper import XScraper

            # Get all current month posts
            posts = self.ambassador_service.get_current_month_x_posts()
            if not posts:
                logger.info("No posts to scrape")
                return

            logger.info(f"Scraping {len(posts)} X posts...")

            # Initialize scraper
            scraper = XScraper(cookie_file=config.x_scraper_cookie_file)

            try:
                success_count = 0
                fail_count = 0

                for post in posts:
                    tweet_url = post.get('Tweet_URL', '')
                    if not tweet_url:
                        continue

                    try:
                        metrics, msg = scraper.scrape_tweet_metrics(tweet_url, timeout=15)
                        if metrics:
                            self.ambassador_service.update_x_post_metrics(tweet_url, metrics)
                            success_count += 1
                            logger.info(f"Scraped: {tweet_url}")
                        else:
                            fail_count += 1
                            logger.warning(f"Failed to scrape {tweet_url}: {msg}")
                    except Exception as e:
                        fail_count += 1
                        logger.error(f"Error scraping {tweet_url}: {e}")

                    # Small delay between requests
                    import asyncio
                    await asyncio.sleep(5)

                logger.info(f"Scrape complete: {success_count} success, {fail_count} failed")

            finally:
                scraper.close_driver()

        except Exception as e:
            logger.error(f"Error in scheduled scrape task: {e}", exc_info=True)
        finally:
            self.scrape_lock = False

    @scrape_posts_task.before_loop
    async def before_scrape_task(self):
        """Wait for bot to be ready before starting scrape task."""
        await self.wait_until_ready()

    async def setup_hook(self):
        """Setup commands when bot starts."""
        # Prefix command (!scrape)
        @self.command(name='scrape')
        @commands.has_permissions(administrator=True)
        async def scrape_command(ctx):
            """Admin command to trigger manual scrape without affecting 4-hour schedule."""
            await ctx.send("Starting manual scrape...")
            self.loop.create_task(self._run_scrape(ctx.channel))

        @scrape_command.error
        async def scrape_error(ctx, error):
            if isinstance(error, commands.MissingPermissions):
                await ctx.send("You need administrator permissions to use this command.")

        # Slash command (/scrape)
        @self.tree.command(name='scrape', description='Manually trigger post scraping (admin only)')
        @app_commands.checks.has_permissions(administrator=True)
        async def scrape_slash(interaction: discord.Interaction):
            """Slash command to trigger manual scrape without affecting 4-hour schedule."""
            await interaction.response.send_message("Starting manual scrape...", ephemeral=True)
            self.loop.create_task(self._run_scrape_with_followup(interaction))

        @scrape_slash.error
        async def scrape_slash_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            if isinstance(error, app_commands.MissingPermissions):
                await interaction.response.send_message(
                    "You need administrator permissions to use this command.",
                    ephemeral=True
                )

        # Sync slash commands with Discord
        await self.tree.sync()
        logger.info("Slash commands synced")

    async def _run_scrape(self, channel):
        """Run scrape and report results to channel. Always executes regardless of lock."""
        logger.info("Manual scrape triggered by admin")

        try:
            from x_scraper import XScraper

            posts = self.ambassador_service.get_current_month_x_posts()
            if not posts:
                await channel.send("No posts to scrape.")
                return

            await channel.send(f"Scraping {len(posts)} posts...")

            scraper = XScraper(cookie_file=config.x_scraper_cookie_file)

            try:
                success_count = 0
                fail_count = 0

                for post in posts:
                    tweet_url = post.get('Tweet_URL', '')
                    if not tweet_url:
                        continue

                    try:
                        metrics, msg = scraper.scrape_tweet_metrics(tweet_url, timeout=15)
                        if metrics:
                            self.ambassador_service.update_x_post_metrics(tweet_url, metrics)
                            success_count += 1
                            logger.info(f"Scraped: {tweet_url}")
                        else:
                            fail_count += 1
                            logger.warning(f"Failed to scrape {tweet_url}: {msg}")
                    except Exception as e:
                        fail_count += 1
                        logger.error(f"Error scraping {tweet_url}: {e}")

                    import asyncio
                    await asyncio.sleep(5)

                await channel.send(f"Scrape complete: {success_count} success, {fail_count} failed")
                logger.info(f"Manual scrape complete: {success_count} success, {fail_count} failed")

            finally:
                scraper.close_driver()

        except Exception as e:
            logger.error(f"Error in manual scrape: {e}", exc_info=True)
            await channel.send(f"Scrape error: {str(e)}")

    async def _run_scrape_with_followup(self, interaction: discord.Interaction):
        """Run scrape and report results via interaction followup. For slash commands."""
        logger.info("Manual scrape triggered by admin (slash command)")

        try:
            from x_scraper import XScraper

            posts = self.ambassador_service.get_current_month_x_posts()
            if not posts:
                await interaction.followup.send("No posts to scrape.", ephemeral=True)
                return

            await interaction.followup.send(f"Scraping {len(posts)} posts...", ephemeral=True)

            scraper = XScraper(cookie_file=config.x_scraper_cookie_file)

            try:
                success_count = 0
                fail_count = 0

                for post in posts:
                    tweet_url = post.get('Tweet_URL', '')
                    if not tweet_url:
                        continue

                    try:
                        metrics, msg = scraper.scrape_tweet_metrics(tweet_url, timeout=15)
                        if metrics:
                            self.ambassador_service.update_x_post_metrics(tweet_url, metrics)
                            success_count += 1
                            logger.info(f"Scraped: {tweet_url}")
                        else:
                            fail_count += 1
                            logger.warning(f"Failed to scrape {tweet_url}: {msg}")
                    except Exception as e:
                        fail_count += 1
                        logger.error(f"Error scraping {tweet_url}: {e}")

                    import asyncio
                    await asyncio.sleep(5)

                await interaction.followup.send(f"Scrape complete: {success_count} success, {fail_count} failed", ephemeral=True)
                logger.info(f"Manual scrape complete: {success_count} success, {fail_count} failed")

            finally:
                scraper.close_driver()

        except Exception as e:
            logger.error(f"Error in manual scrape: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"Scrape error: {str(e)}", ephemeral=True)
            except Exception:
                pass  # Followup may have expired


def run_bot():
    """Run the Discord bot."""
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        logger.error("DISCORD_BOT_TOKEN environment variable not set!")
        raise ValueError("DISCORD_BOT_TOKEN environment variable is required")

    bot = NolusBot()
    bot.run(token)


if __name__ == '__main__':
    run_bot()
