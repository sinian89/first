#!/usr/bin/env bash
set -euo pipefail

cd /app
mkdir -p output

# ── Step 1: Inspect source data CRSes ────────────────────────────────────

echo "=== Inspecting source data ==="
ogrinfo -so data/zones.shp zones | grep -i "layer srs"
gdalinfo data/dem.tif | grep -i "EPSG"
head -2 data/points.csv

# ── Step 2: Reproject all datasets to EPSG:3035 ──────────────────────────

# 2a. Zones: EPSG:27700 → EPSG:3035, output as GeoPackage
ogr2ogr -f GPKG \
    -s_srs EPSG:27700 \
    -t_srs EPSG:3035 \
    output/zones_3035.gpkg data/zones.shp

# 2b. DEM: EPSG:32630 → EPSG:3035, bilinear, preserve NoData
gdalwarp -s_srs EPSG:32630 -t_srs EPSG:3035 \
    -r bilinear \
    -srcnodata -9999 -dstnodata -9999 \
    -co COMPRESS=LZW \
    data/dem.tif output/dem_3035.tif

# 2c. Points CSV: EPSG:4258 → EPSG:3035, output as GeoPackage
ogr2ogr -f GPKG \
    -s_srs EPSG:4258 \
    -t_srs EPSG:3035 \
    -oo X_POSSIBLE_NAMES=longitude \
    -oo Y_POSSIBLE_NAMES=latitude \
    output/points_3035.gpkg data/points.csv

# ── Step 3: Rasterize zones onto exact DEM grid ──────────────────────────

eval $(gdalinfo -json output/dem_3035.tif | python3 -c "
import json, sys
info = json.load(sys.stdin)
gt = info['geoTransform']
sx, sy = info['size']
xmin = gt[0]; ymax = gt[3]
xres = gt[1]; yres = abs(gt[5])
print(f'XMIN={xmin}')
print(f'YMIN={ymax - sy * yres}')
print(f'XMAX={xmin + sx * xres}')
print(f'YMAX={ymax}')
print(f'XRES={xres}')
print(f'YRES={yres}')
")

gdal_rasterize -a ZONE_ID \
    -te $XMIN $YMIN $XMAX $YMAX \
    -tr $XRES $YRES \
    -ot Int32 \
    -a_nodata 0 \
    -co COMPRESS=LZW \
    output/zones_3035.gpkg output/zones_raster.tif

# ── Step 4: Zonal statistics ─────────────────────────────────────────────

python3 << 'PYEOF'
import json
import numpy as np
from osgeo import gdal

gdal.UseExceptions()

dem = gdal.Open("/app/output/dem_3035.tif")
zones = gdal.Open("/app/output/zones_raster.tif")

dem_arr = dem.GetRasterBand(1).ReadAsArray().astype(np.float64)
zones_arr = zones.GetRasterBand(1).ReadAsArray()
dem_nodata = dem.GetRasterBand(1).GetNoDataValue()

valid = dem_arr != dem_nodata

stats = {}
for zone_id in range(1, 6):
    zone_mask = zones_arr == zone_id
    valid_mask = zone_mask & valid
    nodata_mask = zone_mask & ~valid

    if valid_mask.any():
        vals = dem_arr[valid_mask]
        stats[str(zone_id)] = {
            "mean": round(float(np.mean(vals)), 4),
            "min": round(float(np.min(vals)), 4),
            "max": round(float(np.max(vals)), 4),
            "std": round(float(np.std(vals)), 4),
            "count": int(np.sum(valid_mask)),
            "nodata_count": int(np.sum(nodata_mask)),
        }
    else:
        stats[str(zone_id)] = {
            "mean": 0.0, "min": 0.0, "max": 0.0, "std": 0.0,
            "count": 0, "nodata_count": int(np.sum(nodata_mask)),
        }

with open("/app/output/zonal_stats.json", "w") as f:
    json.dump(stats, f, indent=2)
PYEOF

# ── Step 5: Join stats to zones vector (GeoPackage) ──────────────────────

python3 << 'PYEOF'
import json
from osgeo import ogr

ogr.UseExceptions()

with open("/app/output/zonal_stats.json") as f:
    stats = json.load(f)

src_ds = ogr.Open("/app/output/zones_3035.gpkg")
src_layer = src_ds.GetLayer()

driver = ogr.GetDriverByName("GPKG")
out_ds = driver.CreateDataSource("/app/output/zones_enriched.gpkg")
out_layer = out_ds.CreateLayer("zones_enriched", src_layer.GetSpatialRef(), ogr.wkbPolygon)

in_defn = src_layer.GetLayerDefn()
for i in range(in_defn.GetFieldCount()):
    out_layer.CreateField(in_defn.GetFieldDefn(i))

for fname in ["elev_mean", "elev_min", "elev_max", "elev_std"]:
    out_layer.CreateField(ogr.FieldDefn(fname, ogr.OFTReal))
out_layer.CreateField(ogr.FieldDefn("elev_count", ogr.OFTInteger))

for feat in src_layer:
    zone_id = str(feat.GetField("ZONE_ID"))
    out_feat = ogr.Feature(out_layer.GetLayerDefn())
    out_feat.SetGeometry(feat.GetGeometryRef().Clone())

    for i in range(in_defn.GetFieldCount()):
        out_feat.SetField(in_defn.GetFieldDefn(i).GetNameRef(), feat.GetField(i))

    s = stats.get(zone_id, {"mean": 0, "min": 0, "max": 0, "std": 0, "count": 0})
    out_feat.SetField("elev_mean", s["mean"])
    out_feat.SetField("elev_min", s["min"])
    out_feat.SetField("elev_max", s["max"])
    out_feat.SetField("elev_std", s["std"])
    out_feat.SetField("elev_count", s["count"])

    out_layer.CreateFeature(out_feat)

out_ds = None
src_ds = None
PYEOF

# ── Step 6: Terrain derivatives ──────────────────────────────────────────

gdaldem hillshade output/dem_3035.tif output/hillshade.tif \
    -az 315 -alt 45 -z 1 -compute_edges -co COMPRESS=LZW

gdaldem slope output/dem_3035.tif output/slope_deg.tif \
    -compute_edges -co COMPRESS=LZW

# ── Step 7: Normalized DEM ───────────────────────────────────────────────

python3 << 'PYEOF'
import numpy as np
from osgeo import gdal

gdal.UseExceptions()

src = gdal.Open("/app/output/dem_3035.tif")
band = src.GetRasterBand(1)
arr = band.ReadAsArray().astype(np.float64)
nodata = band.GetNoDataValue()

valid = arr != nodata
vmin = float(np.min(arr[valid]))
vmax = float(np.max(arr[valid]))

normalized = np.full_like(arr, nodata, dtype=np.float32)
normalized[valid] = ((arr[valid] - vmin) / (vmax - vmin)).astype(np.float32)

drv = gdal.GetDriverByName("GTiff")
out = drv.Create("/app/output/dem_norm.tif",
                 src.RasterXSize, src.RasterYSize, 1, gdal.GDT_Float32,
                 options=["COMPRESS=LZW"])
out.SetGeoTransform(src.GetGeoTransform())
out.SetProjection(src.GetProjection())
out_band = out.GetRasterBand(1)
out_band.SetNoDataValue(nodata)
out_band.WriteArray(normalized)
out.FlushCache()
out = None
PYEOF

# ── Step 8: Spatial overlay — point zone verification ────────────────────

python3 << 'PYEOF'
from osgeo import ogr

ogr.UseExceptions()

pts_ds = ogr.Open("/app/output/points_3035.gpkg")
pts_layer = pts_ds.GetLayer()

zones_ds = ogr.Open("/app/output/zones_3035.gpkg")
zones_layer = zones_ds.GetLayer()

with open("/app/output/point_zones.csv", "w") as f:
    f.write("id,zone_id_attr,zone_id_spatial\n")

    for pt_feat in pts_layer:
        pt_id = pt_feat.GetField("id")
        pt_zone = pt_feat.GetField("zone_id")
        pt_geom = pt_feat.GetGeometryRef()

        spatial_zone = -1
        zones_layer.ResetReading()
        zones_layer.SetSpatialFilter(pt_geom)
        for zone_feat in zones_layer:
            zone_geom = zone_feat.GetGeometryRef()
            if pt_geom.Within(zone_geom) or zone_geom.Intersects(pt_geom):
                spatial_zone = zone_feat.GetField("ZONE_ID")
                break
        zones_layer.SetSpatialFilter(None)

        f.write(f"{pt_id},{pt_zone},{spatial_zone}\n")
PYEOF

# ── Step 9: Composite VRT — hillshade(1), slope(2), dem(3) ──────────────

gdalbuildvrt -separate \
    output/composite.vrt \
    output/hillshade.tif \
    output/slope_deg.tif \
    output/dem_3035.tif

# ── Step 10: Audit report ────────────────────────────────────────────────

python3 << 'PYEOF'
import json
import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()

rasters = {
    "dem_3035.tif": "/app/output/dem_3035.tif",
    "zones_raster.tif": "/app/output/zones_raster.tif",
    "hillshade.tif": "/app/output/hillshade.tif",
    "slope_deg.tif": "/app/output/slope_deg.tif",
    "dem_norm.tif": "/app/output/dem_norm.tif",
}

audit = {}
for name, path in rasters.items():
    ds = gdal.Open(path)
    gt = ds.GetGeoTransform()
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray().astype(np.float64)
    nodata = band.GetNoDataValue()

    srs = osr.SpatialReference(wkt=ds.GetProjection())
    epsg = srs.GetAuthorityCode(None)

    if nodata is not None:
        valid = arr[arr != nodata]
    else:
        valid = arr.flatten()

    audit[name] = {
        "crs_epsg": int(epsg) if epsg else None,
        "width": ds.RasterXSize,
        "height": ds.RasterYSize,
        "nodata_value": nodata,
        "band_count": ds.RasterCount,
        "pixel_size_x": round(gt[1], 6),
        "pixel_size_y": round(abs(gt[5]), 6),
        "min_value": round(float(np.min(valid)), 4) if len(valid) > 0 else None,
        "max_value": round(float(np.max(valid)), 4) if len(valid) > 0 else None,
    }

with open("/app/output/audit.json", "w") as f:
    json.dump(audit, f, indent=2)
PYEOF

echo "=== Pipeline complete ==="
ls -la /app/output/
