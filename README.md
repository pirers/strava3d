# strava3d – GPX → SVG Rendering Service

A Docker-based web service that converts a GPX file into a plotter-ready SVG —
perfect for cutting plotters, laser engravers, or shirt prints.

---

## Features

- **Web UI** – Visit `http://localhost:8080` to upload a GPX file, configure options, preview the SVG inline, and download it with one click.
- **`POST /render`** – REST API endpoint: upload a GPX file, receive an `image/svg+xml` response.
- Equirectangular projection with automatic bounding-box scaling & centring.
- Optional **frame** (border rectangle), **track name** and **stats** (distance + elevation gain) embedded as SVG text.
- Designed for cutting plotters: black stroke, transparent background, no fill.
- Fully configurable canvas size, padding, stroke width and CSS unit.

---

## Quick Start

### With Docker Compose (recommended)

```bash
docker compose up --build
```

The service listens on **`http://localhost:8080`**.

Open **`http://localhost:8080`** in your browser to use the web UI.

### With Docker directly

```bash
docker build -t strava3d .
docker run -p 8080:8080 strava3d
```

### Without Docker (local dev)

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

---

## API Reference

### `POST /render`

**Request:** `multipart/form-data` with a mandatory `gpx` field (the GPX file).

All other parameters are **query parameters** (append them to the URL):

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `width` | float > 0 | `300` | Canvas width in *unit* |
| `height` | float > 0 | `300` | Canvas height in *unit* |
| `unit` | `mm` \| `px` | `mm` | CSS unit for width/height/stroke |
| `padding` | float ≥ 0 | `10` | Inner padding in *unit* |
| `stroke_width` | float > 0 | `2` | Stroke width in *unit* |
| `frame` | bool | `false` | Draw a border `<rect>` |
| `name` | string | *(GPX track name)* | Track name as SVG `<text>`; falls back to the name embedded in the GPX file |
| `stats` | bool | `false` | Embed distance (km) and elevation gain (m ↑) as SVG `<text>` |
| `elevation_profile` | bool | `false` | Draw an elevation-profile chart in the bottom 28 % of the canvas |
| `view_3d` | bool | `false` | Render an isometric 3-D view combining track and elevation data |

**Response:** `image/svg+xml` – the generated SVG.

**Error responses:**

| Code | Reason |
|------|--------|
| `400` | Invalid / empty GPX file, unsupported unit, padding too large |

> **Note on elevation gain:** if no `<ele>` data is present in the GPX file,
> elevation gain is reported as **0 m** without error.

---

## `curl` Examples

### Minimal (300 × 300 mm, defaults)

```bash
curl -X POST http://localhost:8080/render \
  -F "gpx=@my_track.gpx" \
  -o track.svg
```

### With frame, stats and custom name

```bash
curl -X POST "http://localhost:8080/render?frame=true&stats=true&name=Bergtour" \
  -F "gpx=@my_track.gpx" \
  -o track.svg
```

### Custom canvas (200 × 150 mm)

```bash
curl -X POST "http://localhost:8080/render?width=200&height=150&unit=mm&padding=8" \
  -F "gpx=@my_track.gpx" \
  -o track.svg
```

### Pixel canvas (for screen preview)

```bash
curl -X POST "http://localhost:8080/render?width=800&height=800&unit=px&stroke_width=2" \
  -F "gpx=@my_track.gpx" \
  -o track.svg
```

---

## Project Structure

```
strava3d/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI app, GET / (web UI) & POST /render endpoint
│   ├── gpx_parser.py     # GPX parsing, distance & elevation helpers
│   ├── svg_renderer.py   # SVG normalisation & rendering
│   └── static/
│       └── index.html    # Self-contained web UI
├── tests/
│   ├── fixtures/
│   │   └── sample.gpx    # Minimal GPX for tests
│   ├── test_api.py        # Integration tests (TestClient)
│   ├── test_gpx_parser.py # Unit tests – parsing, distance, elevation
│   ├── test_svg_renderer.py # Unit tests – normalisation, SVG output
│   └── test_ui.py         # Tests for the web UI route
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## Interactive API Docs

When the service is running, visit:

- Swagger UI: <http://localhost:8080/docs>
- ReDoc:       <http://localhost:8080/redoc>
