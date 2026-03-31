FROM ubuntu:22.04

# Install build tools
RUN apt-get update && apt-get install -y \
    g++ \
    clang \
    make \
    cmake \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy all files
COPY . .

# Default command (can override)
CMD ["bash", "run.sh"]