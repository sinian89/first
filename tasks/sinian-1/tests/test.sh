#!/bin/bash
set -e

mkdir -p /logs/verifier

# Tests live on a read-only mount at /tests; cwd is /app. Build in /tmp.
g++ -std=c++20 -O2 -pthread /tests/test_runner.cpp -o /tmp/test_runner

echo "Now sequential stress"

for i in {1..10}; do
  echo "Sequential Run $i"
  /tmp/test_runner || exit 1
done

echo "Now parallel stress"

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

if [ "$RESULT" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "$RESULT"
