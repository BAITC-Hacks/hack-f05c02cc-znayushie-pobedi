import os

os.environ["AI_PROVIDER"] = "demo"
os.environ["CATALOG_MODE"] = "demo"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.catalog import Catalog, NORMALIZED_FILE
from app.sessions import SessionStore


@pytest.fixture
def normalized_client(monkeypatch):
    catalog = Catalog(NORMALIZED_FILE)
    monkeypatch.setattr(main, "catalog", catalog)
    monkeypatch.setattr(main, "store", SessionStore(catalog))
    return TestClient(main.app)


def test_session_creation_does_not_call_llm_and_starts_with_empty_cart(normalized_client, monkeypatch):
    def unexpected_answer(*args, **kwargs):
        raise AssertionError("Creating a session must not call the assistant")

    monkeypatch.setattr(main, "answer", unexpected_answer)
    first = normalized_client.post("/api/sessions")
    second = normalized_client.post("/api/sessions")
    assert first.status_code == second.status_code == 201
    assert first.json()["session_id"] != second.json()["session_id"]
    cart = normalized_client.get(f'/api/sessions/{first.json()["session_id"]}/cart')
    assert cart.status_code == 200
    assert cart.json()["items"] == []
    assert cart.json()["total_kzt"] == 0


def test_browse_preserves_snapshot_nulls_and_product_contract(normalized_client):
    result = normalized_client.get("/api/products", params={"limit": 100}).json()
    assert result["total"] == len(result["products"]) == 40
    assert result["source"] == "ekt-snapshot"
    assert result["catalog"] == "normalized"
    assert sum(p["stock"] is None for p in result["products"]) == 39
    for product in result["products"]:
        assert isinstance(product["id"], str)
        assert product["sku"] == product["article"]
        assert product["stock"] == product["quantity"]
        assert product["currency"] is None
        assert product["unit"] is None
        assert product["price_kzt"] is None
        assert product["requires_live_check"] is True
        assert product["can_add_to_cart"] is False
        assert product == normalized_client.get(f'/api/products/{product["id"]}').json()


def test_browse_pagination_is_stable_and_bounded(normalized_client):
    all_products = normalized_client.get("/api/products", params={"limit": 100}).json()["products"]
    result = normalized_client.get("/api/products", params={"offset": 3, "limit": 7}).json()
    assert result["products"] == all_products[3:10]
    assert result["offset"] == 3
    assert result["limit"] == 7
    assert result["total"] == 40
    assert normalized_client.get("/api/products", params={"offset": 40}).json()["products"] == []
    for params in ({"offset": -1}, {"limit": 0}, {"limit": 101}, {"offset": 1.5}):
        assert normalized_client.get("/api/products", params=params).status_code == 422
    assert normalized_client.get("/api/products/search", params={"q": "515291"}).status_code == 200


@pytest.fixture
def static_client(tmp_path):
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "public" / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><title>EKT frontend</title>", encoding="utf-8")
    (frontend / "src" / "app.js").write_text("export const app = 'EKT';", encoding="utf-8")
    (frontend / "src" / "style.css").write_text("body { color: purple; }", encoding="utf-8")
    (frontend / "public" / "assets" / "breaker.jpg").write_bytes(b"test-image")
    for base in (tmp_path, frontend):
        (base / ".env.local").write_text("PRIVATE_MARKER_DO_NOT_SERVE", encoding="utf-8")
        (base / "README.md").write_text("PRIVATE_MARKER_DO_NOT_SERVE", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("PRIVATE_MARKER_DO_NOT_SERVE", encoding="utf-8")
    application = FastAPI()
    main.mount_frontend(application, frontend)
    return TestClient(application)


def test_frontend_only_serves_entry_page_and_explicit_asset_directories(static_client):
    assert "EKT frontend" in static_client.get("/").text
    assert static_client.get("/").headers["content-type"].startswith("text/html")
    assert static_client.get("/").headers["cache-control"] == "no-store"
    assert "export const app" in static_client.get("/src/app.js").text
    assert "purple" in static_client.get("/src/style.css").text
    assert static_client.get("/assets/breaker.jpg").content == b"test-image"
    assert static_client.get("/src/missing.js").status_code == 404


@pytest.mark.parametrize("path", [
    "/.env.local", "/.env", "/README.md", "/app/main.py", "/frontend/index.html",
    "/public/assets/breaker.jpg", "/src/../.env.local", "/src/%2e%2e/.env.local",
    "/src/%2e%2e/%2e%2e/.env.local", "/assets/%2e%2e/%2e%2e/.env.local",
    "/assets/..%5c..%5c.env.local", "/src/..%5c..%5capp%5cmain.py",
])
def test_frontend_does_not_expose_secret_or_backend_files(static_client, path):
    response = static_client.get(path)
    assert response.status_code == 404
    assert "PRIVATE_MARKER_DO_NOT_SERVE" not in response.text


def test_backend_can_start_without_frontend(tmp_path):
    application = FastAPI()
    main.mount_frontend(application, tmp_path / "not-supplied")
    assert TestClient(application).get("/").status_code == 404
