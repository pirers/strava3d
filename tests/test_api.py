"""Integration tests for the /render API endpoint."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"
client = TestClient(app)


def _gpx_bytes() -> bytes:
    return (FIXTURES / "sample.gpx").read_bytes()


def test_render_returns_200_with_svg():
    resp = client.post("/render", files={"gpx": ("track.gpx", _gpx_bytes(), "application/gpx+xml")})
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers["content-type"]
    assert "<svg" in resp.text


def test_render_default_dimensions():
    resp = client.post("/render", files={"gpx": ("t.gpx", _gpx_bytes())})
    assert resp.status_code == 200
    assert 'width="300mm"' in resp.text
    assert 'height="300mm"' in resp.text


def test_render_custom_dimensions():
    resp = client.post(
        "/render?width=100&height=150&unit=px",
        files={"gpx": ("t.gpx", _gpx_bytes())},
    )
    assert resp.status_code == 200
    assert 'width="100px"' in resp.text
    assert 'height="150px"' in resp.text


def test_render_frame():
    resp = client.post("/render?frame=true", files={"gpx": ("t.gpx", _gpx_bytes())})
    assert resp.status_code == 200
    assert "<rect" in resp.text


def test_render_no_frame():
    resp = client.post("/render?frame=false", files={"gpx": ("t.gpx", _gpx_bytes())})
    assert resp.status_code == 200
    assert "<rect" not in resp.text


def test_render_name_param():
    resp = client.post(
        "/render?name=MyRun",
        files={"gpx": ("t.gpx", _gpx_bytes())},
    )
    assert resp.status_code == 200
    assert "MyRun" in resp.text


def test_render_stats():
    resp = client.post("/render?stats=true", files={"gpx": ("t.gpx", _gpx_bytes())})
    assert resp.status_code == 200
    assert "km" in resp.text
    assert "↑" in resp.text


def test_render_invalid_unit_400():
    resp = client.post(
        "/render?unit=cm",
        files={"gpx": ("t.gpx", _gpx_bytes())},
    )
    assert resp.status_code == 400


def test_render_invalid_gpx_400():
    resp = client.post(
        "/render",
        files={"gpx": ("bad.gpx", b"not xml at all", "application/gpx+xml")},
    )
    assert resp.status_code == 400


def test_render_empty_file_400():
    resp = client.post(
        "/render",
        files={"gpx": ("empty.gpx", b"", "application/gpx+xml")},
    )
    assert resp.status_code == 400


def test_render_padding_too_large_400():
    resp = client.post(
        "/render?width=100&height=100&padding=60",
        files={"gpx": ("t.gpx", _gpx_bytes())},
    )
    assert resp.status_code == 400


def test_render_name_from_gpx_when_not_overridden():
    """GPX track name should appear in SVG when no name param is supplied."""
    resp = client.post("/render", files={"gpx": ("t.gpx", _gpx_bytes())})
    # sample.gpx has name "Test Track" — but name param defaults to None,
    # so GPX name is used only if name query param is absent
    # The endpoint uses GPX name when ?name is not supplied
    assert resp.status_code == 200
    # Track name "Test Track" should appear since it's picked up from GPX
    assert "Test Track" in resp.text


def test_render_elevation_profile():
    """elevation_profile=true should produce a separator line and profile path."""
    resp = client.post(
        "/render?elevation_profile=true",
        files={"gpx": ("t.gpx", _gpx_bytes())},
    )
    assert resp.status_code == 200
    assert "<line" in resp.text
    assert resp.text.count("<path") >= 2


def test_render_no_elevation_profile_by_default():
    """Default render must not include a separator line."""
    resp = client.post("/render", files={"gpx": ("t.gpx", _gpx_bytes())})
    assert resp.status_code == 200
    assert "<line" not in resp.text


def test_render_view_3d():
    """view_3d=true should produce a 3D isometric SVG with path elements."""
    resp = client.post(
        "/render?view_3d=true",
        files={"gpx": ("t.gpx", _gpx_bytes())},
    )
    assert resp.status_code == 200
    assert "<svg" in resp.text
    assert "<path" in resp.text


def test_render_view_3d_default_false():
    """By default, view_3d is off and the flat map is used."""
    resp = client.post("/render", files={"gpx": ("t.gpx", _gpx_bytes())})
    assert resp.status_code == 200
    # Flat map: no <g transform> wrapper from the 3-D renderer.
    assert '<g transform=' not in resp.text
