"""Download and sample SRTM DEM data for a lat/lon bounding box.

Uses the ``srtm.py`` package which automatically downloads and caches SRTM3
tiles (90 m resolution) from public mirrors.  No API key is required.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import srtm

# Singleton – reusing the same GeoElevationData instance avoids re-loading
# already-cached HGT tiles on every request.
_elevation_data: Optional[srtm.data.GeoElevationData] = None


def _get_elevation_data() -> srtm.data.GeoElevationData:
    global _elevation_data
    if _elevation_data is None:
        _elevation_data = srtm.get_data()
    return _elevation_data


@dataclass
class DemGrid:
    """A regular lat/lon grid of elevation samples (metres above sea level)."""

    elevations: List[List[float]]
    """Row-major grid: elevations[row][col].  Row 0 is the *northernmost* row."""

    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    n_rows: int = field(init=False)
    n_cols: int = field(init=False)

    def __post_init__(self) -> None:
        self.n_rows = len(self.elevations)
        self.n_cols = len(self.elevations[0]) if self.elevations else 0

    def sample(self, lat: float, lon: float) -> float:
        """Bilinear interpolation of elevation at an arbitrary lat/lon.

        Returns 0.0 if the coordinates are outside the grid.
        """
        if self.n_rows < 2 or self.n_cols < 2:
            return 0.0
        if not (self.lat_min <= lat <= self.lat_max and self.lon_min <= lon <= self.lon_max):
            return 0.0

        # Normalised position within the grid (0 = north/west edge)
        row_f = (self.lat_max - lat) / (self.lat_max - self.lat_min) * (self.n_rows - 1)
        col_f = (lon - self.lon_min) / (self.lon_max - self.lon_min) * (self.n_cols - 1)

        r0, c0 = int(row_f), int(col_f)
        r1, c1 = min(r0 + 1, self.n_rows - 1), min(c0 + 1, self.n_cols - 1)
        dr, dc = row_f - r0, col_f - c0

        e00 = self.elevations[r0][c0]
        e01 = self.elevations[r0][c1]
        e10 = self.elevations[r1][c0]
        e11 = self.elevations[r1][c1]

        return (
            e00 * (1 - dr) * (1 - dc)
            + e01 * (1 - dr) * dc
            + e10 * dr * (1 - dc)
            + e11 * dr * dc
        )


def fetch_dem_grid(
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    *,
    n_rows: int = 128,
    n_cols: int = 128,
) -> DemGrid:
    """Return a :class:`DemGrid` of real SRTM elevation samples.

    Samples are drawn on a regular *n_rows × n_cols* grid covering the given
    bounding box.  SRTM3 tiles (≈ 90 m resolution) are downloaded and cached
    automatically the first time a tile is needed.

    Args:
        lat_min: Southernmost latitude (degrees).
        lat_max: Northernmost latitude (degrees).
        lon_min: Westernmost longitude (degrees).
        lon_max: Easternmost longitude (degrees).
        n_rows: Number of sample rows (north → south).
        n_cols: Number of sample columns (west → east).

    Returns:
        A :class:`DemGrid` with *n_rows × n_cols* elevation values.
    """
    if lat_min >= lat_max or lon_min >= lon_max:
        raise ValueError("lat_min/lon_min must be strictly less than lat_max/lon_max")
    if n_rows < 2 or n_cols < 2:
        raise ValueError("n_rows and n_cols must each be at least 2")

    ed = _get_elevation_data()

    rows: List[List[float]] = []
    for r in range(n_rows):
        # Row 0 = northernmost
        lat = lat_max - (lat_max - lat_min) * r / (n_rows - 1)
        row: List[float] = []
        for c in range(n_cols):
            lon = lon_min + (lon_max - lon_min) * c / (n_cols - 1)
            ele = ed.get_elevation(lat, lon)
            row.append(float(ele) if ele is not None else 0.0)
        rows.append(row)

    return DemGrid(
        elevations=rows,
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
    )


def bounding_box_with_padding(
    lats: List[float],
    lons: List[float],
    padding_km: float,
) -> tuple[float, float, float, float]:
    """Return *(lat_min, lat_max, lon_min, lon_max)* expanded by *padding_km*.

    The padding is applied in all four directions using approximate
    degree-per-km factors so that the expansion is correct at the centre of
    the bounding box.
    """
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)

    lat_mid = (lat_min + lat_max) / 2.0
    km_per_deg_lat = 111.132  # approximately constant
    km_per_deg_lon = 111.320 * math.cos(math.radians(lat_mid))

    d_lat = padding_km / km_per_deg_lat
    d_lon = padding_km / km_per_deg_lon if km_per_deg_lon > 0 else 0.0

    return (
        lat_min - d_lat,
        lat_max + d_lat,
        lon_min - d_lon,
        lon_max + d_lon,
    )
