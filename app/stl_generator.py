"""Generate binary STL files for a 3-D printable terrain model.

Two STL bodies are produced so that a dual-colour (or filament-swap) print can
render the GPS track in a contrasting colour:

* **Terrain STL** – the terrain surface + solid base plate.
* **Track STL** – a flat ribbon that follows the GPS track, raised slightly
  above the terrain surface.  Print this in a second colour.

The base plate carries embossed route metadata (name, distance, elevation gain
and average gradient) along its bottom edge using a compact 5×7 pixel font.

Coordinate convention (all in mm, right-hand rule):
  X – west → east
  Y – south → north
  Z – down → up  (base plate bottom at z = 0)
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .dem_fetcher import DemGrid
from .gpx_parser import TrackData, project_points

# ---------------------------------------------------------------------------
# Compact 5×7 pixel font (printable ASCII 32–126)
# Each character is 5 columns of 7-bit masks (bit 6 = top row).
# ---------------------------------------------------------------------------
_FONT_5X7: dict[str, List[int]] = {
    " ": [0x00, 0x00, 0x00, 0x00, 0x00],
    "!": [0x00, 0x5F, 0x00, 0x00, 0x00],
    '"': [0x07, 0x00, 0x07, 0x00, 0x00],
    "#": [0x14, 0x7F, 0x14, 0x7F, 0x14],
    "$": [0x24, 0x2A, 0x7F, 0x2A, 0x12],
    "%": [0x23, 0x13, 0x08, 0x64, 0x62],
    "&": [0x36, 0x49, 0x55, 0x22, 0x50],
    "'": [0x00, 0x05, 0x03, 0x00, 0x00],
    "(": [0x00, 0x1C, 0x22, 0x41, 0x00],
    ")": [0x00, 0x41, 0x22, 0x1C, 0x00],
    "*": [0x14, 0x08, 0x3E, 0x08, 0x14],
    "+": [0x08, 0x08, 0x3E, 0x08, 0x08],
    ",": [0x00, 0x50, 0x30, 0x00, 0x00],
    "-": [0x08, 0x08, 0x08, 0x08, 0x08],
    ".": [0x00, 0x60, 0x60, 0x00, 0x00],
    "/": [0x20, 0x10, 0x08, 0x04, 0x02],
    "0": [0x3E, 0x51, 0x49, 0x45, 0x3E],
    "1": [0x00, 0x42, 0x7F, 0x40, 0x00],
    "2": [0x42, 0x61, 0x51, 0x49, 0x46],
    "3": [0x21, 0x41, 0x45, 0x4B, 0x31],
    "4": [0x18, 0x14, 0x12, 0x7F, 0x10],
    "5": [0x27, 0x45, 0x45, 0x45, 0x39],
    "6": [0x3C, 0x4A, 0x49, 0x49, 0x30],
    "7": [0x01, 0x71, 0x09, 0x05, 0x03],
    "8": [0x36, 0x49, 0x49, 0x49, 0x36],
    "9": [0x06, 0x49, 0x49, 0x29, 0x1E],
    ":": [0x00, 0x36, 0x36, 0x00, 0x00],
    ";": [0x00, 0x56, 0x36, 0x00, 0x00],
    "<": [0x08, 0x14, 0x22, 0x41, 0x00],
    "=": [0x14, 0x14, 0x14, 0x14, 0x14],
    ">": [0x00, 0x41, 0x22, 0x14, 0x08],
    "?": [0x02, 0x01, 0x51, 0x09, 0x06],
    "@": [0x32, 0x49, 0x79, 0x41, 0x3E],
    "A": [0x7E, 0x11, 0x11, 0x11, 0x7E],
    "B": [0x7F, 0x49, 0x49, 0x49, 0x36],
    "C": [0x3E, 0x41, 0x41, 0x41, 0x22],
    "D": [0x7F, 0x41, 0x41, 0x22, 0x1C],
    "E": [0x7F, 0x49, 0x49, 0x49, 0x41],
    "F": [0x7F, 0x09, 0x09, 0x09, 0x01],
    "G": [0x3E, 0x41, 0x49, 0x49, 0x7A],
    "H": [0x7F, 0x08, 0x08, 0x08, 0x7F],
    "I": [0x00, 0x41, 0x7F, 0x41, 0x00],
    "J": [0x20, 0x40, 0x41, 0x3F, 0x01],
    "K": [0x7F, 0x08, 0x14, 0x22, 0x41],
    "L": [0x7F, 0x40, 0x40, 0x40, 0x40],
    "M": [0x7F, 0x02, 0x0C, 0x02, 0x7F],
    "N": [0x7F, 0x04, 0x08, 0x10, 0x7F],
    "O": [0x3E, 0x41, 0x41, 0x41, 0x3E],
    "P": [0x7F, 0x09, 0x09, 0x09, 0x06],
    "Q": [0x3E, 0x41, 0x51, 0x21, 0x5E],
    "R": [0x7F, 0x09, 0x19, 0x29, 0x46],
    "S": [0x46, 0x49, 0x49, 0x49, 0x31],
    "T": [0x01, 0x01, 0x7F, 0x01, 0x01],
    "U": [0x3F, 0x40, 0x40, 0x40, 0x3F],
    "V": [0x1F, 0x20, 0x40, 0x20, 0x1F],
    "W": [0x3F, 0x40, 0x38, 0x40, 0x3F],
    "X": [0x63, 0x14, 0x08, 0x14, 0x63],
    "Y": [0x07, 0x08, 0x70, 0x08, 0x07],
    "Z": [0x61, 0x51, 0x49, 0x45, 0x43],
    "[": [0x00, 0x7F, 0x41, 0x41, 0x00],
    "\\": [0x02, 0x04, 0x08, 0x10, 0x20],
    "]": [0x00, 0x41, 0x41, 0x7F, 0x00],
    "^": [0x04, 0x02, 0x01, 0x02, 0x04],
    "_": [0x40, 0x40, 0x40, 0x40, 0x40],
    "`": [0x00, 0x01, 0x02, 0x04, 0x00],
    "a": [0x20, 0x54, 0x54, 0x54, 0x78],
    "b": [0x7F, 0x48, 0x44, 0x44, 0x38],
    "c": [0x38, 0x44, 0x44, 0x44, 0x20],
    "d": [0x38, 0x44, 0x44, 0x48, 0x7F],
    "e": [0x38, 0x54, 0x54, 0x54, 0x18],
    "f": [0x08, 0x7E, 0x09, 0x01, 0x02],
    "g": [0x0C, 0x52, 0x52, 0x52, 0x3E],
    "h": [0x7F, 0x08, 0x04, 0x04, 0x78],
    "i": [0x00, 0x44, 0x7D, 0x40, 0x00],
    "j": [0x20, 0x40, 0x44, 0x3D, 0x00],
    "k": [0x7F, 0x10, 0x28, 0x44, 0x00],
    "l": [0x00, 0x41, 0x7F, 0x40, 0x00],
    "m": [0x7C, 0x04, 0x18, 0x04, 0x78],
    "n": [0x7C, 0x08, 0x04, 0x04, 0x78],
    "o": [0x38, 0x44, 0x44, 0x44, 0x38],
    "p": [0x7C, 0x14, 0x14, 0x14, 0x08],
    "q": [0x08, 0x14, 0x14, 0x18, 0x7C],
    "r": [0x7C, 0x08, 0x04, 0x04, 0x08],
    "s": [0x48, 0x54, 0x54, 0x54, 0x20],
    "t": [0x04, 0x3F, 0x44, 0x40, 0x20],
    "u": [0x3C, 0x40, 0x40, 0x20, 0x7C],
    "v": [0x1C, 0x20, 0x40, 0x20, 0x1C],
    "w": [0x3C, 0x40, 0x30, 0x40, 0x3C],
    "x": [0x44, 0x28, 0x10, 0x28, 0x44],
    "y": [0x0C, 0x50, 0x50, 0x50, 0x3C],
    "z": [0x44, 0x64, 0x54, 0x4C, 0x44],
    "{": [0x00, 0x08, 0x36, 0x41, 0x00],
    "|": [0x00, 0x00, 0x7F, 0x00, 0x00],
    "}": [0x00, 0x41, 0x36, 0x08, 0x00],
    "~": [0x08, 0x04, 0x08, 0x10, 0x08],
    "↑": [0x08, 0x04, 0x7F, 0x04, 0x08],  # unicode up-arrow approximation
    "°": [0x06, 0x09, 0x09, 0x06, 0x00],
    "%": [0x23, 0x13, 0x08, 0x64, 0x62],
}


# ---------------------------------------------------------------------------
# Low-level binary STL helpers
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]
Triangle = Tuple[Vec3, Vec3, Vec3]

_HEADER = b"strava3d terrain model" + b" " * (80 - 22)


def _triangle_normal(v0: Vec3, v1: Vec3, v2: Vec3) -> Vec3:
    ax, ay, az = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
    bx, by, bz = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def _build_stl(triangles: List[Triangle]) -> bytes:
    """Return a binary STL byte string for *triangles*."""
    buf = bytearray(_HEADER)
    buf += struct.pack("<I", len(triangles))
    for v0, v1, v2 in triangles:
        nx, ny, nz = _triangle_normal(v0, v1, v2)
        buf += struct.pack(
            "<fff fff fff fff H",
            nx, ny, nz,
            *v0, *v1, *v2,
            0,
        )
    return bytes(buf)


def _quad(a: Vec3, b: Vec3, c: Vec3, d: Vec3) -> List[Triangle]:
    """Split a quad (a, b, c, d in CCW order viewed from outside) into 2 triangles."""
    return [(a, b, c), (a, c, d)]


# ---------------------------------------------------------------------------
# Pixel-font geometry helpers
# ---------------------------------------------------------------------------
_PX = 0.6   # pixel cube side length (mm)
_PX_H = 0.4  # raised height of each "pixel" cube (mm)
_CHAR_W = 5 * _PX + _PX  # character width including gap
_CHAR_H = 7 * _PX + _PX  # character height including gap


def _char_triangles(ch: str, x0: float, y0: float, z_base: float) -> List[Triangle]:
    """Return STL triangles for a single embossed character at position (x0, y0)."""
    cols = _FONT_5X7.get(ch.upper() if ch.upper() in _FONT_5X7 else ch, _FONT_5X7.get(" ", [0]*5))
    tris: List[Triangle] = []
    for col_idx, col_bits in enumerate(cols):
        for row_idx in range(7):
            if col_bits & (1 << (6 - row_idx)):
                px = x0 + col_idx * (_PX + 0.1)
                py = y0 + row_idx * (_PX + 0.1)
                z0 = z_base
                z1 = z_base + _PX_H
                # Top face
                tris += _quad(
                    (px, py, z1), (px + _PX, py, z1),
                    (px + _PX, py + _PX, z1), (px, py + _PX, z1),
                )
                # Front face (y-)
                tris += _quad(
                    (px, py, z0), (px + _PX, py, z0),
                    (px + _PX, py, z1), (px, py, z1),
                )
                # Back face (y+)
                tris += _quad(
                    (px + _PX, py + _PX, z0), (px, py + _PX, z0),
                    (px, py + _PX, z1), (px + _PX, py + _PX, z1),
                )
                # Left face (x-)
                tris += _quad(
                    (px, py + _PX, z0), (px, py, z0),
                    (px, py, z1), (px, py + _PX, z1),
                )
                # Right face (x+)
                tris += _quad(
                    (px + _PX, py, z0), (px + _PX, py + _PX, z0),
                    (px + _PX, py + _PX, z1), (px + _PX, py, z1),
                )
    return tris


def _text_triangles(text: str, x0: float, y0: float, z_base: float) -> List[Triangle]:
    """Return STL triangles for a string of embossed characters."""
    tris: List[Triangle] = []
    cx = x0
    for ch in text:
        tris += _char_triangles(ch, cx, y0, z_base)
        cx += _CHAR_W
    return tris


def _text_width(text: str) -> float:
    return len(text) * _CHAR_W


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class TerrainModelConfig:
    """Parameters controlling the dimensions of the generated terrain model."""

    model_size_mm: float = 150.0
    """Length of the longest side of the terrain block (mm)."""

    base_thickness_mm: float = 3.0
    """Thickness of the solid base plate below the terrain (mm)."""

    terrain_height_mm: float = 20.0
    """Maximum terrain relief height above the base plate (mm).

    Elevations are linearly scaled so that the highest point in the DEM grid
    equals this value.
    """

    track_raised_mm: float = 0.8
    """How much the track ribbon is raised above the terrain surface (mm).

    Keep this at ≥ 1–2 layer heights so the slicer can produce a clean
    filament-swap layer.
    """

    track_width_mm: float = 2.0
    """Width of the track ribbon (mm)."""

    label_height_mm: float = 10.0
    """Height of the text label band at the front of the base plate (mm)."""


# ---------------------------------------------------------------------------
# Terrain STL builder
# ---------------------------------------------------------------------------

def _map_elevation(ele: float, ele_min: float, ele_range: float, config: TerrainModelConfig) -> float:
    """Scale a DEM elevation to a model z-coordinate (above base plate top face)."""
    if ele_range < 1e-6:
        return 0.0
    return (ele - ele_min) / ele_range * config.terrain_height_mm


def _build_terrain_triangles(
    dem: DemGrid,
    config: TerrainModelConfig,
    x_size: float,
    y_size: float,
    z_terrain_base: float,
    ele_min: float,
    ele_range: float,
) -> List[Triangle]:
    """Return triangles for the terrain surface and its side/bottom walls."""
    nr, nc = dem.n_rows, dem.n_cols
    tris: List[Triangle] = []

    def _pt(r: int, c: int) -> Vec3:
        x = c / (nc - 1) * x_size
        y = (1 - r / (nr - 1)) * y_size          # row 0 = north = high y
        z = z_terrain_base + _map_elevation(dem.elevations[r][c], ele_min, ele_range, config)
        return (x, y, z)

    # Surface quads
    for r in range(nr - 1):
        for c in range(nc - 1):
            a = _pt(r, c)
            b = _pt(r, c + 1)
            c_ = _pt(r + 1, c + 1)
            d_ = _pt(r + 1, c)
            tris += _quad(a, b, c_, d_)

    z_bottom = 0.0

    # South wall (row = nr-1, from west to east)
    for c in range(nc - 1):
        top_l = _pt(nr - 1, c)
        top_r = _pt(nr - 1, c + 1)
        bot_l = (top_l[0], top_l[1], z_bottom)
        bot_r = (top_r[0], top_r[1], z_bottom)
        tris += _quad(bot_l, bot_r, top_r, top_l)

    # North wall (row = 0, from east to west)
    for c in range(nc - 1):
        top_l = _pt(0, c + 1)
        top_r = _pt(0, c)
        bot_l = (top_l[0], top_l[1], z_bottom)
        bot_r = (top_r[0], top_r[1], z_bottom)
        tris += _quad(bot_l, bot_r, top_r, top_l)

    # West wall (col = 0, from north to south)
    for r in range(nr - 1):
        top_l = _pt(r + 1, 0)
        top_r = _pt(r, 0)
        bot_l = (top_l[0], top_l[1], z_bottom)
        bot_r = (top_r[0], top_r[1], z_bottom)
        tris += _quad(bot_l, bot_r, top_r, top_l)

    # East wall (col = nc-1, from south to north)
    for r in range(nr - 1):
        top_l = _pt(r, nc - 1)
        top_r = _pt(r + 1, nc - 1)
        bot_l = (top_l[0], top_l[1], z_bottom)
        bot_r = (top_r[0], top_r[1], z_bottom)
        tris += _quad(bot_l, bot_r, top_r, top_l)

    # Bottom face
    tris += _quad(
        (0.0, 0.0, z_bottom),
        (x_size, 0.0, z_bottom),
        (x_size, y_size, z_bottom),
        (0.0, y_size, z_bottom),
    )

    return tris


# ---------------------------------------------------------------------------
# Track ribbon STL builder
# ---------------------------------------------------------------------------

def _perp2d(dx: float, dy: float, width: float) -> Tuple[float, float]:
    """Unit perpendicular of (dx, dy) scaled to *width/2*."""
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-9:
        return (0.0, width / 2)
    return (-dy / length * width / 2, dx / length * width / 2)


def _build_track_triangles(
    xy_norm: List[Tuple[float, float]],
    dem: DemGrid,
    config: TerrainModelConfig,
    x_size: float,
    y_size: float,
    z_terrain_base: float,
    ele_min: float,
    ele_range: float,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
) -> List[Triangle]:
    """Return triangles for a flat ribbon following the GPS track.

    The ribbon is raised *track_raised_mm* above the terrain surface at each
    GPS point so that it prints on top of the terrain with a filament swap.
    """
    tris: List[Triangle] = []
    n = len(xy_norm)
    if n < 2:
        return tris

    xy_m_min = (min(x for x, _ in xy_norm), min(y for _, y in xy_norm))
    xy_m_max = (max(x for x, _ in xy_norm), max(y for _, y in xy_norm))
    span_x = xy_m_max[0] - xy_m_min[0]
    span_y = xy_m_max[1] - xy_m_min[1]

    def _to_model(xi: float, yi: float) -> Tuple[float, float]:
        """Convert projected metres to model mm."""
        if span_x > 1e-6:
            mx = (xi - xy_m_min[0]) / span_x * x_size
        else:
            mx = x_size / 2
        if span_y > 1e-6:
            my = (yi - xy_m_min[1]) / span_y * y_size
        else:
            my = y_size / 2
        return (mx, my)

    def _lat_lon_at(xi: float, yi: float) -> Tuple[float, float]:
        """Approximate lat/lon from projected (xi, yi) in metres."""
        if span_x > 1e-6:
            t_x = (xi - xy_m_min[0]) / span_x
        else:
            t_x = 0.5
        if span_y > 1e-6:
            t_y = (yi - xy_m_min[1]) / span_y
        else:
            t_y = 0.5
        lat = lat_min + t_y * (lat_max - lat_min)
        lon = lon_min + t_x * (lon_max - lon_min)
        return (lat, lon)

    def _z_at(xi: float, yi: float) -> float:
        lat, lon = _lat_lon_at(xi, yi)
        terrain_ele = dem.sample(lat, lon)
        return z_terrain_base + _map_elevation(terrain_ele, ele_min, ele_range, config) + config.track_raised_mm

    half_w = config.track_width_mm / 2.0

    for i in range(n - 1):
        xi0, yi0 = xy_norm[i]
        xi1, yi1 = xy_norm[i + 1]
        mx0, my0 = _to_model(xi0, yi0)
        mx1, my1 = _to_model(xi1, yi1)

        dx, dy = mx1 - mx0, my1 - my0
        px, py = _perp2d(dx, dy, config.track_width_mm)

        z0 = _z_at(xi0, yi0)
        z1 = _z_at(xi1, yi1)
        z_bottom = 0.0

        # Four corners of ribbon segment top face
        tl = (mx0 - px, my0 - py, z0)
        tr = (mx0 + px, my0 + py, z0)
        bl = (mx1 - px, my1 - py, z1)
        br = (mx1 + px, my1 + py, z1)

        # Top face of ribbon
        tris += _quad(tl, tr, br, bl)

        # Left edge wall (going down to z=0 so it forms a solid)
        tris += _quad(
            (tl[0], tl[1], z_bottom), (bl[0], bl[1], z_bottom),
            bl, tl,
        )
        # Right edge wall
        tris += _quad(
            (tr[0], tr[1], z_bottom), (tr[0], tr[1], z0),
            (br[0], br[1], z1), (br[0], br[1], z_bottom),
        )
        # Front cap (i == 0) and back cap (i == n-2)
        if i == 0:
            tris += _quad(
                (tr[0], tr[1], z_bottom), (tl[0], tl[1], z_bottom),
                tl, tr,
            )
        if i == n - 2:
            tris += _quad(
                (bl[0], bl[1], z_bottom), (br[0], br[1], z_bottom),
                br, bl,
            )
        # Bottom face of ribbon segment
        tris += _quad(
            (tl[0], tl[1], z_bottom), (tr[0], tr[1], z_bottom),
            (br[0], br[1], z_bottom), (bl[0], bl[1], z_bottom),
        )

    return tris


# ---------------------------------------------------------------------------
# Label band STL builder
# ---------------------------------------------------------------------------

def _build_label_triangles(
    lines: List[str],
    x_size: float,
    y_size: float,
    z_base_top: float,
    config: TerrainModelConfig,
) -> List[Triangle]:
    """Return STL triangles for the text label block at the south side.

    The label is a rectangular slab in front of (y < 0) the terrain block,
    with the route metadata embossed on its top face.
    """
    tris: List[Triangle] = []
    lh = config.label_height_mm
    z0 = 0.0
    z1 = z_base_top  # same height as base plate top

    # Label slab (south of the terrain block: y in [-lh, 0])
    # Bottom face
    tris += _quad(
        (0.0, -lh, z0), (x_size, -lh, z0),
        (x_size, 0.0, z0), (0.0, 0.0, z0),
    )
    # Top face
    tris += _quad(
        (0.0, 0.0, z1), (x_size, 0.0, z1),
        (x_size, -lh, z1), (0.0, -lh, z1),
    )
    # South wall
    tris += _quad(
        (0.0, -lh, z0), (0.0, -lh, z1),
        (x_size, -lh, z1), (x_size, -lh, z0),
    )
    # North wall (y = 0)
    tris += _quad(
        (x_size, 0.0, z0), (x_size, 0.0, z1),
        (0.0, 0.0, z1), (0.0, 0.0, z0),
    )
    # West wall
    tris += _quad(
        (0.0, 0.0, z0), (0.0, 0.0, z1),
        (0.0, -lh, z1), (0.0, -lh, z0),
    )
    # East wall
    tris += _quad(
        (x_size, -lh, z0), (x_size, -lh, z1),
        (x_size, 0.0, z1), (x_size, 0.0, z0),
    )

    # Embossed text lines on top face
    total_text_h = len(lines) * _CHAR_H
    margin_y = max(1.0, (lh - total_text_h) / 2)
    for idx, line in enumerate(lines):
        tw = _text_width(line)
        tx = max(1.0, (x_size - tw) / 2)
        # y counts from south (−lh) going north; invert for STL (larger y = more north)
        ty = -lh + margin_y + (len(lines) - 1 - idx) * _CHAR_H
        tris += _text_triangles(line, tx, ty, z1)

    return tris


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_terrain_stls(
    track_data: TrackData,
    dem: DemGrid,
    config: Optional[TerrainModelConfig] = None,
) -> Tuple[bytes, bytes]:
    """Generate two binary STL byte strings from a GPS track and DEM grid.

    Returns:
        ``(terrain_stl, track_stl)`` where

        * *terrain_stl* is the solid terrain + base plate body.
        * *track_stl* is the track ribbon (print in a contrasting colour).

    The two bodies share the same coordinate origin so they can be imported
    into a slicer as a multi-material assembly without alignment.
    """
    if config is None:
        config = TerrainModelConfig()

    # ── DEM elevation range ────────────────────────────────────────────────
    all_elevations = [e for row in dem.elevations for e in row]
    ele_min = min(all_elevations)
    ele_max = max(all_elevations)
    ele_range = ele_max - ele_min

    # ── Model XY dimensions (preserve aspect ratio) ─────────────────────────
    lat_span = dem.lat_max - dem.lat_min
    lon_span = dem.lon_max - dem.lon_min
    cos_lat = math.cos(math.radians((dem.lat_min + dem.lat_max) / 2))
    # Physical aspect ratio (lon distances are shorter at higher latitudes)
    phys_x = lon_span * cos_lat
    phys_y = lat_span
    if phys_x >= phys_y:
        x_size = config.model_size_mm
        y_size = config.model_size_mm * phys_y / phys_x if phys_x > 1e-9 else config.model_size_mm
    else:
        y_size = config.model_size_mm
        x_size = config.model_size_mm * phys_x / phys_y if phys_y > 1e-9 else config.model_size_mm

    z_terrain_base = config.base_thickness_mm

    # ── Terrain STL ─────────────────────────────────────────────────────────
    terrain_tris: List[Triangle] = _build_terrain_triangles(
        dem, config, x_size, y_size, z_terrain_base, ele_min, ele_range
    )

    # Route metadata label
    dist_km = track_data.distance_km
    elev_gain = track_data.elevation_gain_m
    avg_grad = (elev_gain / (dist_km * 1000) * 100) if dist_km > 0.01 else 0.0
    name_line = (track_data.name or "Track")[:24]  # truncate long names
    stats_line = f"{dist_km:.1f}km  {elev_gain:.0f}m  {avg_grad:.1f}%"

    label_tris = _build_label_triangles(
        [name_line, stats_line],
        x_size=x_size,
        y_size=y_size,
        z_base_top=config.base_thickness_mm,
        config=config,
    )
    terrain_tris += label_tris

    terrain_stl = _build_stl(terrain_tris)

    # ── Track STL ───────────────────────────────────────────────────────────
    xy_m = project_points(track_data.points)
    lats = [p.lat for p in track_data.points]
    lons = [p.lon for p in track_data.points]

    track_tris = _build_track_triangles(
        xy_m, dem, config,
        x_size, y_size, z_terrain_base, ele_min, ele_range,
        dem.lat_min, dem.lat_max, dem.lon_min, dem.lon_max,
    )

    track_stl = _build_stl(track_tris)

    return terrain_stl, track_stl
