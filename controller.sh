#!/bin/bash
# ─────────────────────────────────────────────
# Master Controller
# - Charging (P110): 15:00 → 21:00
# - YouTube recorder: starts checking from 18:00
# Run: chmod +x controller.sh && nohup ./controller.sh > controller.log 2>&1 &
# Stop: pkill -f controller.sh
# Logs: tail -f controller.log
# ─────────────────────────────────────────────

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="python3"
SCHEDULER="$BASE_DIR/p110_scheduler.py"
RECORDER="$BASE_DIR/youtube_live_recorder.py"

# Admin credentials for shutdown/wake commands
ADMIN_USER="Hamza Ahmed"
ADMIN_PASS="Hamzahere"

CHARGE_ON=15   # 3 PM
CHARGE_OFF=21  # 9 PM
REC_START=18   # 6 PM
SHUTDOWN_H=21  # shutdown hour
SHUTDOWN_M=30  # shutdown minute (9:30 PM)
WAKE_TIME="14:45:00"  # wake up at 2:45 PM

TICK=30        # check every 30 seconds

shutdown_scheduled=false

scheduler_pid=""
recorder_pid=""

log() {
    echo "[$(date '+%H:%M:%S')] $1"
}

start_scheduler() {
    if [ -z "$scheduler_pid" ] || ! kill -0 "$scheduler_pid" 2>/dev/null; then
        log "▶ Starting P110 charging scheduler..."
        $PYTHON "$SCHEDULER" &
        scheduler_pid=$!
    fi
}

stop_scheduler() {
    if [ -n "$scheduler_pid" ] && kill -0 "$scheduler_pid" 2>/dev/null; then
        log "⏹ Stopping P110 charging scheduler..."
        kill "$scheduler_pid"
        wait "$scheduler_pid" 2>/dev/null
    fi
    scheduler_pid=""
}

start_recorder() {
    if [ -z "$recorder_pid" ] || ! kill -0 "$recorder_pid" 2>/dev/null; then
        log "▶ Starting YouTube live recorder..."
        $PYTHON "$RECORDER" &
        recorder_pid=$!
    fi
}

stop_recorder() {
    if [ -n "$recorder_pid" ] && kill -0 "$recorder_pid" 2>/dev/null; then
        log "⏹ Stopping YouTube live recorder..."
        kill "$recorder_pid"
        wait "$recorder_pid" 2>/dev/null
    fi
    recorder_pid=""
}

cleanup() {
    echo ""
    log "Shutting down all scripts..."
    stop_scheduler
    stop_recorder
    log "Done."
    exit 0
}

trap cleanup SIGINT SIGTERM

echo "================================================"
echo "  Master Controller (Shell)"
echo "================================================"
echo "  Charging  : $(printf '%02d:00' $CHARGE_ON) → $(printf '%02d:00' $CHARGE_OFF)"
echo "  Recording : $(printf '%02d:00' $REC_START) → $(printf '%02d:00' $CHARGE_OFF)"
echo "  Shutdown  : $(printf '%02d:%02d' $SHUTDOWN_H $SHUTDOWN_M)"
echo "  Wake      : $WAKE_TIME daily"
echo "  Tick      : every ${TICK}s"
echo ""

# Schedule daily wake
log "Scheduling daily wake at $WAKE_TIME..."
echo "$ADMIN_PASS" | sudo -S pmset repeat wakeorpoweron MTWRFSU "$WAKE_TIME"

while true; do
    HOUR=$(date '+%-H')  # current hour, no leading zero

    # ── Charging ──
    if [ "$HOUR" -ge "$CHARGE_ON" ] && [ "$HOUR" -lt "$CHARGE_OFF" ]; then
        start_scheduler
    else
        stop_scheduler
    fi

    # ── Recording ──
    if [ "$HOUR" -ge "$REC_START" ] && [ "$HOUR" -lt "$CHARGE_OFF" ]; then
        start_recorder
    else
        stop_recorder
    fi

    # ── Shutdown at 9:30 PM ──
    MINUTE=$(date '+%-M')
    if [ "$HOUR" -eq "$SHUTDOWN_H" ] && [ "$MINUTE" -ge "$SHUTDOWN_M" ] && [ "$shutdown_scheduled" = false ]; then
        shutdown_scheduled=true
        log "Scheduling shutdown in 1 minute..."
        stop_scheduler
        stop_recorder
        echo "$ADMIN_PASS" | sudo -S shutdown -h +1
    fi

    sleep $TICK
done