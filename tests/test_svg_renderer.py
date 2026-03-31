"""Unit tests for SVG normalisation, scaling and rendering."""
import pytest

from app.svg_renderer import _normalize, _build_path, render_svg


def test_normalize_single_point_centered():
    pts = [(0.0, 0.0)]
    result = _normalize(pts, width=100, height=100, padding=10)
    assert len(result) == 1
    x, y = result[0]
    assert x == pytest.approx(50.0)
    assert y == pytest.approx(50.0)


def test_normalize_output_within_bounds():
    pts = [(0.0, 0.0), (1000.0, 500.0), (500.0, 1000.0)]
    width, height, padding = 300.0, 300.0, 10.0
    result = _normalize(pts, width=width, height=height, padding=padding)
    for x, y in result:
        assert padding <= x <= width - padding
        assert padding <= y <= height - padding


def test_normalize_y_axis_inverted():
    """Point with higher projected-y should have lower SVG-y (i.e. appear higher)."""
    pts = [(0.0, 0.0), (0.0, 1000.0)]
    result = _normalize(pts, width=100, height=100, padding=0)
    # pts[1] has higher y → should map to a smaller SVG y (higher on screen)
    assert result[1][1] < result[0][1]


def test_normalize_preserves_aspect_ratio():
    """A perfectly square track should fill width and height equally."""
    pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    result = _normalize(pts, width=200, height=200, padding=0)
    xs = [p[0] for p in result]
    ys = [p[1] for p in result]
    assert max(xs) - min(xs) == pytest.approx(max(ys) - min(ys), rel=1e-5)


def test_build_path_basic():
    pts = [(0.0, 0.0), (10.0, 20.0)]
    d = _build_path(pts)
    assert d.startswith("M 0.000,0.000")
    assert "L 10.000,20.000" in d


def test_build_path_empty():
    assert _build_path([]) == ""


def test_render_svg_contains_svg_tag():
    svg = render_svg(
        xy=[(0.0, 0.0), (1000.0, 1000.0)],
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
    )
    assert "<svg" in svg
    assert "</svg>" in svg


def test_render_svg_contains_path():
    svg = render_svg(
        xy=[(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0)],
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
    )
    assert '<path' in svg
    assert 'stroke="black"' in svg
    assert 'fill="none"' in svg


def test_render_svg_frame():
    svg = render_svg(
        xy=[(0.0, 0.0), (1.0, 1.0)],
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
        frame=True,
    )
    assert "<rect" in svg


def test_render_svg_no_frame():
    svg = render_svg(
        xy=[(0.0, 0.0), (1.0, 1.0)],
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
        frame=False,
    )
    assert "<rect" not in svg


def test_render_svg_name_text():
    svg = render_svg(
        xy=[(0.0, 0.0), (1.0, 1.0)],
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
        name="My Track",
    )
    assert "My Track" in svg
    assert "<text" in svg


def test_render_svg_stats_text():
    svg = render_svg(
        xy=[(0.0, 0.0), (1.0, 1.0)],
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
        stats="12.3 km  |  456 m ↑",
    )
    assert "12.3 km" in svg


def test_render_svg_mm_unit_in_dimensions():
    svg = render_svg(
        xy=[(0.0, 0.0), (1.0, 1.0)],
        width=200,
        height=150,
        padding=5,
        stroke_width=1,
        unit="mm",
    )
    assert 'width="200mm"' in svg
    assert 'height="150mm"' in svg


def test_render_svg_xml_escaping():
    svg = render_svg(
        xy=[(0.0, 0.0), (1.0, 1.0)],
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
        name='<Track & "Test">',
    )
    assert "&lt;Track" in svg
    assert "&amp;" in svg


# ── Elevation profile tests ──────────────────────────────────────────────────

_ELEV_XY = [(0.0, 0.0), (500.0, 0.0), (1000.0, 0.0), (1500.0, 0.0), (2000.0, 0.0)]
_ELEV_VALUES = [500.0, 520.0, 510.0, 540.0, 530.0]


def test_render_svg_elevation_profile_contains_profile_path():
    svg = render_svg(
        xy=_ELEV_XY,
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
        elevations=_ELEV_VALUES,
    )
    # Should contain at least two <path elements: track map + profile
    assert svg.count("<path") >= 2


def test_render_svg_elevation_profile_separator_line():
    svg = render_svg(
        xy=_ELEV_XY,
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
        elevations=_ELEV_VALUES,
    )
    assert "<line" in svg


def test_render_svg_no_elevation_profile_by_default():
    """When elevations=None (default), no separator line is drawn."""
    svg = render_svg(
        xy=_ELEV_XY,
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
    )
    assert "<line" not in svg
    assert svg.count("<path") == 1


def test_render_svg_elevation_profile_all_none_skipped():
    """If all elevation values are None, no profile is rendered."""
    svg = render_svg(
        xy=_ELEV_XY,
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
        elevations=[None, None, None, None, None],
    )
    assert "<line" not in svg
    assert svg.count("<path") == 1


def test_render_svg_elevation_profile_flat():
    """Flat elevation (constant) should still render without error."""
    svg = render_svg(
        xy=_ELEV_XY,
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
        elevations=[500.0, 500.0, 500.0, 500.0, 500.0],
    )
    assert "<line" in svg
    assert svg.count("<path") >= 2


def test_render_svg_elevation_profile_dimensions_unchanged():
    """Canvas dimensions must remain the same whether profile is on or off."""
    svg_with = render_svg(
        xy=_ELEV_XY,
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
        elevations=_ELEV_VALUES,
    )
    svg_without = render_svg(
        xy=_ELEV_XY,
        width=300,
        height=300,
        padding=10,
        stroke_width=2,
        unit="mm",
    )
    assert 'width="300mm"' in svg_with
    assert 'height="300mm"' in svg_with
    assert 'width="300mm"' in svg_without
    assert 'height="300mm"' in svg_without
