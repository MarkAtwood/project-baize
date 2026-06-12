#!/usr/bin/env bash
# build-felt.sh — Launch Claude Code in a git worktree to build autonomously.
#
# Uses a git worktree so the build doesn't conflict with other work
# on the main checkout. Merges results back when done.
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

BRANCH_NAME="felt-compiler-build"
WORKTREE_DIR="${PROJECT_ROOT}/../baize-felt-build"

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
echo "Worktree: $WORKTREE_DIR" | tee -a "$LOGFILE"
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

PROMPT_FILE="$PROJECT_ROOT/scripts/PROMPT-build-felt.md"
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: prompt file not found: $PROMPT_FILE" | tee -a "$LOGFILE"
    exit 1
fi

# --- Create worktree ---
# Clean up any stale worktree from a previous run
if [ -d "$WORKTREE_DIR" ]; then
    echo "Removing stale worktree at $WORKTREE_DIR" | tee -a "$LOGFILE"
    git worktree remove --force "$WORKTREE_DIR" 2>/dev/null || rm -rf "$WORKTREE_DIR"
fi

# Delete stale branch if it exists
git branch -D "$BRANCH_NAME" 2>/dev/null || true

echo "Creating worktree: $WORKTREE_DIR (branch: $BRANCH_NAME)" | tee -a "$LOGFILE"
git worktree add -b "$BRANCH_NAME" "$WORKTREE_DIR" HEAD | tee -a "$LOGFILE"

# Copy beads config so bd works in the worktree
if [ -d "$PROJECT_ROOT/.beads" ]; then
    cp -r "$PROJECT_ROOT/.beads" "$WORKTREE_DIR/.beads"
fi

cd "$WORKTREE_DIR"
echo "Working directory: $(pwd)" | tee -a "$LOGFILE"
echo "---" | tee -a "$LOGFILE"

# --- Run Claude Code in the worktree ---
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
echo "=== Build finished at $(date -Iseconds) (exit code: $EXIT_CODE) ===" | tee -a "$LOGFILE"

# --- Merge back to main ---
cd "$PROJECT_ROOT"

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "" | tee -a "$LOGFILE"
    echo "=== Merging $BRANCH_NAME into main ===" | tee -a "$LOGFILE"

    COMMIT_COUNT=$(git log main.."$BRANCH_NAME" --oneline 2>/dev/null | wc -l)
    echo "Commits to merge: $COMMIT_COUNT" | tee -a "$LOGFILE"

    if [ "$COMMIT_COUNT" -gt 0 ]; then
        git merge "$BRANCH_NAME" --no-edit 2>&1 | tee -a "$LOGFILE"
        echo "Merge complete." | tee -a "$LOGFILE"
    else
        echo "No new commits to merge." | tee -a "$LOGFILE"
    fi
else
    echo "Build failed (exit $EXIT_CODE). NOT merging." | tee -a "$LOGFILE"
fi

# --- Cleanup worktree ---
echo "" | tee -a "$LOGFILE"
echo "Cleaning up worktree..." | tee -a "$LOGFILE"
git worktree remove --force "$WORKTREE_DIR" 2>/dev/null || true
git branch -D "$BRANCH_NAME" 2>/dev/null || true
echo "Cleanup done." | tee -a "$LOGFILE"

# --- Post-run summary ---
echo "" | tee -a "$LOGFILE"
echo "=== Post-build status ===" | tee -a "$LOGFILE"
git log --oneline -5 2>&1 | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"
bd stats 2>&1 | tee -a "$LOGFILE"

rm -f "$PIDFILE"
exit $EXIT_CODE
