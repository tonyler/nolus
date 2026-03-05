"""
Session management service for Discord OAuth
File-based session storage with TTL
"""

import os
import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

SESSIONS_DIR = Path(__file__).parent / 'data' / 'sessions'
SESSION_TTL_DAYS = 30


def _ensure_sessions_dir():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _get_session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def generate_session_id() -> str:
    return secrets.token_hex(32)


def create_session(data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new session and save to file."""
    _ensure_sessions_dir()

    session = {
        'id': generate_session_id(),
        'discord_id': data['discord_id'],
        'username': data['username'],
        'avatar': data.get('avatar'),
        'access_token': data['access_token'],
        'refresh_token': data['refresh_token'],
        'expires_at': data['expires_at'],
        'created_at': datetime.now().isoformat(),
    }

    session_path = _get_session_path(session['id'])
    with open(session_path, 'w') as f:
        json.dump(session, f, indent=2)

    return session


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get session by ID, returns None if expired or not found."""
    try:
        session_path = _get_session_path(session_id)

        if not session_path.exists():
            return None

        with open(session_path, 'r') as f:
            session = json.load(f)

        # Check if session is expired
        created_at = datetime.fromisoformat(session['created_at'])
        age_days = (datetime.now() - created_at).days

        if age_days > SESSION_TTL_DAYS:
            delete_session(session_id)
            return None

        return session
    except Exception:
        return None


def delete_session(session_id: str) -> None:
    """Delete a session file."""
    try:
        session_path = _get_session_path(session_id)
        if session_path.exists():
            session_path.unlink()
    except Exception:
        pass


def clean_expired_sessions() -> None:
    """Remove all expired sessions."""
    _ensure_sessions_dir()

    try:
        for session_file in SESSIONS_DIR.glob('*.json'):
            session_id = session_file.stem
            # get_session handles expiration check and deletion
            get_session(session_id)
    except Exception:
        pass
