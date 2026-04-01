"""Tests for the web UI route."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_ui_returns_200():
    resp = client.get("/")
    assert resp.status_code == 200


def test_ui_content_type_html():
    resp = client.get("/")
    assert "text/html" in resp.headers["content-type"]


def test_ui_contains_form():
    resp = client.get("/")
    body = resp.text
    assert "<form" in body
    assert 'id="renderForm"' in body


def test_ui_contains_file_input():
    resp = client.get("/")
    assert 'type="file"' in resp.text


def test_ui_contains_download_link():
    resp = client.get("/")
    assert "Download SVG" in resp.text


def test_static_index_html_served():
    """Verify the /static/index.html is also accessible."""
    resp = client.get("/static/index.html")
    assert resp.status_code == 200
