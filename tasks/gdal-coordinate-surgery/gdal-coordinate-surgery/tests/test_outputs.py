"""
Verifier for gdal-coordinate-surgery task.

Validates the full geospatial pipeline defined in /app/pipeline.toml.
"""

import csv
import json
import os

import numpy as np
import pytest
from osgeo import gdal, ogr, osr

gdal.UseExceptions()

OUTPUT = "/app/output"

ZONES_BNG = [
    (1, 510000, 160000, 530000, 180000),
    (2, 530000, 160000, 550000, 180000),
    (3, 510000, 180000, 530000, 200000),
    (4, 530000, 180000, 550000, 200000),
    (5, 520000, 200000, 540000, 210000),
]


# ── Reprojection ─────────────────────────────────────────────────────────


class TestReprojection:
    """Reprojection to EPSG:3035 with correct datum handling."""

    def test_dem_exists_and_crs(self):
        """Reprojected DEM must be in EPSG:3035."""
        path = os.path.join(OUTPUT, "dem_3035.tif")
        assert os.path.exists(path), "dem_3035.tif not found"
        ds = gdal.Open(path)
        srs = osr.SpatialReference(wkt=ds.GetProjection())
        assert srs.GetAuthorityCode(None) == "3035"

    def test_zones_gpkg_exists_and_crs(self):
        """Reprojected zones must be GeoPackage format in EPSG:3035."""
        path = os.path.join(OUTPUT, "zones_3035.gpkg")
        assert os.path.exists(path), (
            "zones_3035.gpkg not found — spec requires GeoPackage, not Shapefile"
        )
        ds = ogr.Open(path)
        layer = ds.GetLayer()
        srs = layer.GetSpatialRef()
        assert srs.GetAuthorityCode(None) == "3035"

    def test_points_gpkg_exists_and_crs(self):
        """Reprojected points must be GeoPackage format in EPSG:3035."""
        path = os.path.join(OUTPUT, "points_3035.gpkg")
        assert os.path.exists(path), (
            "points_3035.gpkg not found — spec requires GeoPackage, not Shapefile"
        )
        ds = ogr.Open(path)
        layer = ds.GetLayer()
        srs = layer.GetSpatialRef()
        assert srs.GetAuthorityCode(None) == "3035"

    def test_datum_transformation_precision(self):
        """
        Zone centroids must be within 1m of the correct OSTN15-based position.
        Catches agents using Helmert 7-param (+towgs84) instead of grid shift.
        """
        ds = ogr.Open(os.path.join(OUTPUT, "zones_3035.gpkg"))
        assert ds is not None, "Cannot open zones_3035.gpkg"
        layer = ds.GetLayer()

        srs_27700 = osr.SpatialReference()
        srs_27700.ImportFromEPSG(27700)
        srs_27700.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        srs_3035 = osr.SpatialReference()
        srs_3035.ImportFromEPSG(3035)
        srs_3035.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        transform = osr.CoordinateTransformation(srs_27700, srs_3035)

        expected = {}
        for zone_id, xmin, ymin, xmax, ymax in ZONES_BNG:
            pt = ogr.Geometry(ogr.wkbPoint)
            pt.AddPoint((xmin + xmax) / 2, (ymin + ymax) / 2)
            pt.Transform(transform)
            expected[zone_id] = (pt.GetX(), pt.GetY())

        for feat in layer:
            zid = feat.GetField("ZONE_ID")
            c = feat.GetGeometryRef().Centroid()
            ex, ey = expected[zid]
            dist = ((c.GetX() - ex) ** 2 + (c.GetY() - ey) ** 2) ** 0.5
            assert dist < 1.0, (
                f"Zone {zid} centroid off by {dist:.2f}m — wrong datum transformation"
            )

    def test_bilinear_resampling(self):
        """DEM must use bilinear resampling (produces fractional values)."""
        dem = gdal.Open(os.path.join(OUTPUT, "dem_3035.tif"))
        arr = dem.GetRasterBand(1).ReadAsArray().astype(np.float64)
        nodata = dem.GetRasterBand(1).GetNoDataValue()
        valid = arr[arr != nodata]
        sample = valid[len(valid) // 4 : len(valid) // 4 + 1000]
        frac = np.sum(np.abs(sample - np.round(sample)) > 0.001) / len(sample)
        assert frac > 0.5, f"Only {frac:.0%} fractional — likely nearest-neighbor"

    def test_points_count(self):
        """All 20 points must survive reprojection."""
        ds = ogr.Open(os.path.join(OUTPUT, "points_3035.gpkg"))
        layer = ds.GetLayer()
        assert layer.GetFeatureCount() == 20, (
            f"Expected 20 points, got {layer.GetFeatureCount()}"
        )


# ── Rasterization ────────────────────────────────────────────────────────


class TestRasterization:
    """Rasterized zones must be pixel-aligned with DEM."""

    def test_grid_alignment(self):
        """Identical dimensions, resolution, and extent as DEM."""
        dem = gdal.Open(os.path.join(OUTPUT, "dem_3035.tif"))
        zr_path = os.path.join(OUTPUT, "zones_raster.tif")
        assert os.path.exists(zr_path), "zones_raster.tif not found"
        zones = gdal.Open(zr_path)

        assert dem.RasterXSize == zones.RasterXSize
        assert dem.RasterYSize == zones.RasterYSize

        dem_gt = dem.GetGeoTransform()
        z_gt = zones.GetGeoTransform()
        for i in range(6):
            assert abs(dem_gt[i] - z_gt[i]) < 0.01, (
                f"GeoTransform[{i}]: DEM={dem_gt[i]}, zones={z_gt[i]}"
            )


# ── Zonal Statistics ─────────────────────────────────────────────────────


class TestZonalStats:
    """Zonal statistics with correct NoData handling."""

    def test_values(self):
        """Mean/min/max per zone must match independently computed reference."""
        path = os.path.join(OUTPUT, "zonal_stats.json")
        assert os.path.exists(path), "zonal_stats.json not found"
        with open(path) as f:
            stats = json.load(f)

        dem = gdal.Open(os.path.join(OUTPUT, "dem_3035.tif"))
        zones = gdal.Open(os.path.join(OUTPUT, "zones_raster.tif"))
        da = dem.GetRasterBand(1).ReadAsArray().astype(np.float64)
        za = zones.GetRasterBand(1).ReadAsArray()
        nd = dem.GetRasterBand(1).GetNoDataValue()
        valid = da != nd

        for zid in range(1, 6):
            k = str(zid)
            assert k in stats, f"Zone {zid} missing"
            mask = (za == zid) & valid
            if mask.any():
                for field, fn in [("mean", np.mean), ("min", np.min), ("max", np.max)]:
                    ref = float(fn(da[mask]))
                    assert abs(stats[k][field] - ref) < 0.1, (
                        f"Zone {zid} {field}: expected {ref:.4f}, got {stats[k][field]}"
                    )

    def test_std_population(self):
        """Standard deviation must be population (ddof=0), not sample (ddof=1)."""
        with open(os.path.join(OUTPUT, "zonal_stats.json")) as f:
            stats = json.load(f)

        dem = gdal.Open(os.path.join(OUTPUT, "dem_3035.tif"))
        zones = gdal.Open(os.path.join(OUTPUT, "zones_raster.tif"))
        da = dem.GetRasterBand(1).ReadAsArray().astype(np.float64)
        za = zones.GetRasterBand(1).ReadAsArray()
        nd = dem.GetRasterBand(1).GetNoDataValue()

        for zid in range(1, 6):
            k = str(zid)
            assert "std" in stats[k], f"Zone {zid} missing 'std'"
            mask = (za == zid) & (da != nd)
            if mask.any():
                ref = float(np.std(da[mask]))  # ddof=0
                assert abs(stats[k]["std"] - ref) < 0.1, (
                    f"Zone {zid} std: expected {ref:.4f}, got {stats[k]['std']}"
                )

    def test_nodata_count(self):
        """Each zone must report NoData pixel count."""
        with open(os.path.join(OUTPUT, "zonal_stats.json")) as f:
            stats = json.load(f)

        dem = gdal.Open(os.path.join(OUTPUT, "dem_3035.tif"))
        zones = gdal.Open(os.path.join(OUTPUT, "zones_raster.tif"))
        da = dem.GetRasterBand(1).ReadAsArray().astype(np.float64)
        za = zones.GetRasterBand(1).ReadAsArray()
        nd = dem.GetRasterBand(1).GetNoDataValue()

        for zid in range(1, 6):
            k = str(zid)
            assert "nodata_count" in stats[k], f"Zone {zid} missing 'nodata_count'"
            ref = int(np.sum((za == zid) & (da == nd)))
            assert stats[k]["nodata_count"] == ref


# ── Vector Join ──────────────────────────────────────────────────────────


class TestVectorJoin:
    """Enriched zones vector with stat attributes."""

    def test_enriched_gpkg(self):
        """Must be GeoPackage with elev_mean/min/max/std/count fields."""
        path = os.path.join(OUTPUT, "zones_enriched.gpkg")
        assert os.path.exists(path), (
            "zones_enriched.gpkg not found — spec requires GeoPackage"
        )
        ds = ogr.Open(path)
        layer = ds.GetLayer()
        defn = layer.GetLayerDefn()
        names = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
        for f in ["elev_mean", "elev_min", "elev_max", "elev_std", "elev_count"]:
            assert f in names, f"Missing field '{f}'"

        with open(os.path.join(OUTPUT, "zonal_stats.json")) as fj:
            stats = json.load(fj)

        for feat in layer:
            zid = str(feat.GetField("ZONE_ID"))
            s = stats[zid]
            assert abs(feat.GetField("elev_mean") - s["mean"]) < 0.5
            assert abs(feat.GetField("elev_std") - s["std"]) < 0.5


# ── Terrain Derivatives ──────────────────────────────────────────────────


class TestTerrain:
    """Hillshade and slope rasters."""

    def test_hillshade(self):
        """Hillshade must be single-band Byte with DEM-matching extent."""
        path = os.path.join(OUTPUT, "hillshade.tif")
        assert os.path.exists(path), "hillshade.tif not found"
        ds = gdal.Open(path)
        assert ds.RasterCount == 1
        assert gdal.GetDataTypeName(ds.GetRasterBand(1).DataType) == "Byte"

    def test_slope_exists_and_degrees(self):
        """Slope must be in degrees (max < 45 for gentle terrain), named slope_deg.tif."""
        path = os.path.join(OUTPUT, "slope_deg.tif")
        assert os.path.exists(path), (
            "slope_deg.tif not found — spec names it slope_deg.tif, not slope.tif"
        )
        ds = gdal.Open(path)
        arr = ds.GetRasterBand(1).ReadAsArray()
        nd = ds.GetRasterBand(1).GetNoDataValue()
        valid = arr[arr != nd] if nd is not None else arr.flatten()
        assert float(np.max(valid)) < 45.0, "Slope likely in percent, not degrees"
        assert float(np.max(valid)) > 0.0, "All slope values are zero"


# ── Normalized DEM ───────────────────────────────────────────────────────


class TestNormalized:
    """Min-max normalized DEM."""

    def test_range_and_nodata(self):
        """Must be [0,1] for valid pixels, NoData preserved."""
        path = os.path.join(OUTPUT, "dem_norm.tif")
        assert os.path.exists(path), (
            "dem_norm.tif not found — spec names it dem_norm.tif"
        )
        ds = gdal.Open(path)
        assert gdal.GetDataTypeName(ds.GetRasterBand(1).DataType) == "Float32"

        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray()
        nd = band.GetNoDataValue()
        assert nd is not None, "NoData not set"

        valid = arr[arr != nd]
        assert len(valid) > 0
        assert float(np.min(valid)) >= -0.001 and float(np.min(valid)) < 0.01
        assert float(np.max(valid)) <= 1.001 and float(np.max(valid)) > 0.99

    def test_nodata_preserved(self):
        """Original NoData pixels must remain NoData after normalization."""
        orig = gdal.Open(os.path.join(OUTPUT, "dem_3035.tif"))
        norm = gdal.Open(os.path.join(OUTPUT, "dem_norm.tif"))
        o_arr = orig.GetRasterBand(1).ReadAsArray()
        n_arr = norm.GetRasterBand(1).ReadAsArray()
        o_nd = orig.GetRasterBand(1).GetNoDataValue()
        n_nd = norm.GetRasterBand(1).GetNoDataValue()
        missed = np.sum((o_arr == o_nd) & (n_arr != n_nd))
        assert missed == 0, f"{missed} NoData pixels lost during normalization"


# ── Spatial Overlay ──────────────────────────────────────────────────────


class TestSpatialOverlay:
    """Point-in-polygon verification."""

    def test_csv_schema(self):
        """Must have id, zone_id_attr, zone_id_spatial columns."""
        path = os.path.join(OUTPUT, "point_zones.csv")
        assert os.path.exists(path), "point_zones.csv not found"
        with open(path) as f:
            reader = csv.DictReader(f)
            for col in ["id", "zone_id_attr", "zone_id_spatial"]:
                assert col in reader.fieldnames, (
                    f"Missing column '{col}' — spec requires: id, zone_id_attr, zone_id_spatial"
                )

    def test_all_points_match(self):
        """All 20 points must have matching zone_id_attr and zone_id_spatial."""
        path = os.path.join(OUTPUT, "point_zones.csv")
        with open(path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 20, f"Expected 20 rows, got {len(rows)}"
        bad = [r for r in rows if int(r["zone_id_attr"]) != int(r["zone_id_spatial"])]
        assert len(bad) == 0, (
            f"{len(bad)} mismatches — reprojection or overlay broken"
        )


# ── Composite VRT ────────────────────────────────────────────────────────


class TestComposite:
    """Multi-band VRT with specific band ordering."""

    def test_band_ordering(self):
        """
        Spec: band 1 = hillshade (Byte), band 2 = slope (Float32), band 3 = DEM (Float32).
        NOTE: the order is hillshade, slope, dem — NOT hillshade, dem, slope.
        """
        path = os.path.join(OUTPUT, "composite.vrt")
        assert os.path.exists(path), (
            "composite.vrt not found — spec names it composite.vrt, not combined.vrt"
        )
        ds = gdal.Open(path)
        assert ds.RasterCount == 3, f"Expected 3 bands, got {ds.RasterCount}"

        b1 = gdal.GetDataTypeName(ds.GetRasterBand(1).DataType)
        b2 = gdal.GetDataTypeName(ds.GetRasterBand(2).DataType)
        b3 = gdal.GetDataTypeName(ds.GetRasterBand(3).DataType)

        assert b1 == "Byte", f"Band 1 should be Byte (hillshade), got {b1}"
        assert b2 == "Float32", f"Band 2 should be Float32 (slope), got {b2}"
        assert b3 == "Float32", f"Band 3 should be Float32 (DEM), got {b3}"

        # Band 2 must be slope (values < 45), Band 3 must be DEM (values > 45)
        b2_max = ds.GetRasterBand(2).GetStatistics(True, True)[1]
        b3_max = ds.GetRasterBand(3).GetStatistics(True, True)[1]
        assert b2_max < 45, (
            f"Band 2 max={b2_max:.1f} — should be slope (<45 deg), "
            f"bands are likely in wrong order"
        )
        assert b3_max > 45, (
            f"Band 3 max={b3_max:.1f} — should be DEM (>45m elevation)"
        )


# ── NoData Handling ──────────────────────────────────────────────────────


class TestNoData:
    """NoData preservation through pipeline."""

    def test_dem_nodata(self):
        """Reprojected DEM must have NoData=-9999 with pixels present."""
        dem = gdal.Open(os.path.join(OUTPUT, "dem_3035.tif"))
        band = dem.GetRasterBand(1)
        nd = band.GetNoDataValue()
        assert nd == -9999.0, f"NoData should be -9999, got {nd}"
        arr = band.ReadAsArray()
        assert np.sum(arr == nd) > 0, "No NoData pixels found"


# ── Audit Report ─────────────────────────────────────────────────────────


class TestAudit:
    """Pipeline audit report."""

    def test_audit_exists_and_schema(self):
        """Audit JSON must exist with entries for all five rasters."""
        path = os.path.join(OUTPUT, "audit.json")
        assert os.path.exists(path), "audit.json not found"
        with open(path) as f:
            audit = json.load(f)

        required = ["dem_3035.tif", "zones_raster.tif", "hillshade.tif",
                     "slope_deg.tif", "dem_norm.tif"]
        for name in required:
            assert name in audit, f"audit.json missing entry for '{name}'"
            entry = audit[name]
            for field in ["crs_epsg", "width", "height", "band_count",
                          "pixel_size_x", "pixel_size_y", "min_value", "max_value"]:
                assert field in entry, f"audit['{name}'] missing field '{field}'"

    def test_audit_crs_consistency(self):
        """All audited rasters must report EPSG:3035."""
        with open(os.path.join(OUTPUT, "audit.json")) as f:
            audit = json.load(f)
        for name, entry in audit.items():
            assert entry["crs_epsg"] == 3035, (
                f"audit['{name}'] CRS should be 3035, got {entry['crs_epsg']}"
            )

    def test_audit_dimensions_consistent(self):
        """DEM, zones_raster, hillshade, slope must share dimensions."""
        with open(os.path.join(OUTPUT, "audit.json")) as f:
            audit = json.load(f)
        ref_w = audit["dem_3035.tif"]["width"]
        ref_h = audit["dem_3035.tif"]["height"]
        for name in ["zones_raster.tif", "hillshade.tif", "slope_deg.tif", "dem_norm.tif"]:
            assert audit[name]["width"] == ref_w, (
                f"{name} width {audit[name]['width']} != DEM width {ref_w}"
            )
            assert audit[name]["height"] == ref_h, (
                f"{name} height {audit[name]['height']} != DEM height {ref_h}"
            )
