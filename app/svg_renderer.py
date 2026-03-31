"""SVG rendering helpers for GPX tracks."""
from __future__ import annotations

import math
from typing import List, Optional, Set, Tuple

# Fraction of canvas height reserved for the elevation profile panel.
_PROFILE_RATIO = 0.28

# Vertical scale used in the isometric 3D projection.
# A value of 0.5 means the elevation axis spans half the horizontal extent.
_ISO_Z_SCALE = 0.5


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


def _fill_elevations(elevations: List[Optional[float]], count: int) -> List[float]:
    """Return exactly *count* elevation floats, filling ``None`` gaps.

    Strategy: forward-fill then backward-fill; any remaining ``None`` (i.e.
    all values were absent) is replaced with ``0.0``.
    """
    eles: List[Optional[float]] = list(elevations[:count])
    while len(eles) < count:
        eles.append(None)

    # Forward fill
    last: Optional[float] = None
    for i, e in enumerate(eles):
        if e is not None:
            last = e
        elif last is not None:
            eles[i] = last

    # Backward fill
    last = None
    for i in range(len(eles) - 1, -1, -1):
        if eles[i] is not None:
            last = eles[i]
        elif last is not None:
            eles[i] = last

    return [e if e is not None else 0.0 for e in eles]


def _render_3d_track(
    xy: List[Tuple[float, float]],
    elevations: List[Optional[float]],
    width: float,
    height: float,
    padding: float,
    stroke_width: float,
) -> List[str]:
    """Render a 3-D isometric view of the track, combining geographic and elevation data.

    The projection used is the standard isometric cabinet projection::

        screen_x = (norm_x - norm_y) * cos(30°)
        screen_y = (norm_x + norm_y) * sin(30°) − norm_z * _ISO_Z_SCALE

    where *norm_x* and *norm_y* are the normalised geographic coordinates in
    [0, 1] and *norm_z* is the normalised elevation also in [0, 1].

    The function draws (back-to-front paint order):

    1. Dashed ground-level track shadow.
    2. Vertical "rib" lines at ~every 10 % of the track, connecting the
       elevated point to the ground plane.
    3. The elevated track path (solid, full stroke width).

    Args:
        xy: Raw projected (x, y) coordinates in metres.
        elevations: Per-point elevation values; ``None`` gaps are filled.
        width: Canvas width in SVG user units.
        height: Canvas height in SVG user units.
        padding: Inner padding in SVG user units.
        stroke_width: Base stroke width.

    Returns:
        A list of SVG element strings (empty when fewer than 2 points).
    """
    if len(xy) < 2:
        return []

    eles = _fill_elevations(elevations, len(xy))

    # ── Normalise 3-D coordinates ────────────────────────────────────────────
    xs = [p[0] for p in xy]
    ys = [p[1] for p in xy]

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    ele_min, ele_max = min(eles), max(eles)

    # Preserve the geographic aspect ratio (same scale for x and y).
    horiz_span = max(x_max - x_min, y_max - y_min, 1.0)
    ele_span = max(ele_max - ele_min, 1.0)

    cos30 = math.cos(math.radians(30))
    sin30 = math.sin(math.radians(30))

    def _iso(px: float, py: float, pz: float) -> Tuple[float, float]:
        nx = (px - x_min) / horiz_span
        ny = (py - y_min) / horiz_span
        nz = (pz - ele_min) / ele_span * _ISO_Z_SCALE
        sx = (nx - ny) * cos30
        sy = (nx + ny) * sin30 - nz
        return sx, sy

    # Projected points – elevated and at ground level.
    elev_pts = [_iso(x, y, e) for (x, y), e in zip(xy, eles)]
    ground_pts = [_iso(x, y, ele_min) for x, y in xy]

    # ── Fit into the canvas ──────────────────────────────────────────────────
    all_pts = elev_pts + ground_pts
    sx_vals = [p[0] for p in all_pts]
    sy_vals = [p[1] for p in all_pts]
    sx_min, sx_max = min(sx_vals), max(sx_vals)
    sy_min, sy_max = min(sy_vals), max(sy_vals)

    sx_span = sx_max - sx_min
    sy_span = sy_max - sy_min

    draw_w = width - 2 * padding
    draw_h = height - 2 * padding

    if sx_span == 0 and sy_span == 0:
        scale = 1.0
    elif sx_span == 0:
        scale = draw_h / sy_span
    elif sy_span == 0:
        scale = draw_w / sx_span
    else:
        scale = min(draw_w / sx_span, draw_h / sy_span)

    scaled_w = sx_span * scale
    scaled_h = sy_span * scale
    off_x = padding + (draw_w - scaled_w) / 2 - sx_min * scale
    off_y = padding + (draw_h - scaled_h) / 2 - sy_min * scale

    def _to_svg(sx: float, sy: float) -> Tuple[float, float]:
        return sx * scale + off_x, sy * scale + off_y

    elev_svg = [_to_svg(*p) for p in elev_pts]
    ground_svg = [_to_svg(*p) for p in ground_pts]

    lines: List[str] = []
    sw = _fmt(stroke_width)

    # 1. Dashed ground-level shadow.
    path_ground = _build_path(ground_svg)
    if path_ground:
        dash = _fmt(stroke_width * 3)
        gap = _fmt(stroke_width * 2)
        thin = _fmt(stroke_width * 0.5)
        lines.append(
            f'  <path d="{path_ground}" fill="none" stroke="black" '
            f'stroke-width="{thin}" stroke-linecap="round" stroke-linejoin="round" '
            f'stroke-dasharray="{dash} {gap}"/>'
        )

    # 2. Vertical rib lines at ~every 10 % of the points.
    n = len(xy)
    rib_step = max(1, n // 10)
    rib_indices: Set[int] = set(range(0, n, rib_step))
    rib_indices.add(n - 1)  # always include the last point
    thin_sw = _fmt(stroke_width * 0.5)
    for i in sorted(rib_indices):
        ex, ey = elev_svg[i]
        gx, gy = ground_svg[i]
        lines.append(
            f'  <line x1="{ex:.3f}" y1="{ey:.3f}" '
            f'x2="{gx:.3f}" y2="{gy:.3f}" '
            f'stroke="black" stroke-width="{thin_sw}"/>'
        )

    # 3. Elevated track path.
    path_elev = _build_path(elev_svg)
    if path_elev:
        lines.append(
            f'  <path d="{path_elev}" fill="none" stroke="black" '
            f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"/>'
        )

    return lines


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
    view_3d: bool = False,
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
            elevation-profile chart (only when *view_3d* is ``False``).
        view_3d: When ``True`` the track is rendered as an isometric 3-D view
            that combines geographic and elevation data.  The flat map and the
            separate elevation-profile panel are replaced by the 3-D
            representation.
    """
    # ── Layout ──────────────────────────────────────────────────────────────
    # Canvas is split top-to-bottom:
    #   [text zone]  [track map]  [separator]  [elevation profile]
    #
    # When elevation_profile is disabled (elevations=None), the profile zone
    # and separator are zero-height, so the layout is unchanged vs. the
    # original behaviour.
    #
    # When view_3d=True the isometric 3-D renderer takes the full track zone
    # (the separate elevation-profile panel is omitted).

    has_text = bool(name or stats)

    # 3-D mode uses the full canvas for the track (no profile panel).
    if view_3d:
        has_elev_panel = False
        profile_zone_h = 0.0
        sep_h = 0.0
    else:
        has_elev_panel = elevations is not None and any(e is not None for e in elevations)
        profile_zone_h = height * _PROFILE_RATIO if has_elev_panel else 0.0
        sep_h = stroke_width * 3 if has_elev_panel else 0.0

    # Height available for text + track map.
    available_h = height - profile_zone_h - sep_h

    text_zone_h = available_h * 0.15 if has_text else 0.0
    track_offset_y = text_zone_h
    track_height = available_h - text_zone_h

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

    if view_3d:
        # ── 3-D isometric view ───────────────────────────────────────────────
        # Build a clipping viewport shifted down by the text zone so the 3-D
        # drawing does not overlap the text labels.
        elev_list: List[Optional[float]] = elevations if elevations is not None else []
        track_3d_lines = _render_3d_track(
            xy=xy,
            elevations=elev_list,
            width=width,
            height=track_height,
            padding=padding,
            stroke_width=stroke_width,
        )
        # Wrap in a <g> that shifts the 3-D content below the text zone.
        if track_3d_lines:
            lines.append(f'  <g transform="translate(0,{track_offset_y:.3f})">')
            lines.extend(track_3d_lines)
            lines.append("  </g>")
    else:
        # ── Flat map view ────────────────────────────────────────────────────
        normalised = _normalize(xy, width, track_height, padding)
        shifted = [(x, y + track_offset_y) for x, y in normalised]
        path_d = _build_path(shifted)

        if path_d:
            lines.append(
                f'  <path d="{path_d}" '
                f'fill="none" stroke="black" stroke-width="{_fmt(stroke_width)}" '
                f'stroke-linecap="round" stroke-linejoin="round"/>'
            )

        # ── Elevation profile panel ──────────────────────────────────────────
        if has_elev_panel:
            assert elevations is not None  # narrowing for type checkers
            sep_y = available_h + sep_h / 2
            lines.append(
                f'  <line x1="{_fmt(padding)}" y1="{sep_y:.3f}" '
                f'x2="{_fmt(width - padding)}" y2="{sep_y:.3f}" '
                f'stroke="black" stroke-width="{_fmt(stroke_width * 0.5)}"/>'
            )
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
