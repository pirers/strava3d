"""SVG rendering helpers for GPX tracks."""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Set, Tuple

# Fraction of canvas height reserved for the elevation profile panel.
_PROFILE_RATIO = 0.28

# Vertical scale used in the isometric 3D projection.
# A value of 0.5 means the elevation axis spans half the horizontal extent.
_ISO_Z_SCALE = 0.5

# Maximum gradient (%) used as the upper bound for colour scaling.
# Anything steeper maps to the darkest shade.
_MAX_GRADE_PCT = 15.0


def _gradient_color(gradient_pct: float) -> str:
    """Return an SVG colour string for a gradient percentage.

    * Positive values (uphill) → red hues (HSL hue 0°).
    * Negative values (downhill) → green hues (HSL hue 120°).
    * Flat sections → neutral mid-grey.
    * The steeper the gradient the darker the colour (lower lightness).

    Lightness varies linearly from 78 % (flat) down to 25 % (≥ ±_MAX_GRADE_PCT).
    """
    clamped = max(-_MAX_GRADE_PCT, min(_MAX_GRADE_PCT, gradient_pct))
    t = abs(clamped) / _MAX_GRADE_PCT  # 0 = flat, 1 = max grade
    lightness = int(78 - t * 53)       # 78 % → 25 %
    if clamped > 0:
        return f"hsl(0,85%,{lightness}%)"
    if clamped < 0:
        return f"hsl(120,70%,{lightness}%)"
    return "hsl(0,0%,65%)"  # flat → mid-grey


def _compute_segment_colors(
    xy: List[Tuple[float, float]],
    eles: List[float],
) -> List[str]:
    """Return one colour per consecutive point-pair using 1 km gradient buckets.

    The gradient for each 1 km window (elevation rise ÷ horizontal distance × 100)
    is computed and mapped to a colour via :func:`_gradient_color`.

    Returns a list of length ``len(xy) - 1``.
    """
    n = len(xy)
    if n < 2:
        return []

    # Cumulative horizontal distance between consecutive projected points (metres).
    cum: List[float] = [0.0]
    for i in range(1, n):
        dx = xy[i][0] - xy[i - 1][0]
        dy = xy[i][1] - xy[i - 1][1]
        cum.append(cum[-1] + math.sqrt(dx * dx + dy * dy))

    total = cum[-1]
    if total == 0.0:
        return [_gradient_color(0.0)] * (n - 1)

    _KM = 1000.0
    n_buckets = int(total / _KM) + 2

    # Compute the average gradient (%) for each 1 km bucket.
    bucket_grad: List[float] = []
    for b in range(n_buckets):
        lo, hi = b * _KM, (b + 1) * _KM
        pts = [(cum[i], eles[i]) for i in range(n) if lo <= cum[i] < hi]
        if len(pts) >= 2:
            d_dist = pts[-1][0] - pts[0][0]
            d_ele = pts[-1][1] - pts[0][1]
            bucket_grad.append((d_ele / d_dist * 100.0) if d_dist > 0 else 0.0)
        else:
            bucket_grad.append(0.0)

    # Assign a colour to each segment based on its midpoint's 1 km bucket.
    colors: List[str] = []
    for i in range(n - 1):
        mid = (cum[i] + cum[i + 1]) / 2.0
        b = min(int(mid / _KM), n_buckets - 1)
        colors.append(_gradient_color(bucket_grad[b]))
    return colors


def _compute_3d_points(
    xy: List[Tuple[float, float]],
    eles: List[float],
) -> Tuple[List[Tuple[float, float, float]], List[str]]:
    """Normalise 3-D coordinates and compute per-segment gradient colours.

    Returns:
        pts3d: list of *(nx, ny, nz)* where each component is in ``[0, 1]``.
            *nx* and *ny* are normalised by the same horizontal span to
            preserve the geographic aspect ratio; *nz* is normalised
            independently by the elevation span.
        seg_colors: list of CSS colour strings of length ``len(xy) - 1``.
    """
    xs = [p[0] for p in xy]
    ys = [p[1] for p in xy]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    ele_min, ele_max = min(eles), max(eles)

    horiz_span = max(x_max - x_min, y_max - y_min, 1.0)
    ele_span = max(ele_max - ele_min, 1.0)

    pts3d: List[Tuple[float, float, float]] = [
        (
            (x - x_min) / horiz_span,
            (y - y_min) / horiz_span,
            (e - ele_min) / ele_span,
        )
        for (x, y), e in zip(xy, eles)
    ]
    seg_colors = _compute_segment_colors(xy, eles)
    return pts3d, seg_colors


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
    """Render a 3-D isometric view of the track with gradient colour coding.

    The projection used is the standard isometric cabinet projection::

        screen_x = (norm_x - norm_y) * cos(30°)
        screen_y = (norm_x + norm_y) * sin(30°) − norm_z * _ISO_Z_SCALE

    where *norm_x* and *norm_y* are the normalised geographic coordinates in
    ``[0, 1]`` and *norm_z* is the normalised elevation also in ``[0, 1]``.

    The track is split into **1 km gradient buckets** and each bucket is
    drawn in a colour that encodes its average gradient:

    * **Red** shades for uphill segments (darker = steeper).
    * **Green** shades for downhill segments (darker = steeper).

    The function draws (back-to-front paint order):

    1. Dashed ground-level track shadow (group id ``iso3d-ground``).
    2. Vertical "rib" lines at ~every 10 % of the track (group id
       ``iso3d-ribs``), connecting the elevated point to the ground plane.
    3. The gradient-coloured elevated track (group id ``iso3d-track``).

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
    pts3d, seg_colors = _compute_3d_points(xy, eles)

    # ── Isometric projection ─────────────────────────────────────────────────
    cos30 = math.cos(math.radians(30))
    sin30 = math.sin(math.radians(30))

    def _iso(nx: float, ny: float, nz: float) -> Tuple[float, float]:
        """Apply the standard isometric projection to normalised coordinates."""
        nz_scaled = nz * _ISO_Z_SCALE
        sx = (nx - ny) * cos30
        sy = (nx + ny) * sin30 - nz_scaled
        return sx, sy

    elev_pts = [_iso(nx, ny, nz) for nx, ny, nz in pts3d]
    ground_pts = [_iso(nx, ny, 0.0) for nx, ny, _ in pts3d]

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

    # 1. Dashed ground-level shadow.
    lines.append('  <g id="iso3d-ground">')
    path_ground = _build_path(ground_svg)
    if path_ground:
        dash = _fmt(stroke_width * 3)
        gap = _fmt(stroke_width * 2)
        thin = _fmt(stroke_width * 0.5)
        lines.append(
            f'    <path d="{path_ground}" fill="none" stroke="#555" '
            f'stroke-width="{thin}" stroke-linecap="round" stroke-linejoin="round" '
            f'stroke-dasharray="{dash} {gap}"/>'
        )
    lines.append("  </g>")

    # 2. Vertical rib lines at ~every 10 % of the points.
    lines.append('  <g id="iso3d-ribs">')
    n = len(xy)
    rib_step = max(1, n // 10)
    rib_indices: Set[int] = set(range(0, n, rib_step))
    rib_indices.add(n - 1)  # always include the last point
    thin_sw = _fmt(stroke_width * 0.5)
    for i in sorted(rib_indices):
        ex, ey = elev_svg[i]
        gx, gy = ground_svg[i]
        lines.append(
            f'    <line x1="{ex:.3f}" y1="{ey:.3f}" '
            f'x2="{gx:.3f}" y2="{gy:.3f}" '
            f'stroke="#888" stroke-width="{thin_sw}"/>'
        )
    lines.append("  </g>")

    # 3. Gradient-coloured elevated track segments grouped by colour.
    lines.append('  <g id="iso3d-track">')
    sw = _fmt(stroke_width)
    i = 0
    while i < len(elev_svg) - 1:
        color = seg_colors[i] if i < len(seg_colors) else "black"
        seg_pts = [elev_svg[i]]
        j = i
        while j < len(seg_colors) and seg_colors[j] == color:
            seg_pts.append(elev_svg[j + 1])
            j += 1
        path_d = _build_path(seg_pts)
        if path_d:
            lines.append(
                f'    <path d="{path_d}" fill="none" stroke="{color}" '
                f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"/>'
            )
        i = j
    lines.append("  </g>")

    return lines


def _build_3d_script(
    pts3d: List[Tuple[float, float, float]],
    seg_colors: List[str],
    width: float,
    track_height: float,
    padding: float,
    stroke_width: float,
) -> str:
    """Return an SVG ``<script>`` element for interactive 3-D rotation.

    The script embeds the raw normalised 3-D point data and implements
    mouse-driven rotation of the isometric view around all three axes:

    * **Left-drag left/right** → azimuth (rotation around the vertical Z axis).
    * **Left-drag up/down** → elevation tilt (rotation around the X axis).
    * **Right-drag left/right** → twist / roll (rotation around the Y axis).

    The initial view approximates the Python-rendered isometric projection.
    On browsers that block scripts in SVGs (e.g. when used as ``<img>``),
    the static Python-rendered coloured track remains visible as a fallback.

    Args:
        pts3d: Normalised 3-D coordinates ``[(nx, ny, nz), ...]`` (all in
            ``[0, 1]``), as produced by :func:`_compute_3d_points`.
        seg_colors: Per-segment CSS colours (length ``len(pts3d) - 1``).
        width: SVG canvas width (user units) – used for JS canvas sizing.
        track_height: Height of the 3-D track area (user units).
        padding: Inner padding (user units).
        stroke_width: Base stroke width (user units).

    Returns:
        An SVG-compatible ``<script>`` element string.
    """
    pts_json = json.dumps([[round(nx, 5), round(ny, 5), round(nz, 5)] for nx, ny, nz in pts3d])
    colors_json = json.dumps(seg_colors)

    js = f"""(function () {{
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var PTS = {pts_json};
  var COLORS = {colors_json};
  var W = {width}, TH = {track_height}, PAD = {padding};
  var SW = {stroke_width}, ZS = {_ISO_Z_SCALE};

  // Initial view angles (radians) – approximates the Python isometric view.
  var az = Math.PI * 0.75;  // azimuth  (rotation around Z axis)
  var el = Math.PI * 0.25;  // elevation (rotation around X axis)
  var tw = 0.0;              // twist     (rotation around Y axis)

  function project(nx, ny, nz) {{
    var cx = nx - 0.5, cy = ny - 0.5, cz = nz * ZS - ZS * 0.5;
    // Rotate around Z (azimuth)
    var caz = Math.cos(az), saz = Math.sin(az);
    var x1 = cx * caz - cy * saz, y1 = cx * saz + cy * caz, z1 = cz;
    // Rotate around X (elevation)
    var cel = Math.cos(el), sel = Math.sin(el);
    var x2 = x1, y2 = y1 * cel - z1 * sel, z2 = y1 * sel + z1 * cel;
    // Rotate around Y (twist)
    var ctw = Math.cos(tw), stw = Math.sin(tw);
    return [x2 * ctw + z2 * stw, y2];
  }}

  function fitPts(rawPts) {{
    var xs = rawPts.map(function (p) {{ return p[0]; }});
    var ys = rawPts.map(function (p) {{ return p[1]; }});
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    var xSp = (x1 - x0) || 1, ySp = (y1 - y0) || 1;
    var dw = W - 2 * PAD, dh = TH - 2 * PAD;
    var sc = Math.min(dw / xSp, dh / ySp);
    var ox = PAD + (dw - xSp * sc) / 2 - x0 * sc;
    var oy = PAD + (dh - ySp * sc) / 2 - y0 * sc;
    return rawPts.map(function (p) {{ return [p[0] * sc + ox, p[1] * sc + oy]; }});
  }}

  function buildPath(pts) {{
    if (!pts.length) return '';
    var d = 'M ' + pts[0][0].toFixed(2) + ',' + pts[0][1].toFixed(2);
    for (var i = 1; i < pts.length; i++) d += ' L ' + pts[i][0].toFixed(2) + ',' + pts[i][1].toFixed(2);
    return d;
  }}

  function mkEl(tag, attrs) {{
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }}

  function redraw() {{
    var n = PTS.length;
    var ePts = PTS.map(function (p) {{ return project(p[0], p[1], p[2]); }});
    var gPts = PTS.map(function (p) {{ return project(p[0], p[1], 0); }});
    var fitted = fitPts(ePts.concat(gPts));
    var ef = fitted.slice(0, n), gf = fitted.slice(n);

    var wrap = document.getElementById('iso3d-wrap');
    if (!wrap) return;

    // Clear previous dynamic content, preserving static sub-groups by id.
    var dyn = document.getElementById('iso3d-dyn');
    if (dyn) wrap.removeChild(dyn);
    dyn = document.createElementNS(NS, 'g');
    dyn.setAttribute('id', 'iso3d-dyn');

    // Hide static fallback content.
    ['iso3d-ground', 'iso3d-ribs', 'iso3d-track'].forEach(function (id) {{
      var el2 = document.getElementById(id);
      if (el2) el2.setAttribute('display', 'none');
    }});

    // Ground shadow.
    var thin = (SW * 0.5).toFixed(2), dash = (SW * 3).toFixed(2), gap2 = (SW * 2).toFixed(2);
    var gd = buildPath(gf);
    if (gd) dyn.appendChild(mkEl('path', {{
      d: gd, fill: 'none', stroke: '#555',
      'stroke-width': thin, 'stroke-dasharray': dash + ' ' + gap2, 'stroke-linecap': 'round'
    }}));

    // Rib lines.
    var step = Math.max(1, Math.floor(n / 10));
    var thinSW = (SW * 0.5).toFixed(2);
    for (var i = 0; i < n; i += step) {{
      dyn.appendChild(mkEl('line', {{
        x1: ef[i][0].toFixed(2), y1: ef[i][1].toFixed(2),
        x2: gf[i][0].toFixed(2), y2: gf[i][1].toFixed(2),
        stroke: '#888', 'stroke-width': thinSW
      }}));
    }}
    if ((n - 1) % step !== 0) {{
      dyn.appendChild(mkEl('line', {{
        x1: ef[n-1][0].toFixed(2), y1: ef[n-1][1].toFixed(2),
        x2: gf[n-1][0].toFixed(2), y2: gf[n-1][1].toFixed(2),
        stroke: '#888', 'stroke-width': thinSW
      }}));
    }}

    // Gradient-coloured track segments (group consecutive same-colour runs).
    var j = 0;
    while (j < n - 1) {{
      var col = COLORS[j] || 'black';
      var segPts = [ef[j]];
      var k = j;
      while (k < n - 1 && COLORS[k] === col) {{ segPts.push(ef[k + 1]); k++; }}
      var pd = buildPath(segPts);
      if (pd) dyn.appendChild(mkEl('path', {{
        d: pd, fill: 'none', stroke: col,
        'stroke-width': SW.toFixed(2), 'stroke-linecap': 'round', 'stroke-linejoin': 'round'
      }}));
      j = k;
    }}

    wrap.appendChild(dyn);
  }}

  // Mouse interaction.
  var dragging = false, lastX = 0, lastY = 0, btn = 0;
  var hit = document.getElementById('iso3d-hitarea');
  if (!hit) return;

  hit.addEventListener('mousedown', function (e) {{
    dragging = true; btn = e.button; lastX = e.clientX; lastY = e.clientY;
    hit.style.cursor = 'grabbing';
    e.preventDefault();
  }});

  document.addEventListener('mousemove', function (e) {{
    if (!dragging) return;
    var dx = e.clientX - lastX, dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    var sens = 0.005;
    if (btn === 2) {{
      tw += dx * sens;                                        // right-drag → twist
    }} else {{
      az += dx * sens;                                        // left-drag  → azimuth
      el = Math.max(-Math.PI / 2 + 0.01,
                    Math.min(Math.PI / 2 - 0.01, el + dy * sens)); // elevation clamp
    }}
    redraw();
  }});

  document.addEventListener('mouseup', function () {{
    dragging = false;
    if (hit) hit.style.cursor = 'grab';
  }});

  hit.addEventListener('contextmenu', function (e) {{ e.preventDefault(); }});

  // Legend hint.
  var svg = hit.closest ? hit.closest('svg') : hit.parentNode;
  if (svg) {{
    var hint = document.createElementNS(NS, 'text');
    hint.setAttribute('x', '4');
    hint.setAttribute('y', (TH - 4).toFixed(1));
    hint.setAttribute('font-size', '9');
    hint.setAttribute('font-family', 'sans-serif');
    hint.setAttribute('fill', '#94a3b8');
    hint.textContent = 'drag: rotate \u2502 right-drag: roll';
    var wrap2 = document.getElementById('iso3d-wrap');
    if (wrap2) wrap2.appendChild(hint);
  }}

  redraw();
}})();"""

    return (
        "  <script type=\"text/javascript\"><![CDATA[\n"
        + js
        + "\n  ]]></script>"
    )


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
        eles_filled = _fill_elevations(elev_list, len(xy))

        track_3d_lines = _render_3d_track(
            xy=xy,
            elevations=elev_list,
            width=width,
            height=track_height,
            padding=padding,
            stroke_width=stroke_width,
        )
        # Wrap in a <g id="iso3d-wrap"> that shifts the 3-D content below the
        # text zone.  The id is used by the interactive JavaScript to update
        # the projection dynamically.
        if track_3d_lines:
            lines.append(
                f'  <g id="iso3d-wrap" transform="translate(0,{track_offset_y:.3f})">'
            )
            lines.extend(track_3d_lines)
            lines.append("  </g>")

        # Transparent hit-area rectangle to capture mouse events for rotation.
        lines.append(
            f'  <rect id="iso3d-hitarea" '
            f'x="0" y="{track_offset_y:.3f}" '
            f'width="{_fmt(width)}" height="{_fmt(track_height)}" '
            f'fill="transparent" style="cursor:grab;"/>'
        )

        # Embed the interactive JS script (only when track data is available).
        if track_3d_lines:
            pts3d, seg_colors = _compute_3d_points(xy, eles_filled)
            lines.append(
                _build_3d_script(
                    pts3d=pts3d,
                    seg_colors=seg_colors,
                    width=width,
                    track_height=track_height,
                    padding=padding,
                    stroke_width=stroke_width,
                )
            )
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
