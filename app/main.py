"""FastAPI application – GPX → SVG rendering service."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .dem_fetcher import bounding_box_with_padding, fetch_dem_grid
from .gpx_parser import parse_gpx, project_points
from .stl_generator import TerrainModelConfig, generate_terrain_stls
from .svg_renderer import render_svg

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="strava3d – GPX to SVG renderer",
    description=(
        "Upload a GPX file and receive a plotter-ready SVG in return. "
        "Ideal for cutting-plotter shirt prints."
    ),
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse, include_in_schema=False)
async def index() -> FileResponse:
    """Serve the web UI."""
    return FileResponse(_STATIC_DIR / "index.html", media_type="text/html")


@app.post(
    "/render",
    response_class=Response,
    responses={
        200: {"content": {"image/svg+xml": {}}, "description": "Generated SVG"},
        400: {"description": "Invalid input (bad GPX or parameters)"},
    },
)
async def render(
    gpx: UploadFile = File(..., description="GPX file to render"),
    width: float = Query(300.0, gt=0, description="Canvas width (in *unit*)"),
    height: float = Query(300.0, gt=0, description="Canvas height (in *unit*)"),
    unit: str = Query("mm", description="CSS unit: mm or px"),
    padding: float = Query(10.0, ge=0, description="Inner padding (in *unit*)"),
    stroke_width: float = Query(2.0, gt=0, description="Stroke width (in *unit*)"),
    frame: bool = Query(False, description="Draw a border rectangle"),
    name: Optional[str] = Query(None, description="Track name to embed as text"),
    stats: bool = Query(False, description="Embed distance and elevation gain as text"),
    elevation_profile: bool = Query(False, description="Draw an elevation-profile chart below the track map"),
    view_3d: bool = Query(False, description="Render an isometric 3-D view combining track and elevation data"),
) -> Response:
    """Render a GPX track as a plotter-ready SVG.

    **Query parameters** (all optional):

    | Parameter | Default | Description |
    |-----------|---------|-------------|
    | `width` | 300 | Canvas width in *unit* |
    | `height` | 300 | Canvas height in *unit* |
    | `unit` | `mm` | `mm` or `px` |
    | `padding` | 10 | Inner padding in *unit* |
    | `stroke_width` | 2 | Stroke width in *unit* |
    | `frame` | `false` | Draw a border rectangle |
    | `name` | *(none)* | Track name as SVG text |
    | `stats` | `false` | Distance & elevation as SVG text |
    | `elevation_profile` | `false` | Elevation-profile chart below track |
    | `view_3d` | `false` | Isometric 3-D view combining track and elevation |

    **Note on elevation gain**: if no elevation data is present in the GPX,
    elevation gain is reported as 0 m.
    """
    if unit not in ("mm", "px"):
        raise HTTPException(status_code=400, detail="unit must be 'mm' or 'px'")

    if padding * 2 >= width or padding * 2 >= height:
        raise HTTPException(
            status_code=400,
            detail="padding is too large relative to width/height",
        )

    raw_bytes = await gpx.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded GPX file is empty")

    try:
        track_data = parse_gpx(raw_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Use track name from GPX if not overridden via query param
    display_name: Optional[str] = name if name is not None else track_data.name

    stats_text: Optional[str] = None
    if stats:
        dist = f"{track_data.distance_km:.1f} km"
        elev = f"{track_data.elevation_gain_m:.0f} m \u2191"
        stats_text = f"{dist}  |  {elev}"

    xy = project_points(track_data.points)

    # Elevations are needed for both the separate profile panel and the 3-D view.
    elevations = (
        [p.ele for p in track_data.points]
        if elevation_profile or view_3d
        else None
    )

    svg_content = render_svg(
        xy=xy,
        width=width,
        height=height,
        padding=padding,
        stroke_width=stroke_width,
        unit=unit,
        frame=frame,
        name=display_name,
        stats=stats_text,
        elevations=elevations,
        view_3d=view_3d,
    )

    return Response(content=svg_content, media_type="image/svg+xml")


@app.post(
    "/render_terrain",
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "ZIP archive containing terrain.stl and track.stl",
        },
        400: {"description": "Invalid input (bad GPX or parameters)"},
    },
)
async def render_terrain(
    gpx: UploadFile = File(..., description="GPX file to render"),
    terrain_padding_km: float = Query(
        0.5,
        ge=0,
        description="Extra terrain to include around the track (km)",
    ),
    model_size_mm: float = Query(
        150.0,
        gt=0,
        description="Longest side of the printed terrain block (mm)",
    ),
    base_thickness_mm: float = Query(
        3.0,
        gt=0,
        description="Thickness of the solid base plate (mm)",
    ),
    terrain_height_mm: float = Query(
        20.0,
        gt=0,
        description="Maximum terrain relief above the base plate (mm)",
    ),
    track_width_mm: float = Query(
        2.0,
        gt=0,
        description="Width of the raised track ribbon (mm)",
    ),
    track_raised_mm: float = Query(
        0.8,
        gt=0,
        description="Height the track ribbon is raised above the terrain (mm)",
    ),
    dem_resolution: int = Query(
        128,
        ge=16,
        le=512,
        description="DEM grid resolution (points per side; higher = more detail, slower)",
    ),
) -> StreamingResponse:
    """Generate a 3-D printable terrain model from a GPX track.

    Returns a ZIP archive with two binary STL files:

    * **terrain.stl** – terrain surface and solid base plate.  Print in your
      main filament colour.
    * **track.stl** – raised ribbon following the GPS route.  Assign a
      contrasting colour (e.g. via filament swap or multi-material).

    The base plate label includes the route name, distance, elevation gain and
    average gradient embossed in a pixel font.

    **Query parameters:**

    | Parameter | Default | Description |
    |-----------|---------|-------------|
    | `terrain_padding_km` | 0.5 | Extra terrain beyond the track bounding box (km) |
    | `model_size_mm` | 150 | Longest side of the printed block (mm) |
    | `base_thickness_mm` | 3 | Base plate thickness (mm) |
    | `terrain_height_mm` | 20 | Maximum terrain relief (mm) |
    | `track_width_mm` | 2 | Track ribbon width (mm) |
    | `track_raised_mm` | 0.8 | Track ribbon height above terrain (mm) |
    | `dem_resolution` | 128 | DEM grid size (points per side) |
    """
    raw_bytes = await gpx.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded GPX file is empty")

    try:
        track_data = parse_gpx(raw_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    lats = [p.lat for p in track_data.points]
    lons = [p.lon for p in track_data.points]

    lat_min, lat_max, lon_min, lon_max = bounding_box_with_padding(
        lats, lons, terrain_padding_km
    )

    try:
        dem = fetch_dem_grid(
            lat_min, lat_max, lon_min, lon_max,
            n_rows=dem_resolution,
            n_cols=dem_resolution,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch DEM data: {exc}",
        ) from exc

    config = TerrainModelConfig(
        model_size_mm=model_size_mm,
        base_thickness_mm=base_thickness_mm,
        terrain_height_mm=terrain_height_mm,
        track_raised_mm=track_raised_mm,
        track_width_mm=track_width_mm,
    )

    try:
        terrain_stl, track_stl = generate_terrain_stls(track_data, dem, config)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"STL generation failed: {exc}",
        ) from exc

    # Bundle both STL files into a ZIP archive
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("terrain.stl", terrain_stl)
        zf.writestr("track.stl", track_stl)
        readme = (
            "strava3d – 3D printable terrain model\n"
            "======================================\n\n"
            "Files:\n"
            "  terrain.stl  – terrain surface + base plate (main colour)\n"
            "  track.stl    – GPS track ribbon (accent colour)\n\n"
            "Import both files into your slicer and assign different colours.\n"
            "For single-extruder printers, use a filament-swap colour change\n"
            f"at z = {base_thickness_mm + terrain_height_mm:.1f} mm.\n"
        )
        zf.writestr("README.txt", readme)
    buf.seek(0)

    track_name = (track_data.name or "terrain").replace(" ", "_")
    filename = f"{track_name}_3d.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
