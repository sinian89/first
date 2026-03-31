FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install GDAL, PROJ, Python bindings, and curl for downloading grids
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    python3 \
    python3-pip \
    python3-gdal \
    python3-numpy \
    proj-data \
    proj-bin \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install OSTN15 datum grid for accurate OSGB36 <-> ETRS89 transformation
# Without this grid, PROJ falls back to a "ballpark" transform with ~5m error
RUN PROJ_DIR=$(pkg-config --variable=datadir proj 2>/dev/null || echo /usr/share/proj) && \
    curl -sL https://cdn.proj.org/uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
      -o "${PROJ_DIR}/uk_os_OSTN15_NTv2_OSGBtoETRS.tif" && \
    ls -la "${PROJ_DIR}/uk_os_OSTN15_NTv2_OSGBtoETRS.tif"

WORKDIR /app

# Generate synthetic data at build time
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

# Install pipeline spec
COPY pipeline.toml /app/pipeline.toml

# Record GDAL version for reproducibility
RUN gdalinfo --version > /app/.gdal_version
