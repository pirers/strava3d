"""Integration tests for the /render_terrain endpoint."""
from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.dem_fetcher import DemGrid
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"
client = TestClient(app)


def _gpx_bytes() -> bytes:
    return (FIXTURES / "sample.gpx").read_bytes()


def _flat_dem(n: int = 16) -> DemGrid:
    """Return a tiny flat DEM grid (all elevations = 500 m) for fast testing."""
    return DemGrid(
        elevations=[[500.0] * n for _ in range(n)],
        lat_min=47.0,
        lat_max=47.04,
        lon_min=8.0,
        lon_max=8.03,
    )


def _varied_dem(n: int = 16) -> DemGrid:
    """Return a DEM grid with a simple elevation gradient."""
    return DemGrid(
        elevations=[[500.0 + r * 2 + c for c in range(n)] for r in range(n)],
        lat_min=47.0,
        lat_max=47.04,
        lon_min=8.0,
        lon_max=8.03,
    )


def _post_terrain(dem: DemGrid, **extra_params):
    """POST to /render_terrain with a mocked DEM and return the response."""
    with patch("app.main.fetch_dem_grid", return_value=dem):
        return client.post(
            "/render_terrain",
            files={"gpx": ("track.gpx", _gpx_bytes(), "application/gpx+xml")},
            params=extra_params,
        )


# ---------------------------------------------------------------------------
# Basic happy-path tests
# ---------------------------------------------------------------------------

def test_render_terrain_returns_200():
    resp = _post_terrain(_flat_dem())
    assert resp.status_code == 200


def test_render_terrain_content_type_zip():
    resp = _post_terrain(_flat_dem())
    assert "application/zip" in resp.headers["content-type"]


def test_render_terrain_zip_contains_both_stl_files():
    resp = _post_terrain(_flat_dem())
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
    assert "terrain.stl" in names
    assert "track.stl" in names


def test_render_terrain_no_water_stl_when_all_land():
    """When all DEM cells are well above sea level there should be no water.stl."""
    resp = _post_terrain(_flat_dem())  # flat_dem has 500 m elevations
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
    assert "water.stl" not in names


def _ocean_dem(n: int = 16) -> DemGrid:
    """Return a DEM where all cells are at sea level (0 m) – simulates ocean."""
    return DemGrid(
        elevations=[[0.0] * n for _ in range(n)],
        lat_min=47.0,
        lat_max=47.04,
        lon_min=8.0,
        lon_max=8.03,
    )


def _coastal_dem(n: int = 16) -> DemGrid:
    """Return a DEM with mixed land (left half) and ocean (right half)."""
    half = n // 2
    rows = []
    for _ in range(n):
        row = [0.0] * half + [200.0] * (n - half)
        rows.append(row)
    return DemGrid(
        elevations=rows,
        lat_min=47.0,
        lat_max=47.04,
        lon_min=8.0,
        lon_max=8.03,
    )


def test_render_terrain_water_stl_present_for_ocean_dem():
    """When DEM cells are at sea level, water.stl should be included."""
    resp = _post_terrain(_ocean_dem(), sea_level_m=0.0)
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
    assert "water.stl" in names


def test_render_terrain_water_stl_valid_binary_stl():
    resp = _post_terrain(_ocean_dem(), sea_level_m=0.0)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        water_bytes = zf.read("water.stl")
    assert len(water_bytes) >= 84
    n_triangles = struct.unpack_from("<I", water_bytes, 80)[0]
    assert n_triangles > 0
    assert len(water_bytes) == 84 + n_triangles * 50


def test_render_terrain_coastal_has_partial_water():
    """Coastal DEM (half ocean) should include water.stl when sea_level_m=0."""
    resp = _post_terrain(_coastal_dem(), sea_level_m=0.0)
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
    assert "water.stl" in names


def test_render_terrain_zip_contains_readme():
    resp = _post_terrain(_flat_dem())
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
    assert "README.txt" in names


def test_render_terrain_stl_has_binary_header():
    """Binary STL starts with 80-byte header + 4-byte triangle count."""
    resp = _post_terrain(_flat_dem())
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        terrain_bytes = zf.read("terrain.stl")
    assert len(terrain_bytes) >= 84
    n_triangles = struct.unpack_from("<I", terrain_bytes, 80)[0]
    assert n_triangles > 0
    # Each triangle is 50 bytes (normal + 3 vertices + attr)
    assert len(terrain_bytes) == 84 + n_triangles * 50


def test_render_terrain_track_stl_is_valid_binary_stl():
    resp = _post_terrain(_flat_dem())
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        track_bytes = zf.read("track.stl")
    assert len(track_bytes) >= 84
    n_triangles = struct.unpack_from("<I", track_bytes, 80)[0]
    assert n_triangles > 0
    assert len(track_bytes) == 84 + n_triangles * 50


def test_render_terrain_varied_elevation():
    """Model with real elevation variation still produces valid STL."""
    resp = _post_terrain(_varied_dem())
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        terrain_bytes = zf.read("terrain.stl")
    n_triangles = struct.unpack_from("<I", terrain_bytes, 80)[0]
    assert n_triangles > 0


# ---------------------------------------------------------------------------
# Parameter validation tests
# ---------------------------------------------------------------------------

def test_render_terrain_custom_model_size():
    resp = _post_terrain(_flat_dem(), model_size_mm=200.0)
    assert resp.status_code == 200


def test_render_terrain_custom_padding():
    resp = _post_terrain(_flat_dem(), terrain_padding_km=1.0)
    assert resp.status_code == 200


def test_render_terrain_custom_track_width():
    resp = _post_terrain(_flat_dem(), track_width_mm=3.0)
    assert resp.status_code == 200


def test_render_terrain_custom_terrain_height():
    resp = _post_terrain(_flat_dem(), terrain_height_mm=30.0)
    assert resp.status_code == 200


def test_render_terrain_custom_base_thickness():
    resp = _post_terrain(_flat_dem(), base_thickness_mm=5.0)
    assert resp.status_code == 200


def test_render_terrain_empty_gpx_400():
    with patch("app.main.fetch_dem_grid", return_value=_flat_dem()):
        resp = client.post(
            "/render_terrain",
            files={"gpx": ("empty.gpx", b"", "application/gpx+xml")},
        )
    assert resp.status_code == 400


def test_render_terrain_invalid_gpx_400():
    with patch("app.main.fetch_dem_grid", return_value=_flat_dem()):
        resp = client.post(
            "/render_terrain",
            files={"gpx": ("bad.gpx", b"not xml", "application/gpx+xml")},
        )
    assert resp.status_code == 400


def test_render_terrain_dem_resolution_default():
    """Default dem_resolution=128 produces a non-trivial mesh."""
    resp = _post_terrain(_flat_dem(16))
    assert resp.status_code == 200


def test_render_terrain_sea_level_param():
    """sea_level_m parameter is accepted and processed without error."""
    resp = _post_terrain(_flat_dem(), sea_level_m=5.0)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Track positioning tests (regression for padding bug)
# ---------------------------------------------------------------------------

def test_track_positioned_within_model_with_padding():
    """Track ribbon XY coordinates must lie within the model boundaries.

    With padding, the track should occupy only the central portion of the
    model block – its model-space coordinates must be strictly inside
    [0, x_size] × [0, y_size].
    """
    import struct as _struct
    from app.dem_fetcher import DemGrid
    from app.gpx_parser import parse_gpx
    from app.stl_generator import TerrainModelConfig, generate_terrain_stls

    # DEM covers a 0.04°×0.03° area – larger than the 5-point GPX track
    # which spans 0.04°×0.02°, so there is genuine padding in all directions.
    dem = DemGrid(
        elevations=[[500.0] * 32 for _ in range(32)],
        lat_min=46.99,
        lat_max=47.05,
        lon_min=7.99,
        lon_max=8.03,
    )
    gpx_bytes = (FIXTURES / "sample.gpx").read_bytes()
    track_data = parse_gpx(gpx_bytes)
    config = TerrainModelConfig(model_size_mm=100)

    _, track_stl, _ = generate_terrain_stls(track_data, dem, config)

    # Read all vertex XY from the binary STL (skip 84-byte header, then
    # each triangle is: 12 normal + 3×12 vertex + 2 attr = 50 bytes)
    n = _struct.unpack_from("<I", track_stl, 80)[0]
    xs, ys = [], []
    for i in range(n):
        offset = 84 + i * 50
        for vi in range(3):
            vx, vy = _struct.unpack_from("<ff", track_stl, offset + 12 + vi * 12)
            xs.append(vx)
            ys.append(vy)

    # Track must not reach the model edges (DEM extends ~6km beyond track bbox)
    # Allow 1 mm tolerance for the ribbon half-width.
    x_size = 100.0  # model_size_mm (square-ish for this bbox)
    assert min(xs) > -1.0, "Track left edge is outside the model"
    assert max(xs) < x_size + 1.0, "Track right edge is outside the model"
    assert min(ys) > -1.0, "Track bottom edge is outside the model"
    assert max(ys) < x_size + 1.0, "Track top edge is outside the model"

    # Track must NOT stretch edge-to-edge (old bug: track filled full extent)
    assert max(xs) - min(xs) < x_size * 0.95, (
        "Track X span nearly equals model width – padding not applied"
    )


# ---------------------------------------------------------------------------
# DemGrid unit tests
# ---------------------------------------------------------------------------

def test_dem_grid_sample_corner():
    dem = _flat_dem(4)
    # All corners should return 500 m
    assert dem.sample(47.0, 8.0) == pytest.approx(500.0, abs=1e-3)
    assert dem.sample(47.04, 8.03) == pytest.approx(500.0, abs=1e-3)


def test_dem_grid_sample_outside_returns_zero():
    dem = _flat_dem(4)
    assert dem.sample(0.0, 0.0) == pytest.approx(0.0)


def test_dem_grid_sample_bilinear():
    """Centre of a 2×2 grid with corners 0,1,2,3 should be 1.5."""
    dem = DemGrid(
        elevations=[[0.0, 1.0], [2.0, 3.0]],
        lat_min=0.0, lat_max=1.0,
        lon_min=0.0, lon_max=1.0,
    )
    result = dem.sample(0.5, 0.5)
    assert result == pytest.approx(1.5, abs=1e-6)
