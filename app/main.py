"""FastAPI application – GPX → SVG rendering service."""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from .gpx_parser import parse_gpx, project_points
from .svg_renderer import render_svg

app = FastAPI(
    title="strava3d – GPX to SVG renderer",
    description=(
        "Upload a GPX file and receive a plotter-ready SVG in return. "
        "Ideal for cutting-plotter shirt prints."
    ),
    version="1.0.0",
)


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
    )

    return Response(content=svg_content, media_type="image/svg+xml")
