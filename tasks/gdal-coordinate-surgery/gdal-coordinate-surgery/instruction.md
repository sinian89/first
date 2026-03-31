# Geospatial Pipeline

There are three datasets in `/app/data/` covering the same area in southeast England — a polygon layer, a raster DEM, and a point CSV — each in a different CRS. Build a complete analysis pipeline per the spec in `/app/pipeline.toml`. All outputs go in `/app/output/`.

Inspect the data to determine source CRSes. The pipeline config specifies the target CRS, required outputs, and processing parameters. Some outputs depend on earlier ones — read the spec carefully and handle edge cases properly.
