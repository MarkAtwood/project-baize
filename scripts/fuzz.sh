#!/usr/bin/env bash
set -euo pipefail

# Fuzzing runner for both engines.
#
# Usage:
#   ./scripts/fuzz.sh                  # hypothesis + cargo-fuzz (30s default)
#   FUZZ_DURATION=120 ./scripts/fuzz.sh  # cargo-fuzz runs for 120 seconds
#
# Prerequisites:
#   pip install hypothesis             # Python property-based testing
#   cargo install cargo-fuzz           # Rust libFuzzer integration (nightly)

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FUZZ_DURATION="${FUZZ_DURATION:-30}"
PY_FAIL=0
RUST_FAIL=0

# --- Python: hypothesis property tests ---
echo "=== Python hypothesis fuzz tests ==="
if python3 -c "import hypothesis" 2>/dev/null; then
    (cd "$REPO_ROOT/python" && python3 -m pytest tests/test_fuzz_hypothesis.py -v) || PY_FAIL=1
else
    echo "SKIP: hypothesis not installed (pip install hypothesis)"
    PY_FAIL=2
fi
echo

# --- Rust: cargo-fuzz targets ---
echo "=== Rust cargo-fuzz (${FUZZ_DURATION}s per target) ==="
if cargo fuzz --version &>/dev/null; then
    for target in fuzz_definition_parse fuzz_action_parse; do
        echo "--- $target (${FUZZ_DURATION}s) ---"
        (cd "$REPO_ROOT/engine" && cargo fuzz run "$target" -- \
            -max_total_time="$FUZZ_DURATION" \
            -max_len=4096) || RUST_FAIL=1
    done
else
    echo "SKIP: cargo-fuzz not installed (cargo install cargo-fuzz)"
    echo "  Fuzz targets exist at engine/fuzz/fuzz_targets/ — install and run manually:"
    echo "    cd engine && cargo fuzz run fuzz_definition_parse -- -max_total_time=30"
    echo "    cd engine && cargo fuzz run fuzz_action_parse -- -max_total_time=30"
    RUST_FAIL=2
fi
echo

# --- Summary ---
echo "=== Summary ==="
report() {
    local name="$1" code="$2"
    case "$code" in
        0) echo "  $name: PASS" ;;
        1) echo "  $name: FAIL" ;;
        2) echo "  $name: SKIPPED (tool not installed)" ;;
    esac
}
report "Python hypothesis" "$PY_FAIL"
report "Rust cargo-fuzz"   "$RUST_FAIL"

if [ "$PY_FAIL" = "1" ] || [ "$RUST_FAIL" = "1" ]; then
    echo
    echo "FUZZING FAILURES DETECTED"
    exit 1
fi

if [ "$PY_FAIL" = "2" ] || [ "$RUST_FAIL" = "2" ]; then
    echo
    echo "Some fuzz runs skipped — install missing tools for full coverage."
fi

echo
echo "Done."
