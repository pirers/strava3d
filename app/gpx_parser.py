"""GPX parsing, distance and elevation helpers."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import gpxpy
import gpxpy.gpx


@dataclass
class TrackPoint:
    lat: float
    lon: float
    ele: Optional[float] = None


@dataclass
class TrackData:
    points: List[TrackPoint] = field(default_factory=list)
    name: Optional[str] = None
    distance_km: float = 0.0
    elevation_gain_m: float = 0.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two lat/lon points."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def parse_gpx(gpx_bytes: bytes) -> TrackData:
    """Parse GPX bytes and return a :class:`TrackData` instance.

    Notes:
        - Only the first track's segments are used.
        - If elevation (``ele``) is missing for all points, ``elevation_gain_m``
          is set to 0 and this is considered normal behaviour.
    """
    try:
        gpx = gpxpy.parse(gpx_bytes)
    except Exception as exc:
        raise ValueError(f"Invalid GPX data: {exc}") from exc

    points: List[TrackPoint] = []
    name: Optional[str] = None

    for track in gpx.tracks:
        if name is None and track.name:
            name = track.name
        for segment in track.segments:
            for pt in segment.points:
                points.append(TrackPoint(lat=pt.latitude, lon=pt.longitude, ele=pt.elevation))

    # Also consider waypoints / routes if no track points found
    if not points:
        for route in gpx.routes:
            if name is None and route.name:
                name = route.name
            for pt in route.points:
                points.append(TrackPoint(lat=pt.latitude, lon=pt.longitude, ele=pt.elevation))

    if not points:
        raise ValueError("GPX contains no track points.")

    distance_m = 0.0
    elevation_gain_m = 0.0
    for i in range(1, len(points)):
        prev, curr = points[i - 1], points[i]
        distance_m += _haversine_m(prev.lat, prev.lon, curr.lat, curr.lon)
        if curr.ele is not None and prev.ele is not None:
            delta = curr.ele - prev.ele
            if delta > 0:
                elevation_gain_m += delta

    return TrackData(
        points=points,
        name=name,
        distance_km=distance_m / 1000.0,
        elevation_gain_m=elevation_gain_m,
    )


def project_points(points: List[TrackPoint]) -> List[Tuple[float, float]]:
    """Convert lat/lon to equirectangular (x, y) in metres.

    The centre of the bounding box is used as the reference point so that
    distortion is minimal for the typical track sizes involved.
    """
    if not points:
        return []

    lat_min = min(p.lat for p in points)
    lat_max = max(p.lat for p in points)
    lon_min = min(p.lon for p in points)
    lon_max = max(p.lon for p in points)

    lat_mid = (lat_min + lat_max) / 2.0
    cos_lat = math.cos(math.radians(lat_mid))
    R = 6_371_000.0

    result: List[Tuple[float, float]] = []
    for p in points:
        x = R * math.radians(p.lon) * cos_lat
        y = R * math.radians(p.lat)
        result.append((x, y))
    return result
