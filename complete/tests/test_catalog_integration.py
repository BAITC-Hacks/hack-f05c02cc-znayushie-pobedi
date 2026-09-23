import os
os.environ["AI_PROVIDER"] = "demo"
os.environ["CATALOG_MODE"] = "demo"

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.assistant import grounded_answer
from app.catalog import Catalog, NORMALIZED_FILE
from app.sessions import SessionStore


@pytest.fixture
def imported():
    return Catalog(NORMALIZED_FILE)


@pytest.fixture
def imported_client(imported, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "demo")
    monkeypatch.setattr(main, "catalog", imported)
    monkeypatch.setattr(main, "store", SessionStore(imported))
    return TestClient(main.app)


def test_import_preserves_unknown_values_and_source(imported):
    assert len(imported.products) == 40
    assert sum(p["stock"] is None for p in imported.products.values()) == 39
    p = imported.get(515288)
    assert p["id"] == "515288"
    assert p["article"] == p["sku"] == "200300282_"
    assert p["price"] == 65920
    assert p["currency"] is None and p["unit"] is None and p["price_kzt"] is None
    p["features"]["current_a"] = 999
    assert imported.get(515288)["features"]["current_a"] == 160


@pytest.mark.parametrize("query", ["Legrand 160A", "легранд 160 ампер", "трехфазный автомат Legrand 160А"])
def test_strict_current_filters_exclude_conflict(imported, query):
    assert [p["id"] for p in imported.search(query)] == ["515288"]
    assert all(p["features"]["current_a"] == 25 for p in imported.search("25A"))


@pytest.mark.parametrize("query", ["027228", "200300285_", "200300285", "515291", "покажи 027228"])
def test_exact_article_and_numeric_ids_keep_conflicts_visible(imported, query):
    assert [p["id"] for p in imported.search(query)] == ["515291"]
    p = imported.get(515291)
    assert p["features"]["current_a"] is None
    assert p["data_conflicts"][0]["values"] == [160, 250]
    assert "Ток, А" not in p["properties"]


def test_unknown_and_unsupported_query_does_not_broaden(imported):
    assert imported.search("999999999") == []
    for query in ["не Legrand", "Legrand 25A или 125A"]:
        with pytest.raises(ValueError):
            imported.search(query)


def test_snapshot_stock_never_authorizes_cart(imported):
    unknown = imported.check_stock(515288)
    assert unknown["snapshot_quantity"] is None
    assert unknown["enough_in_snapshot"] is None
    total = imported.check_stock(515291, 5)
    assert total["snapshot_quantity"] == 23 and total["enough_in_snapshot"] is True
    for result in [unknown, total, imported.check_stock(515291, 5, 13), imported.check_stock(515291, 1, 2)]:
        assert result["cart_authorized"] is False
        assert result["requires_live_check"] is True
        assert result["currently_available"] is None
    assert imported.check_stock(515291, 6, 13)["enough_in_snapshot"] is False
    assert imported.check_stock(515291, 1, 999)["snapshot_quantity"] is None


def test_analogs_disclose_differences_and_block_conflicting_source(imported):
    result = imported.alternative_result(515290)
    assert result["status"] == "preliminary_candidates"
    assert [p["id"] for p in result["products"]] == ["515287"]
    p = result["products"][0]
    assert p["comparison"]["differences"]["breaking_capacity_ka"] == {"source": 18, "candidate": 25}
    assert "voltage_v" in p["comparison"]["missing_checks"]
    assert p["replacement_confirmed"] is False
    assert p["needs_live_stock_check"] is True
    assert imported.alternative_result(515291)["status"] == "blocked_source_conflict"


def test_grounded_answer_does_not_invent_currency_unit_or_stock(imported):
    text = grounded_answer([imported.get(515288)])
    assert "₸" not in text
    assert "валюта не указана" in text and "Остаток неизвестен" in text
    conflict = grounded_answer([imported.get(515291)])
    assert "160, 250" in conflict
    assert "Остаток в снимке: 23" in conflict
    assert "Ток, А:" not in conflict


def test_imported_http_search_detail_stock_and_blocked_cart(imported_client):
    client = imported_client
    assert client.get("/health").json()["products"] == 40
    assert client.get("/health").json()["source"] == "ekt-snapshot"
    assert client.get("/api/products/search", params={"q": "Legrand 160A"}).json()["products"][0]["id"] == "515288"
    assert client.get("/api/products/515291").json()["stock"] == 23
    assert client.get("/api/products/515291/stock", params={"quantity": 5, "store_id": 13}).json()["snapshot_quantity"] == 5
    assert client.get("/api/products/515290/alternatives").json()["products"][0]["id"] == "515287"
    assert client.get("/api/products/9999/stock").status_code == 404
    for product_id in [515288, 515291]:
        chat = client.post("/api/chat", json={"message": f"добавь {product_id}"}).json()
        assert chat["pending_action"] is None
        sid = chat["session_id"]
        proposal = client.post(f"/api/sessions/{sid}/cart/proposals", json={"product_id": product_id, "quantity": 1})
        assert proposal.status_code == 409
        assert proposal.json()["detail"]["code"] == "live_stock_check_required"
        assert client.get(f"/api/sessions/{sid}/cart").json()["items"] == []


def test_inline_analog_query_and_followup(imported_client):
    response = imported_client.post("/api/chat", json={"message": "аналоги 515290"}).json()
    assert [p["id"] for p in response["products"]] == ["515287"]
    conflict = imported_client.post("/api/chat", json={"message": "аналоги 515291"}).json()
    assert conflict["products"] == []
    assert "конфликт" in conflict["answer"]
    first = imported_client.post("/api/chat", json={"message": "515290"}).json()
    followup = imported_client.post("/api/chat", json={"session_id": first["session_id"], "message": "а аналоги?"}).json()
    assert [p["id"] for p in followup["products"]] == ["515287"]


def test_demo_price_change_requires_a_new_confirmation():
    from app.catalog import DEMO_FILE
    catalog = Catalog(DEMO_FILE)
    store = SessionStore(catalog)
    sid = store.create().id
    proposal = store.propose(sid, "demo-breaker-16a", 1)
    catalog.products["demo-breaker-16a"]["price_kzt"] += 10
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        store.confirm(sid, proposal["proposal_id"], True)
    assert exc.value.detail["code"] == "proposal_changed"
    assert store.cart(sid)["items"] == []


@pytest.mark.parametrize("value", ["true", "yes", 1])
def test_confirmation_requires_actual_json_boolean(value):
    from app.models import ConfirmRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ConfirmRequest(confirm=value)



def test_teammate_service_is_active_and_has_one_catalog_source(imported):
    from ekt_catalog import CatalogService
    from ekt_catalog.service import DEFAULT_PATH
    assert isinstance(imported.service, CatalogService)
    assert NORMALIZED_FILE == DEFAULT_PATH
    assert len(imported.service) == len(imported.products) == 40


def test_structured_search_and_uncertain_matches(imported_client):
    response = imported_client.post("/api/products/search", json={
        "filters": {"brand": "Legrand", "current": 160, "phases": 3}})
    assert response.status_code == 200
    assert [p["id"] for p in response.json()["products"]] == ["515288"]
    assert response.json()["filters"]["current_a"] == 160
    review = imported_client.post("/api/products/search", json={
        "query": "Legrand 160A", "include_uncertain": True}).json()
    assert [p["id"] for p in review["products"]] == ["515288", "515291"]
    assert review["products"][1]["match"]["status"] == "needs_review"
    assert review["products"][1]["features"]["current_a"] is None
    assert review["products"][1]["can_add_to_cart"] is False


@pytest.mark.parametrize("body", [
    {"filters": {"made_up": 1}},
    {"filters": {"current": True}},
    {"query": "160A", "filters": {"current": 200}},
    {"query": "160A", "include_uncertain": "false"},
    {"query": "160A", "limit": True},
    {"query": "160A", "unexpected": "ignored?"},
])
def test_structured_search_rejects_ambiguous_or_invalid_filters(imported_client, body):
    assert imported_client.post("/api/products/search", json=body).status_code == 422


def test_unsupported_search_has_422_but_chat_requests_clarification(imported_client):
    for query in ["не Legrand", "Legrand 125-160A", "Legrand 125A или 160A"]:
        assert imported_client.get("/api/products/search", params={"q": query}).status_code == 422
        response = imported_client.post("/api/chat", json={"message": query})
        assert response.status_code == 200
        data = response.json()
        assert "Уточните" in data["answer"]
        assert data["products"] == [] and data["pending_action"] is None
        assert imported_client.get(f"/api/sessions/{data['session_id']}/cart").json()["items"] == []


def test_intent_wrapper_keeps_extra_constraints(imported):
    for query in ["покажи 515291", "добавь 515291", "аналоги 515291", "покажи артикул 200300285_"]:
        assert [p["id"] for p in imported.search(query)] == ["515291"]
    assert imported.search("покажи 515291 25A") == []
    assert imported.search_result("покажи 515291", filters={"current": 25})["products"] == []
    with pytest.raises(ValueError):
        imported.search("не показывай 515291")


def test_peer_analog_scope_and_original_comparison_flags(imported_client):
    result = imported_client.get("/api/products/515290/alternatives").json()
    assert result["source_status"] == "candidates_require_review"
    assert result["status"] == "preliminary_candidates"
    p = result["products"][0]
    assert p["comparison"]["needs_engineering_review"] is True
    assert "breaking_capacity_reference_conditions" in p["comparison"]["missing_checks"]
    assert "18 → 25" in p["reason"]
    assert imported_client.get("/api/products/25397/alternatives").json()["status"] == "unsupported_category"



def test_explicit_analog_id_cannot_fall_back_to_previous_product(imported_client):
    for message in ["похожие на 515291", "замена 515291"]:
        first = imported_client.post("/api/chat", json={"message": "515290"}).json()
        result = imported_client.post("/api/chat", json={"session_id": first["session_id"], "message": message}).json()
        assert result["products"] == []
        assert "конфликт" in result["answer"]
    for message in ["аналоги 999999999", "похожие на 515291 125A"]:
        first = imported_client.post("/api/chat", json={"message": "515290"}).json()
        result = imported_client.post("/api/chat", json={"session_id": first["session_id"], "message": message}).json()
        assert result["products"] == []
        assert "Уточните" in result["answer"]


def test_explicit_detail_id_cannot_fall_back_to_previous_product(imported_client):
    first = imported_client.post("/api/chat", json={"message": "515288"}).json()
    sid = first["session_id"]
    result = imported_client.post("/api/chat", json={"session_id": sid, "message": "цена 515291"}).json()
    assert [p["id"] for p in result["products"]] == ["515291"]
    result = imported_client.post("/api/chat", json={"session_id": sid, "message": "цена 999999999"}).json()
    assert result["products"] == []
    followup = imported_client.post("/api/chat", json={"session_id": sid, "message": "а наличие?"}).json()
    assert [p["id"] for p in followup["products"]] == ["515291"]

