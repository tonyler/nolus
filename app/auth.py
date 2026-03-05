"""
Discord OAuth authentication routes and middleware
"""

import os
import requests
from functools import wraps
from flask import Blueprint, request, redirect, jsonify, make_response, g

from session_service import create_session, get_session, delete_session
from whitelist_service import is_user_whitelisted

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def get_app_prefix():
    """Get the app URL prefix (e.g., /nolus)."""
    prefix = os.getenv('APP_BASE_URL', '/nolus').rstrip('/')
    return prefix

DISCORD_API = 'https://discord.com/api/v10'
DISCORD_CDN = 'https://cdn.discordapp.com'


def get_discord_client_id():
    return os.getenv('DISCORD_CLIENT_ID', '')


def get_discord_client_secret():
    return os.getenv('DISCORD_CLIENT_SECRET', '')


def get_discord_redirect_uri():
    return os.getenv('DISCORD_REDIRECT_URI', 'http://localhost:5000/api/auth/callback')


def get_oauth_url():
    """Generate Discord OAuth URL."""
    params = {
        'client_id': get_discord_client_id(),
        'redirect_uri': get_discord_redirect_uri(),
        'response_type': 'code',
        'scope': 'identify',
    }
    query = '&'.join(f"{k}={v}" for k, v in params.items())
    return f"https://discord.com/oauth2/authorize?{query}"


def require_auth(f):
    """Decorator to require authentication on routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_id = request.cookies.get('session')

        if not session_id:
            # For API routes, return JSON error
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Not authenticated'}), 401
            # For page routes, redirect to login page
            return redirect(f"{get_app_prefix()}/login")

        session = get_session(session_id)

        if not session:
            if request.path.startswith('/api/'):
                response = make_response(jsonify({'error': 'Session expired'}))
                response.delete_cookie('session')
                return response, 401
            response = make_response(redirect(f"{get_app_prefix()}/login"))
            response.delete_cookie('session')
            return response

        # Re-check whitelist
        if not is_user_whitelisted(session['discord_id']):
            delete_session(session_id)
            response = make_response(jsonify({'error': 'User no longer authorized'}))
            response.delete_cookie('session')
            return response, 403

        # Attach user to g for use in routes
        g.user = {
            'id': session['discord_id'],
            'username': session['username'],
            'avatar': session['avatar'],
        }

        return f(*args, **kwargs)
    return decorated_function


@auth_bp.route('/login')
def login():
    """Redirect to Discord OAuth."""
    return redirect(get_oauth_url())


@auth_bp.route('/callback')
def callback():
    """Handle Discord OAuth callback."""
    code = request.args.get('code')

    if not code:
        return jsonify({'error': 'Missing authorization code'}), 400

    # Exchange code for tokens
    token_response = requests.post(
        f'{DISCORD_API}/oauth2/token',
        data={
            'client_id': get_discord_client_id(),
            'client_secret': get_discord_client_secret(),
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': get_discord_redirect_uri(),
        },
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )

    if not token_response.ok:
        print(f"Token exchange failed: {token_response.text}")
        return jsonify({'error': 'Failed to authenticate with Discord'}), 401

    tokens = token_response.json()

    # Get user info
    user_response = requests.get(
        f'{DISCORD_API}/users/@me',
        headers={'Authorization': f"Bearer {tokens['access_token']}"}
    )

    if not user_response.ok:
        return jsonify({'error': 'Failed to get user info'}), 401

    user = user_response.json()

    # Check whitelist
    if not is_user_whitelisted(user['id']):
        return jsonify({'error': 'User not authorized'}), 403

    # Create session
    avatar_url = None
    if user.get('avatar'):
        avatar_url = f"{DISCORD_CDN}/avatars/{user['id']}/{user['avatar']}.png"

    session = create_session({
        'discord_id': user['id'],
        'username': user['username'],
        'avatar': avatar_url,
        'access_token': tokens['access_token'],
        'refresh_token': tokens.get('refresh_token'),
        'expires_at': tokens.get('expires_in', 0) * 1000,
    })

    # Set session cookie and redirect to app
    base_url = os.getenv('APP_BASE_URL', '/nolus/')
    response = make_response(redirect(base_url))
    response.set_cookie(
        'session',
        session['id'],
        httponly=True,
        secure=os.getenv('FLASK_ENV') == 'production',
        samesite='Lax',
        max_age=30 * 24 * 60 * 60  # 30 days
    )

    return response


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Clear session and logout."""
    session_id = request.cookies.get('session')

    if session_id:
        delete_session(session_id)

    response = make_response(jsonify({'success': True}))
    response.delete_cookie('session')
    return response


@auth_bp.route('/me')
def me():
    """Get current user info."""
    session_id = request.cookies.get('session')

    if not session_id:
        return jsonify({'error': 'Not authenticated'}), 401

    session = get_session(session_id)

    if not session:
        response = make_response(jsonify({'error': 'Session expired'}))
        response.delete_cookie('session')
        return response, 401

    # Re-check whitelist
    if not is_user_whitelisted(session['discord_id']):
        delete_session(session_id)
        response = make_response(jsonify({'error': 'User no longer authorized'}))
        response.delete_cookie('session')
        return response, 403

    return jsonify({
        'user': {
            'id': session['discord_id'],
            'username': session['username'],
            'avatar': session['avatar'],
        }
    })
