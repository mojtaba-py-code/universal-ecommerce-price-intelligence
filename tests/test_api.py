"""End-to-end API tests via FastAPI TestClient (offline, fixture-backed)."""

from __future__ import annotations


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["scraper_mode"] == "fixture"


def test_stores_endpoint_lists_amazon(client):
    r = client.get("/api/stores")
    assert r.status_code == 200
    slugs = [s["slug"] for s in r.json()]
    assert "amazon" in slugs


def test_track_and_list_flow(client):
    r = client.post("/api/track", json={"url": "https://www.amazon.com/dp/B08N5WRWNW"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True
    pid = body["product_id"]

    r = client.get("/api/products")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.get(f"/api/products/{pid}")
    assert r.status_code == 200
    detail = r.json()
    assert "Echo Dot" in detail["title"]
    assert detail["current_price"] == 49.99
    assert detail["stats"]["snapshots"] == 1
    assert len(detail["history"]) == 1


def test_track_rejects_unknown_store(client):
    r = client.post("/api/track", json={"url": "https://example.com/p/1"})
    assert r.status_code == 400


def test_refresh_adds_snapshot(client):
    pid = client.post(
        "/api/track", json={"url": "https://www.amazon.com/dp/B08N5WRWNW"}
    ).json()["product_id"]

    client.post(f"/api/products/{pid}/refresh")
    detail = client.get(f"/api/products/{pid}").json()
    assert detail["stats"]["snapshots"] == 2


def test_delete_product(client):
    pid = client.post(
        "/api/track", json={"url": "https://www.amazon.com/dp/B08N5WRWNW"}
    ).json()["product_id"]

    r = client.delete(f"/api/products/{pid}")
    assert r.status_code == 200
    assert client.get("/api/products").json() == []


def test_get_missing_product_404(client):
    assert client.get("/api/products/9999").status_code == 404
