#!/usr/bin/env python3
"""Generate synthetic geospatial data for the GDAL coordinate surgery task."""

import os
import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()

os.makedirs("/app/data", exist_ok=True)

# === 1. Create shapefile in EPSG:27700 (OSGB36 / British National Grid) ===

srs_27700 = osr.SpatialReference()
srs_27700.ImportFromEPSG(27700)

driver = ogr.GetDriverByName("ESRI Shapefile")
ds = driver.CreateDataSource("/app/data/zones.shp")
layer = ds.CreateLayer("zones", srs_27700, ogr.wkbPolygon)
layer.CreateField(ogr.FieldDefn("ZONE_ID", ogr.OFTInteger))

# 5 non-overlapping rectangles in BNG coords (southeast England area)
ZONES = [
    (1, 510000, 160000, 530000, 180000),
    (2, 530000, 160000, 550000, 180000),
    (3, 510000, 180000, 530000, 200000),
    (4, 530000, 180000, 550000, 200000),
    (5, 520000, 200000, 540000, 210000),
]

for zone_id, xmin, ymin, xmax, ymax in ZONES:
    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint(xmin, ymin)
    ring.AddPoint(xmax, ymin)
    ring.AddPoint(xmax, ymax)
    ring.AddPoint(xmin, ymax)
    ring.AddPoint(xmin, ymin)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    feat = ogr.Feature(layer.GetLayerDefn())
    feat.SetField("ZONE_ID", zone_id)
    feat.SetGeometry(poly)
    layer.CreateFeature(feat)

ds = None

# === 2. Create raster DEM in EPSG:32630 (WGS84 / UTM 30N) ===

srs_32630 = osr.SpatialReference()
srs_32630.ImportFromEPSG(32630)

xorigin = 670000.0
yorigin = 5750000.0  # top-left Y (north)
xsize = 600
ysize = 700
pixel = 100.0
nodata = -9999.0

drv = gdal.GetDriverByName("GTiff")
dem = drv.Create("/app/data/dem.tif", xsize, ysize, 1, gdal.GDT_Float32)
dem.SetGeoTransform([xorigin, pixel, 0, yorigin, 0, -pixel])
dem.SetProjection(srs_32630.ExportToWkt())

band = dem.GetRasterBand(1)
band.SetNoDataValue(nodata)

# Synthetic elevation: gradient + deterministic pattern
np.random.seed(42)
x = np.linspace(0, 1, xsize)   # columns
y = np.linspace(0, 1, ysize)   # rows
xx, yy = np.meshgrid(x, y)
elev = (50.0 + 100.0 * xx + 50.0 * yy + 10.0 * np.sin(xx * 10) * np.cos(yy * 10)).astype(
    np.float32
)

# Plant NoData pixels at specific locations
elev[0, 0] = nodata
elev[349, 300] = nodata
elev[699, 599] = nodata
elev[200:203, 200:203] = nodata  # 3x3 block

band.WriteArray(elev)
band.FlushCache()
dem = None

# === 3. Create CSV with points in EPSG:4258 (ETRS89 geographic) ===

srs_4258 = osr.SpatialReference()
srs_4258.ImportFromEPSG(4258)

# Force traditional GIS axis order (lon, lat) so GetX() = longitude, GetY() = latitude
srs_27700_gis = osr.SpatialReference()
srs_27700_gis.ImportFromEPSG(27700)
srs_27700_gis.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
srs_4258.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

transform = osr.CoordinateTransformation(srs_27700_gis, srs_4258)

with open("/app/data/points.csv", "w") as f:
    f.write("id,longitude,latitude,zone_id\n")
    pid = 1
    for zone_id, xmin, ymin, xmax, ymax in ZONES:
        for dx, dy in [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)]:
            px = xmin + dx * (xmax - xmin)
            py = ymin + dy * (ymax - ymin)
            pt = ogr.Geometry(ogr.wkbPoint)
            pt.AddPoint(px, py)
            pt.Transform(transform)
            f.write(f"{pid},{pt.GetX():.8f},{pt.GetY():.8f},{zone_id}\n")
            pid += 1

# === 4. Write README for the agent ===

with open("/app/data/README.txt", "w") as f:
    f.write("zones.shp  - Vector polygons, EPSG:27700 (OSGB 1936 / British National Grid)\n")
    f.write("dem.tif     - Raster DEM, EPSG:32630 (WGS 84 / UTM zone 30N)\n")
    f.write("points.csv  - Point coordinates, EPSG:4258 (ETRS89 geographic)\n")

print("Data generation complete.")
print(f"  zones.shp  -> {os.path.getsize('/app/data/zones.shp')} bytes")
print(f"  dem.tif    -> {os.path.getsize('/app/data/dem.tif')} bytes")
print(f"  points.csv -> {os.path.getsize('/app/data/points.csv')} bytes")
