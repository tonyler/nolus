"""
Flask Ambassador Dashboard - Main application file
"""

import os
import logging
from datetime import datetime

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

from sheets_service import SheetsService
from config_loader import get_config
from pfp_service import get_pfp_service

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class ReverseProxied:
    """Middleware to handle reverse proxy with URL prefix (e.g., /nolus)."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        script_name = environ.get('HTTP_X_SCRIPT_NAME', '')
        if script_name:
            environ['SCRIPT_NAME'] = script_name
            path_info = environ.get('PATH_INFO', '')
            if path_info.startswith(script_name):
                environ['PATH_INFO'] = path_info[len(script_name):]
        return self.app(environ, start_response)


app = Flask(__name__)
# Add ReverseProxied middleware to handle X-Script-Name header from nginx
app.wsgi_app = ReverseProxied(app.wsgi_app)
# Add ProxyFix to handle X-Forwarded-* headers from nginx
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Get secret key from environment or generate a secure warning
secret_key = os.getenv('FLASK_SECRET_KEY')
if not secret_key:
    logger.warning("FLASK_SECRET_KEY not set in environment! Using insecure default for development only.")
    secret_key = 'dev-secret-key-change-in-production'
app.secret_key = secret_key

# Initialize configuration and services
config = get_config()
sheets_service = SheetsService()

# Initialize profile picture service (uses db_service from sheets_service if available)
db_service = getattr(sheets_service, 'db_service', None) or getattr(sheets_service, 'local_service', None)
if db_service and hasattr(db_service, 'db_service'):
    db_service = db_service.db_service
pfp_service = get_pfp_service(db_service)

logger.info("Flask application initialized")

def get_selected_month():
    """Helper to get selected month from query params or current month"""
    current = datetime.now()
    if request.args.get('year') and request.args.get('month'):
        return request.args.get('year', type=int), request.args.get('month', type=int)
    return current.year, current.month

def render_error_page(error_message, status_code=500):
    """Render a user-friendly error page without redirect loops."""
    return render_template('error.html', error_message=error_message), status_code

@app.route('/')
def index():
    """Main dashboard - redirect to X leaderboard"""
    return redirect(url_for('x_leaderboard'))

@app.route('/x-leaderboard')
def x_leaderboard():
    """X/Twitter leaderboard page"""
    try:
        selected_year, selected_month = get_selected_month()
        current_month = datetime.now()

        leaderboard, total_impressions_all = sheets_service.get_x_leaderboard(selected_year, selected_month)

        # Get profile pictures for all ambassadors
        pfp_urls = pfp_service.get_pfp_urls_batch(leaderboard)

        return render_template(
            'x_leaderboard.html',
            leaderboard=leaderboard,
            pfp_urls=pfp_urls,
            total_impressions=total_impressions_all,
            total_posts=sum(amb['tweets'] for amb in leaderboard),
            active_ambassadors=len(leaderboard),
            available_months=sheets_service.get_available_months(),
            selected_year=selected_year,
            selected_month=selected_month,
            current_year=current_month.year,
            current_month_num=current_month.month,
            daily_stats=sheets_service.get_x_daily_stats(selected_year, selected_month)
        )
    except Exception as e:
        logger.error(f"Error rendering X leaderboard: {e}", exc_info=True)
        return render_error_page(f"Error loading X leaderboard: {str(e)}")

@app.route('/reddit-leaderboard')
def reddit_leaderboard():
    """Reddit leaderboard page"""
    try:
        selected_year, selected_month = get_selected_month()
        current_month = datetime.now()

        leaderboard = sheets_service.get_reddit_leaderboard(selected_year, selected_month)

        # Get profile pictures for all ambassadors
        pfp_urls = pfp_service.get_pfp_urls_batch(leaderboard)

        return render_template(
            'reddit_leaderboard.html',
            leaderboard=leaderboard,
            pfp_urls=pfp_urls,
            total_score=sum(amb['total_score'] for amb in leaderboard),
            total_posts=sum(amb['posts'] for amb in leaderboard),
            total_comments=sum(amb['total_comments'] for amb in leaderboard),
            total_views=sum(amb['total_views'] for amb in leaderboard),
            available_months=sheets_service.get_available_months(),
            selected_year=selected_year,
            selected_month=selected_month,
            current_year=current_month.year,
            current_month_num=current_month.month,
            daily_stats=sheets_service.get_reddit_daily_stats(selected_year, selected_month)
        )
    except Exception as e:
        logger.error(f"Error rendering Reddit leaderboard: {e}", exc_info=True)
        return render_error_page(f"Error loading Reddit leaderboard: {str(e)}")

@app.route('/total-leaderboard')
def total_leaderboard():
    """Total combined leaderboard page"""
    try:
        selected_year, selected_month = get_selected_month()
        current_month = datetime.now()

        leaderboard = sheets_service.get_total_leaderboard(selected_year, selected_month)

        # Get profile pictures for all ambassadors
        pfp_urls = pfp_service.get_pfp_urls_batch(leaderboard)

        return render_template(
            'total_leaderboard.html',
            leaderboard=leaderboard,
            pfp_urls=pfp_urls,
            total_x_views=sum(amb['x_views'] for amb in leaderboard),
            total_reddit_views=sum(amb['reddit_views'] for amb in leaderboard),
            total_combined_views=sum(amb['total_views'] for amb in leaderboard),
            available_months=sheets_service.get_available_months(),
            selected_year=selected_year,
            selected_month=selected_month,
            current_year=current_month.year,
            current_month_num=current_month.month,
            daily_stats=sheets_service.get_daily_impressions_for_graph(selected_year, selected_month)
        )
    except Exception as e:
        logger.error(f"Error rendering total leaderboard: {e}", exc_info=True)
        return render_error_page(f"Error loading total leaderboard: {str(e)}")

@app.route('/api/refresh-reddit', methods=['POST'])
def refresh_reddit():
    """API endpoint to refresh Reddit stats"""
    try:
        year = request.json.get('year') if request.json else None
        month = request.json.get('month') if request.json else None

        logger.info(f"Reddit refresh requested for {year}/{month}")
        success, message = sheets_service.update_reddit_stats(year, month)

        if success:
            logger.info(f"Reddit stats refreshed successfully: {message}")
        else:
            logger.warning(f"Reddit stats refresh failed: {message}")

        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error(f"Error refreshing Reddit stats: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f"Error: {str(e)}"})

@app.route('/api/clear-cache', methods=['POST'])
def clear_cache():
    """API endpoint to clear all caches"""
    try:
        logger.info("Cache clear requested")
        sheets_service._invalidate_cache()
        logger.info("Cache cleared successfully")
        return jsonify({'success': True, 'message': 'Cache cleared successfully'})
    except Exception as e:
        logger.error(f"Error clearing cache: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f"Error: {str(e)}"})

@app.route('/api/update-ambassador', methods=['POST'])
def update_ambassador():
    """API endpoint to update ambassador X handle"""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'})

        name = data.get('name')
        x_handle = data.get('x_handle')

        if not name or not x_handle:
            return jsonify({'success': False, 'message': 'Name and x_handle are required'})

        # Update the ambassador's handle and fetch new profile picture
        success = pfp_service.update_ambassador_handle(name, x_handle)

        if success:
            pfp_url = pfp_service.get_pfp_url(name, x_handle)
            return jsonify({
                'success': True,
                'message': f'Updated {name} with handle @{x_handle}',
                'pfp_url': pfp_url
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update ambassador'})

    except Exception as e:
        logger.error(f"Error updating ambassador: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f"Error: {str(e)}"})

@app.template_filter('month_name')
def month_name_filter(month_num):
    """Template filter to convert month number to name"""
    return datetime(2000, month_num, 1).strftime('%B')

if __name__ == '__main__':
    # For development
    app.run(host='0.0.0.0', port=5000, debug=True)
