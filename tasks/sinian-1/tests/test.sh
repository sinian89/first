#!/bin/bash
set -e

mkdir -p /logs/verifier

if [[ ! -f /app/solution.cpp ]]; then
  echo "error: missing /app/solution.cpp (agent submission)" >&2
  echo 0 > /logs/verifier/reward.txt
  exit 1
fi

# Tests live on a read-only mount at /tests; cwd is /app. Build in /tmp.
# test_runner.cpp pulls in /app/solution.cpp via #include (see test_runner.cpp).
g++ -std=c++20 -O2 -pthread /tests/test_runner.cpp -o /tmp/test_runner

# Stress: 10 sequential + 10 parallel full-suite runs to catch rare races or UB
# (per task design — flakiness shows up as intermittent non-zero exit).
echo "Now sequential stress (10 runs)"
for i in {1..10}; do
  echo "Sequential Run $i"
  /tmp/test_runner || exit 1
done

echo "Now parallel stress (10 concurrent processes)"
pids=()
for i in {1..10}; do
  /tmp/test_runner &
  pids+=("$!")
done
fail=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    fail=1
  fi
done
RESULT=$fail

if [[ "$RESULT" -eq 0 ]]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "$RESULT"
