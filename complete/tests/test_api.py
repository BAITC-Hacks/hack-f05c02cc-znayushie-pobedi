import os
os.environ["AI_PROVIDER"] = "demo"
os.environ["CATALOG_MODE"] = "demo"

from fastapi.testclient import TestClient

from app.main import app, catalog, store

client = TestClient(app)
PRODUCT = "demo-breaker-16a"


def session():
    response = client.post("/api/chat", json={"message": "автомат 16 А"})
    assert response.status_code == 200
    return response.json()["session_id"]


def propose(sid, quantity=1, product=PRODUCT):
    return client.post(f"/api/sessions/{sid}/cart/proposals", json={"product_id": product, "quantity": quantity})


def confirm(sid, pid, value=True):
    return client.post(f"/api/sessions/{sid}/cart/proposals/{pid}/confirm", json={"confirm": value})


def test_catalog_and_read_only_chat():
    sid = session()
    assert client.get("/api/products/search", params={"q": "C16"}).json()["products"]
    assert client.get(f"/api/products/{PRODUCT}/alternatives").json()["products"]
    assert client.post("/api/chat", json={"session_id": sid, "message": "да, подтверждаю"}).status_code == 200
    assert client.get(f"/api/sessions/{sid}/cart").json()["items"] == []


def test_explicit_confirmation_and_idempotency():
    sid = session()
    proposal = propose(sid, 2).json()
    pid = proposal["proposal_id"]
    assert client.get(f"/api/sessions/{sid}/cart").json()["items"] == []
    assert confirm(sid, pid, False).status_code == 422
    assert client.get(f"/api/sessions/{sid}/cart").json()["items"] == []
    first = confirm(sid, pid).json()
    assert first["items"][0]["quantity"] == 2
    assert confirm(sid, pid).json() == first
    assert client.get(f"/api/sessions/{sid}/cart").json()["items"][0]["quantity"] == 2


def test_session_isolation_cancel_and_stock():
    first, second = session(), session()
    pid = propose(first).json()["proposal_id"]
    assert confirm(second, pid).status_code == 404
    assert client.delete(f"/api/sessions/{first}/cart/proposals/{pid}").status_code == 204
    assert confirm(first, pid).status_code == 409
    assert propose(first, product="demo-cable-pvs-3x2-5").status_code == 409
    assert propose(first, quantity=0).status_code == 422
    assert client.get(f"/api/sessions/{first}/cart").json()["items"] == []


def test_chat_proposal_requires_separate_confirm():
    sid = session()
    result = client.post("/api/chat", json={"session_id": sid, "message": "добавь DEMO-004"}).json()
    assert result["pending_action"]["product_id"] == PRODUCT
    assert client.get(f"/api/sessions/{sid}/cart").json()["items"] == []
    assert client.post("/api/chat", json={"session_id": sid, "message": "да"}).status_code == 200
    assert client.get(f"/api/sessions/{sid}/cart").json()["items"] == []
    assert confirm(sid, result["pending_action"]["proposal_id"]).json()["items"][0]["quantity"] == 1


def test_stock_rechecked_on_confirmation():
    sid = session()
    pid = propose(sid).json()["proposal_id"]
    original = catalog.products[PRODUCT]["stock"]
    try:
        catalog.products[PRODUCT]["stock"] = 0
        assert confirm(sid, pid).status_code == 409
        assert client.get(f"/api/sessions/{sid}/cart").json()["items"] == []
    finally:
        catalog.products[PRODUCT]["stock"] = original

def test_expiry_and_no_quantity_override():
    from datetime import datetime, timedelta, timezone
    sid = session()
    pid = propose(sid).json()["proposal_id"]
    store.sessions[sid].proposals[pid]["data"]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert confirm(sid, pid).status_code == 409
    assert client.get(f"/api/sessions/{sid}/cart").json()["items"] == []
    pid = propose(sid).json()["proposal_id"]
    response = client.post(f"/api/sessions/{sid}/cart/proposals/{pid}/confirm", json={"confirm": True, "quantity": 100})
    assert response.status_code == 422
    assert client.get(f"/api/sessions/{sid}/cart").json()["items"] == []
    assert confirm(sid, pid).json()["items"][0]["quantity"] == 1


def test_followup_uses_session_context_and_stockout_chat_is_read_only():
    sid = session()
    followup = client.post("/api/chat", json={"session_id": sid, "message": "а аналоги?"}).json()
    assert followup["products"]
    assert all(p["id"] != PRODUCT for p in followup["products"])
    out_of_stock = client.post("/api/chat", json={"session_id": sid, "message": "добавь DEMO-003"})
    assert out_of_stock.status_code == 200
    assert out_of_stock.json()["pending_action"] is None
    assert client.get(f"/api/sessions/{sid}/cart").json()["items"] == []

def test_purchase_terms_are_grounded_and_do_not_change_cart():
    sid = session()
    for question, topic in [("Как оплатить?", "payment"), ("Как работает доставка?", "delivery"), ("Есть минимальная партия?", "minimum_order")]:
        result = client.get("/api/purchase-terms", params={"q": question})
        assert result.status_code == 200
        assert result.json()["topic"] == topic
        assert result.json()["source_url"].startswith("/api/purchase-terms")
        assert result.json()["is_demo"] is True
        chat = client.post("/api/chat", json={"session_id": sid, "message": question}).json()
        assert chat["answer"]
        assert chat["pending_action"] is None
    assert client.get(f"/api/sessions/{sid}/cart").json()["items"] == []


def test_confirm_returns_a_live_demo_cart_url():
    sid = session()
    empty = client.get(f"/api/sessions/{sid}/cart").json()
    assert empty["cart_url"].endswith(f"/demo/cart/{sid}")
    assert "Корзина пока пуста" in client.get(empty["cart_url"]).text
    pid = propose(sid, 2).json()["proposal_id"]
    assert "Корзина пока пуста" in client.get(empty["cart_url"]).text
    cart = confirm(sid, pid).json()
    page = client.get(cart["cart_url"])
    assert page.status_code == 200
    assert "Автоматический выключатель" in page.text
    assert "3,900" in page.text
    assert confirm(sid, pid).json() == cart

