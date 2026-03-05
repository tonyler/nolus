"""
Whitelist service for Discord user authorization
Reads from wl.json config file
"""

import os
import json
from pathlib import Path
from typing import List

WHITELIST_PATH = Path(__file__).parent / 'wl.json'

_cached_whitelist = None
_last_modified = 0


def _load_whitelist() -> dict:
    """Load whitelist from file, with caching based on file modification time."""
    global _cached_whitelist, _last_modified

    try:
        stat = os.stat(WHITELIST_PATH)

        # Return cached if file hasn't changed
        if _cached_whitelist and stat.st_mtime == _last_modified:
            return _cached_whitelist

        with open(WHITELIST_PATH, 'r') as f:
            _cached_whitelist = json.load(f)
        _last_modified = stat.st_mtime

        return _cached_whitelist
    except Exception as e:
        print(f"Failed to load whitelist: {e}")
        return {'allowedUserIds': []}


def is_user_whitelisted(discord_id: str) -> bool:
    """Check if a Discord user ID is in the whitelist."""
    whitelist = _load_whitelist()
    return discord_id in whitelist.get('allowedUserIds', [])


def get_whitelisted_users() -> List[str]:
    """Get list of all whitelisted user IDs."""
    whitelist = _load_whitelist()
    return whitelist.get('allowedUserIds', [])
