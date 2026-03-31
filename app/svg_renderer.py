"""SVG rendering helpers for GPX tracks."""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

# Fraction of canvas height reserved for the elevation profile panel.
_PROFILE_RATIO = 0.28


def _normalize(
    xy: List[Tuple[float, float]],
    width: float,
    height: float,
    padding: float,
) -> List[Tuple[float, float]]:
    """Scale and translate projected points to fit within the drawing area.

    The drawing area is ``width x height`` minus ``padding`` on each side.
    The Y-axis is inverted so that north is up in SVG coordinates.

    If all points are identical (degenerate track), they are placed at the
    centre of the drawing area.
    """
    if not xy:
        return []

    xs = [p[0] for p in xy]
    ys = [p[1] for p in xy]

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    draw_w = width - 2 * padding
    draw_h = height - 2 * padding

    # Guard against degenerate tracks (single point / zero span)
    span_x = x_max - x_min
    span_y = y_max - y_min

    if span_x == 0 and span_y == 0:
        return [(width / 2, height / 2)] * len(xy)

    if span_x == 0:
        scale = draw_h / span_y
    elif span_y == 0:
        scale = draw_w / span_x
    else:
        scale = min(draw_w / span_x, draw_h / span_y)

    # Centre the track in the drawing area
    scaled_w = span_x * scale
    scaled_h = span_y * scale
    offset_x = padding + (draw_w - scaled_w) / 2
    offset_y = padding + (draw_h - scaled_h) / 2

    result: List[Tuple[float, float]] = []
    for x, y in xy:
        nx = (x - x_min) * scale + offset_x
        # Invert Y axis for SVG (SVG y increases downward)
        ny = (y_max - y) * scale + offset_y
        result.append((nx, ny))
    return result


def _build_path(points: List[Tuple[float, float]]) -> str:
    """Build an SVG path ``d`` attribute string from normalised points."""
    if not points:
        return ""
    parts = [f"M {points[0][0]:.3f},{points[0][1]:.3f}"]
    for x, y in points[1:]:
        parts.append(f"L {x:.3f},{y:.3f}")
    return " ".join(parts)


def _render_elevation_profile(
    xy: List[Tuple[float, float]],
    elevations: List[Optional[float]],
    x_offset: float,
    y_offset: float,
    width: float,
    height: float,
    padding: float,
    stroke_width: float,
) -> List[str]:
    """Render an elevation-profile polyline into a bounding box.

    Args:
        xy: Raw projected (x, y) coordinates in metres – used to compute
            cumulative distance along the track (X axis of the profile).
        elevations: Elevation in metres for each track point (may contain
            ``None`` where data is absent).
        x_offset: Left edge of the bounding box in SVG user units.
        y_offset: Top edge of the bounding box in SVG user units.
        width: Width of the bounding box in SVG user units.
        height: Height of the bounding box in SVG user units.
        padding: Inner padding applied on all sides.
        stroke_width: Stroke width for the profile polyline.

    Returns:
        A list of SVG element strings (may be empty if data is insufficient).
    """
    if len(xy) < 2 or len(elevations) < 2:
        return []

    # Pair each index with its elevation value; skip missing elevations.
    pairs: List[Tuple[int, float]] = [
        (i, e) for i, e in enumerate(elevations) if e is not None and i < len(xy)
    ]
    if len(pairs) < 2:
        return []

    # Cumulative distances (metres) between successive projected points.
    cum_dists: List[float] = [0.0]
    for i in range(1, len(xy)):
        dx = xy[i][0] - xy[i - 1][0]
        dy = xy[i][1] - xy[i - 1][1]
        cum_dists.append(cum_dists[-1] + math.sqrt(dx * dx + dy * dy))

    total_dist = cum_dists[-1]
    if total_dist == 0.0:
        # Degenerate track: space points equally along the X axis.
        total_dist = float(len(xy) - 1)
        cum_dists = [float(i) for i in range(len(xy))]

    eles = [e for _, e in pairs]
    ele_min, ele_max = min(eles), max(eles)
    ele_span = ele_max - ele_min

    draw_w = width - 2 * padding
    draw_h = height - 2 * padding
    if draw_w <= 0 or draw_h <= 0:
        return []

    profile_pts: List[Tuple[float, float]] = []
    for idx, ele in pairs:
        d = cum_dists[idx] / total_dist  # normalised 0..1
        px = x_offset + padding + d * draw_w
        if ele_span > 0:
            # Higher elevation → smaller SVG y (upward)
            py = y_offset + padding + draw_h - ((ele - ele_min) / ele_span) * draw_h
        else:
            py = y_offset + padding + draw_h / 2  # flat profile: centre line
        profile_pts.append((px, py))

    path_d = _build_path(profile_pts)
    sw = _fmt(stroke_width)
    return [
        f'  <path d="{path_d}" fill="none" stroke="black" '
        f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"/>'
    ]


def render_svg(
    xy: List[Tuple[float, float]],
    width: float,
    height: float,
    padding: float,
    stroke_width: float,
    unit: str,
    frame: bool = False,
    name: Optional[str] = None,
    stats: Optional[str] = None,
    elevations: Optional[List[Optional[float]]] = None,
) -> str:
    """Render an SVG string from projected track points.

    Args:
        xy: Raw projected (x, y) coordinates in metres.
        width: Canvas width in *unit*.
        height: Canvas height in *unit*.
        padding: Inner padding in *unit*.
        stroke_width: Stroke width in *unit*.
        unit: CSS unit string, e.g. ``"mm"`` or ``"px"``.
        frame: Whether to draw a border rectangle.
        name: Optional track name to render as text.
        stats: Optional stats string to render as text (e.g. ``"12.3 km | 456 m"``)
        elevations: Optional per-point elevation values (metres). When provided
            the bottom :data:`_PROFILE_RATIO` of the canvas is used to draw an
            elevation-profile chart.
    """
    # ── Layout ──────────────────────────────────────────────────────────────
    # Canvas is split top-to-bottom:
    #   [text zone]  [track map]  [separator]  [elevation profile]
    #
    # When elevation_profile is disabled (elevations=None), the profile zone
    # and separator are zero-height, so the layout is unchanged vs. the
    # original behaviour.

    has_elev = elevations is not None and any(e is not None for e in elevations)
    has_text = bool(name or stats)

    profile_zone_h = height * _PROFILE_RATIO if has_elev else 0.0
    # A thin separator between track area and profile panel.
    sep_h = stroke_width * 3 if has_elev else 0.0

    # Height available for text + track map.
    available_h = height - profile_zone_h - sep_h

    text_zone_h = available_h * 0.15 if has_text else 0.0
    track_offset_y = text_zone_h
    track_height = available_h - text_zone_h

    normalised = _normalize(xy, width, track_height, padding)

    # Shift track points down by text_zone_h
    shifted = [(x, y + track_offset_y) for x, y in normalised]

    path_d = _build_path(shifted)

    u = unit
    lines: List[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_fmt(width)}{u}" height="{_fmt(height)}{u}" '
        f'viewBox="0 0 {_fmt(width)} {_fmt(height)}">'
    )

    if frame:
        lines.append(
            f'  <rect x="0" y="0" width="{_fmt(width)}" height="{_fmt(height)}" '
            f'fill="none" stroke="black" stroke-width="{_fmt(stroke_width)}"/>'
        )

    if has_text:
        font_size = text_zone_h * 0.35
        font_size = max(font_size, 1.0)
        y_cursor = text_zone_h * 0.4

        if name:
            lines.append(
                f'  <text x="{_fmt(padding)}" y="{y_cursor:.3f}" '
                f'font-size="{font_size:.3f}" font-family="sans-serif" '
                f'fill="black">{_escape_xml(name)}</text>'
            )
            y_cursor += font_size * 1.3

        if stats:
            lines.append(
                f'  <text x="{_fmt(padding)}" y="{y_cursor:.3f}" '
                f'font-size="{font_size:.3f}" font-family="sans-serif" '
                f'fill="black">{_escape_xml(stats)}</text>'
            )

    if path_d:
        lines.append(
            f'  <path d="{path_d}" '
            f'fill="none" stroke="black" stroke-width="{_fmt(stroke_width)}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )

    # ── Elevation profile ────────────────────────────────────────────────────
    if has_elev:
        assert elevations is not None  # narrowing for type checkers
        # Separator line between track area and profile panel.
        sep_y = available_h + sep_h / 2
        lines.append(
            f'  <line x1="{_fmt(padding)}" y1="{sep_y:.3f}" '
            f'x2="{_fmt(width - padding)}" y2="{sep_y:.3f}" '
            f'stroke="black" stroke-width="{_fmt(stroke_width * 0.5)}"/>'
        )
        # Profile panel starts below the separator.
        profile_y = available_h + sep_h
        profile_lines = _render_elevation_profile(
            xy=xy,
            elevations=elevations,
            x_offset=0.0,
            y_offset=profile_y,
            width=width,
            height=profile_zone_h,
            padding=padding,
            stroke_width=stroke_width,
        )
        lines.extend(profile_lines)

    lines.append("</svg>")
    return "\n".join(lines)


def _fmt(value: float) -> str:
    """Format a float without trailing zeros (e.g. 300.0 → '300', 10.5 → '10.5')."""
    return f"{value:g}"


def _escape_xml(text: str) -> str:
    """Escape characters that are special in XML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
