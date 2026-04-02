# C++20 expression-engine task: agent writes /app/solution.cpp; verifier builds with g++ -std=c++20 -pthread.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bench-harbor overrides this with sleep infinity; keep a sane default for ad-hoc runs.
CMD ["sleep", "infinity"]
