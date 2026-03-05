#!/usr/bin/env python3
"""
One-time script to backfill missed Discord submissions.

Reads message history from the X and Reddit channels and saves any URLs
that aren't already in the database.

Usage:
    python backfill_discord.py [--limit 1000] [--dry-run]
"""

import sys
import os
import re
import asyncio
import argparse
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import discord
from local_data_service import LocalDataService
from db_service import DatabaseService
from config_loader import get_config

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)-8s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Same patterns as the bot
X_URL_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:twitter\.com|x\.com)/(?:\w{1,50}/status/\d{10,20}|i(?:/web)?/status/\d{10,20})'
)
REDDIT_URL_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:reddit\.com/r/\w{1,50}/(?:comments|s)/\w{5,20}|reddit\.com/user/\w{1,50}/comments/\w{5,10}|redd\.it/\w{5,10})(?:[/?#][^\s]*)?'
)


async def backfill(limit: int, dry_run: bool):
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        logger.error("DISCORD_BOT_TOKEN not set")
        sys.exit(1)

    config = get_config()
    x_channel_id = config.get('discord.x_channel_id')
    reddit_channel_id = config.get('discord.reddit_channel_id')

    db_service = DatabaseService()
    local_service = LocalDataService(db_service)

    # Build sets of already-saved URLs to skip duplicates
    existing_x = {p['tweet_url'] for p in db_service.get_x_posts()}
    existing_reddit = {p['url'] for p in db_service.get_reddit_posts()}
    logger.info(f"Existing DB: {len(existing_x)} X posts, {len(existing_reddit)} Reddit posts")

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    results = {'x_added': 0, 'x_skipped': 0, 'reddit_added': 0, 'reddit_skipped': 0, 'errors': 0}

    @client.event
    async def on_ready():
        logger.info(f"Logged in as {client.user} — starting backfill (limit={limit}, dry_run={dry_run})")

        now = datetime.now(tz=timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        logger.info(f"Only scanning messages from {month_start.strftime('%Y-%m-%d')} onwards")

        for channel_id, platform, pattern, existing in [
            (x_channel_id,      'x',      X_URL_PATTERN,      existing_x),
            (reddit_channel_id, 'reddit', REDDIT_URL_PATTERN,  existing_reddit),
        ]:
            channel = client.get_channel(channel_id)
            if not channel:
                logger.error(f"Could not find channel {channel_id}")
                continue

            logger.info(f"Scanning #{channel.name} ({platform.upper()}) ...")
            msg_count = 0

            async for message in channel.history(limit=limit, after=month_start, oldest_first=True):
                if message.author.bot:
                    continue

                msg_count += 1
                urls = pattern.findall(message.content)
                if not urls:
                    continue

                submitter_name = message.author.display_name or message.author.name
                submitter_avatar = str(message.author.display_avatar.url) if message.author.display_avatar else None
                submitter_discord_id = str(message.author.id)
                submitter_username = message.author.name
                # Use message timestamp for date context
                msg_time = message.created_at.strftime('%Y-%m-%d %H:%M:%S')

                for url in urls:
                    already_saved = url in existing
                    status = "SKIP" if already_saved else ("DRY " if dry_run else "ADD ")
                    logger.info(f"  [{status}] {msg_time} @{submitter_name}: {url}")

                    if already_saved:
                        results[f'{platform}_skipped'] += 1
                        continue

                    if not dry_run:
                        success, msg = local_service.add_content(
                            url,
                            ambassador=submitter_name,
                            discord_avatar_url=submitter_avatar,
                            submitter_discord_id=submitter_discord_id,
                            submitter_username=submitter_username
                        )
                        if success:
                            existing.add(url)  # prevent double-add within same run
                            results[f'{platform}_added'] += 1
                        else:
                            logger.warning(f"    Failed to save: {msg}")
                            results['errors'] += 1
                    else:
                        results[f'{platform}_added'] += 1  # count as "would add" in dry run

            logger.info(f"  Scanned {msg_count} messages in #{channel.name}")

        logger.info("")
        logger.info("=== Backfill complete ===")
        logger.info(f"  X      — added: {results['x_added']}, skipped: {results['x_skipped']}")
        logger.info(f"  Reddit — added: {results['reddit_added']}, skipped: {results['reddit_skipped']}")
        if results['errors']:
            logger.warning(f"  Errors: {results['errors']}")
        if dry_run:
            logger.info("  (dry run — nothing was written)")

        await client.close()

    await client.start(token)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backfill missed Discord submissions into the database')
    parser.add_argument('--limit', type=int, default=1000, help='Max messages to scan per channel (default: 1000)')
    parser.add_argument('--dry-run', action='store_true', help='Print what would be added without saving')
    args = parser.parse_args()

    asyncio.run(backfill(args.limit, args.dry_run))
