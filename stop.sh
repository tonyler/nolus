#!/bin/bash
#
# Stop Nolus Ambassador Dashboard and Discord Bot
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$SCRIPT_DIR/pids"

stop_process() {
    local name="$1"
    local pid_file="$PID_DIR/$2.pid"

    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Stopping $name (PID: $PID)..."
            kill "$PID"

            # Wait for process to stop (max 10 seconds)
            for i in {1..10}; do
                if ! ps -p "$PID" > /dev/null 2>&1; then
                    break
                fi
                sleep 1
            done

            # Force kill if still running
            if ps -p "$PID" > /dev/null 2>&1; then
                echo "Force killing $name..."
                kill -9 "$PID"
            fi

            echo "$name stopped"
        else
            echo "$name not running (stale PID file)"
        fi
        rm -f "$pid_file"
    else
        echo "$name not running (no PID file)"
    fi
}

# Stop Flask app
stop_process "Flask app" "flask"

# Stop Discord bot via systemd
echo "Stopping Discord bot (systemd)..."
systemctl stop nolus-bot.service
echo "Discord bot stopped"

echo ""
echo "All services stopped"
