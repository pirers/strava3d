"""SVG rendering helpers for GPX tracks."""
from __future__ import annotations

from typing import List, Optional, Tuple


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
    """
    # Reserve 15 % of height for text if name or stats are requested
    has_text = bool(name or stats)
    text_zone_h = height * 0.15 if has_text else 0.0
    track_offset_y = text_zone_h
    track_height = height - text_zone_h

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
