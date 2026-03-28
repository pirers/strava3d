"""Unit tests for GPX parsing, distance and elevation calculation."""
import math
from pathlib import Path

import pytest

from app.gpx_parser import TrackPoint, _haversine_m, parse_gpx, project_points

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_gpx_returns_correct_number_of_points():
    gpx_bytes = (FIXTURES / "sample.gpx").read_bytes()
    data = parse_gpx(gpx_bytes)
    assert len(data.points) == 5


def test_parse_gpx_name():
    gpx_bytes = (FIXTURES / "sample.gpx").read_bytes()
    data = parse_gpx(gpx_bytes)
    assert data.name == "Test Track"


def test_parse_gpx_first_point_coords():
    gpx_bytes = (FIXTURES / "sample.gpx").read_bytes()
    data = parse_gpx(gpx_bytes)
    assert data.points[0].lat == pytest.approx(47.0, rel=1e-5)
    assert data.points[0].lon == pytest.approx(8.0, rel=1e-5)
    assert data.points[0].ele == pytest.approx(500.0, rel=1e-5)


def test_parse_gpx_distance_positive():
    gpx_bytes = (FIXTURES / "sample.gpx").read_bytes()
    data = parse_gpx(gpx_bytes)
    assert data.distance_km > 0


def test_parse_gpx_distance_reasonable():
    """Track spans ~4.5 km north; check rough magnitude."""
    gpx_bytes = (FIXTURES / "sample.gpx").read_bytes()
    data = parse_gpx(gpx_bytes)
    # 4 segments of ~1.1 km each => ~4-5 km
    assert 3.0 < data.distance_km < 6.0


def test_parse_gpx_elevation_gain():
    """Expected positive gains: 500->520 (+20), 510->540 (+30), -> 50 m total."""
    gpx_bytes = (FIXTURES / "sample.gpx").read_bytes()
    data = parse_gpx(gpx_bytes)
    assert data.elevation_gain_m == pytest.approx(50.0, rel=1e-5)


def test_parse_gpx_no_elevation():
    """If ele is absent, elevation_gain_m should be 0."""
    gpx_no_ele = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="47.0" lon="8.0"/>
    <trkpt lat="47.1" lon="8.1"/>
  </trkseg></trk>
</gpx>"""
    data = parse_gpx(gpx_no_ele)
    assert data.elevation_gain_m == 0.0


def test_parse_gpx_invalid_raises():
    with pytest.raises(ValueError, match="Invalid GPX"):
        parse_gpx(b"not valid xml")


def test_parse_gpx_empty_track_raises():
    gpx_empty = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg></trkseg></trk>
</gpx>"""
    with pytest.raises(ValueError, match="no track points"):
        parse_gpx(gpx_empty)


def test_haversine_known_distance():
    """Haversine between two points ~1 degree apart in latitude (~111 km)."""
    d = _haversine_m(0.0, 0.0, 1.0, 0.0)
    assert d == pytest.approx(111_195, rel=0.01)


def test_project_points_returns_same_count():
    pts = [TrackPoint(lat=47.0, lon=8.0), TrackPoint(lat=47.1, lon=8.1)]
    xy = project_points(pts)
    assert len(xy) == 2


def test_project_points_x_increases_east():
    pts = [TrackPoint(lat=47.0, lon=8.0), TrackPoint(lat=47.0, lon=9.0)]
    xy = project_points(pts)
    assert xy[1][0] > xy[0][0]


def test_project_points_y_increases_north():
    pts = [TrackPoint(lat=47.0, lon=8.0), TrackPoint(lat=48.0, lon=8.0)]
    xy = project_points(pts)
    assert xy[1][1] > xy[0][1]
