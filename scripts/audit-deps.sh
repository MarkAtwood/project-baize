#!/usr/bin/env bash
set -uo pipefail

# Dependency supply chain audit for all three ecosystems.
# Runs all audits even if one fails, reports aggregate result at the end.
#
# Prerequisites:
#   cargo install cargo-audit   # Rust
#   pip install pip-audit        # Python
#   npm (bundled with Node.js)   # TypeScript

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUST_FAIL=0
PY_FAIL=0
TS_FAIL=0

# --- Rust: cargo audit (engine + server) ---
echo "=== Rust dependency audit ==="
if ! command -v cargo-audit &>/dev/null; then
    echo "SKIP: cargo-audit not installed (cargo install cargo-audit)"
    RUST_FAIL=2
else
    for crate in engine server; do
        if [ -f "$REPO_ROOT/$crate/Cargo.lock" ]; then
            echo "--- $crate ---"
            cargo audit --file "$REPO_ROOT/$crate/Cargo.lock" 2>&1 || RUST_FAIL=1
        else
            echo "SKIP: $REPO_ROOT/$crate/Cargo.lock not found"
        fi
    done
fi
echo

# --- Python: pip-audit ---
echo "=== Python dependency audit ==="
if ! command -v pip-audit &>/dev/null; then
    echo "SKIP: pip-audit not installed (pip install pip-audit)"
    PY_FAIL=2
else
    if [ -f "$REPO_ROOT/python/pyproject.toml" ]; then
        pip-audit --desc --project-path "$REPO_ROOT/python" 2>&1 || PY_FAIL=1
    else
        echo "SKIP: python/pyproject.toml not found"
    fi
fi
echo

# --- TypeScript: npm audit ---
echo "=== TypeScript dependency audit ==="
if ! command -v npm &>/dev/null; then
    echo "SKIP: npm not installed"
    TS_FAIL=2
else
    if [ -f "$REPO_ROOT/client/package-lock.json" ]; then
        (cd "$REPO_ROOT/client" && npm audit --omit=dev 2>&1) || TS_FAIL=1
    else
        echo "SKIP: client/package-lock.json not found"
    fi
fi
echo

# --- Summary ---
echo "=== Summary ==="
report() {
    local name="$1" code="$2"
    case "$code" in
        0) echo "  $name: PASS" ;;
        1) echo "  $name: VULNERABLE" ;;
        2) echo "  $name: SKIPPED (tool not installed)" ;;
    esac
}
report "Rust"       "$RUST_FAIL"
report "Python"     "$PY_FAIL"
report "TypeScript" "$TS_FAIL"

if [ "$RUST_FAIL" = "1" ] || [ "$PY_FAIL" = "1" ] || [ "$TS_FAIL" = "1" ]; then
    echo
    echo "VULNERABILITIES FOUND"
    exit 1
fi

if [ "$RUST_FAIL" = "2" ] || [ "$PY_FAIL" = "2" ] || [ "$TS_FAIL" = "2" ]; then
    echo
    echo "Some audits skipped — install missing tools for full coverage."
    exit 0
fi

echo
echo "All clear."
