#!/usr/bin/env bash
# build-felt.sh — Launch Claude Code to build the Felt compiler autonomously.
#
# Usage:
#   ./scripts/build-felt.sh              # foreground with live output
#   ./scripts/build-felt.sh &            # background
#   nohup ./scripts/build-felt.sh &      # background, survives logout
#
# Logs: logs/felt-build-<timestamp>.log
# PID:  logs/felt-build.pid
#
# To monitor: tail -f logs/felt-build-*.log
# To stop:    kill $(cat logs/felt-build.pid)

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# --- Setup logging ---
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOGFILE="$LOG_DIR/felt-build-${TIMESTAMP}.log"
PIDFILE="$LOG_DIR/felt-build.pid"

echo $$ > "$PIDFILE"
echo "=== Felt compiler build started at $(date -Iseconds) ===" | tee "$LOGFILE"
echo "PID: $$" | tee -a "$LOGFILE"
echo "Log: $LOGFILE" | tee -a "$LOGFILE"
echo "Project: $PROJECT_ROOT" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

# --- Preflight checks ---
if ! command -v claude &>/dev/null; then
    echo "ERROR: claude CLI not found" | tee -a "$LOGFILE"
    exit 1
fi

if ! git rev-parse --is-inside-work-tree &>/dev/null; then
    echo "ERROR: not in a git repository" | tee -a "$LOGFILE"
    exit 1
fi

# Ensure beads is initialized
if ! bd status &>/dev/null; then
    echo "ERROR: beads not initialized" | tee -a "$LOGFILE"
    exit 1
fi

# Ensure clean working tree (don't start with uncommitted changes)
if [ -n "$(git status --porcelain)" ]; then
    echo "WARNING: working tree not clean, proceeding anyway" | tee -a "$LOGFILE"
    git status --short | tee -a "$LOGFILE"
    echo "" | tee -a "$LOGFILE"
fi

PROMPT_FILE="$PROJECT_ROOT/scripts/PROMPT-build-felt.md"
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: prompt file not found: $PROMPT_FILE" | tee -a "$LOGFILE"
    exit 1
fi

echo "Starting Claude Code with prompt: $PROMPT_FILE" | tee -a "$LOGFILE"
echo "---" | tee -a "$LOGFILE"

# --- Run Claude Code ---
# --print: non-interactive, print output
# --verbose: show tool calls
# --max-turns 200: generous budget for a compiler build
# --model: use opus for complex multi-file work
claude \
    --print \
    --verbose \
    --max-turns 200 \
    --model claude-opus-4-6 \
    --dangerously-skip-permissions \
    -p "$(cat "$PROMPT_FILE")" \
    2>&1 | tee -a "$LOGFILE"

EXIT_CODE=${PIPESTATUS[0]}

echo "" | tee -a "$LOGFILE"
echo "---" | tee -a "$LOGFILE"
echo "=== Felt compiler build finished at $(date -Iseconds) ===" | tee -a "$LOGFILE"
echo "Exit code: $EXIT_CODE" | tee -a "$LOGFILE"

# --- Post-run summary ---
echo "" | tee -a "$LOGFILE"
echo "=== Post-build status ===" | tee -a "$LOGFILE"
git log --oneline -5 2>&1 | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"
bd stats 2>&1 | tee -a "$LOGFILE"

rm -f "$PIDFILE"
exit $EXIT_CODE
