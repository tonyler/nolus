#!/bin/bash
#
# Start Nolus Ambassador Dashboard and Discord Bot
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/app"
PID_DIR="$SCRIPT_DIR/pids"
LOG_DIR="$SCRIPT_DIR/logs"
VENV_DIR="$SCRIPT_DIR/venv"

# Create directories if they don't exist
mkdir -p "$PID_DIR" "$LOG_DIR"

# Check venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Virtual environment not found at $VENV_DIR"
    echo "Create it with: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
    exit 1
fi

PYTHON="$VENV_DIR/bin/python"
GUNICORN="$VENV_DIR/bin/gunicorn"

# Load environment variables
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

cd "$APP_DIR"

# Check if already running
if [ -f "$PID_DIR/flask.pid" ]; then
    FLASK_PID=$(cat "$PID_DIR/flask.pid")
    if ps -p "$FLASK_PID" > /dev/null 2>&1; then
        echo "Flask app already running (PID: $FLASK_PID)"
    else
        rm "$PID_DIR/flask.pid"
    fi
fi

# Start Flask app with gunicorn
if [ ! -f "$PID_DIR/flask.pid" ]; then
    echo "Starting Flask app..."
    nohup "$GUNICORN" --bind 0.0.0.0:5000 --workers 2 app:app \
        > "$LOG_DIR/flask.log" 2>&1 &
    echo $! > "$PID_DIR/flask.pid"
    echo "Flask app started (PID: $!)"
fi

# Start Discord bot via systemd (handles auto-restart/watchdog)
echo "Starting Discord bot (systemd)..."
systemctl start nolus-bot.service
echo "Discord bot started"

echo ""
echo "Services started. Logs available at:"
echo "  Flask: $LOG_DIR/flask.log"
echo "  Bot:   $LOG_DIR/bot.log  (also: journalctl -u nolus-bot -f)"
echo ""
echo "To stop services, run: ./stop.sh"
