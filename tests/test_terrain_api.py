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
