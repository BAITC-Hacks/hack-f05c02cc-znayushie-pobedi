"""In-memory demo sessions. A lock protects cart mutations and proposal consumption."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from fastapi import HTTPException

from .catalog import Catalog

TTL = timedelta(minutes=10)


@dataclass
class Session:
    id: str
    cart: dict[str, int] = field(default_factory=dict)
    last_product_ids: list[str] = field(default_factory=list)
    last_analog_ids: list[str] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    proposals: dict[str, dict] = field(default_factory=dict)


class SessionStore:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.sessions: dict[str, Session] = {}
        self.lock = RLock()

    def get(self, session_id: str) -> Session:
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                raise HTTPException(404, "Unknown session")
            return session

    def create(self) -> Session:
        with self.lock:
            session = Session(str(uuid4()))
            self.sessions[session.id] = session
            return session

    def record(self, session_id: str, message: str, answer: str, product_ids: list[str]) -> None:
        with self.lock:
            session = self.get(session_id)
            session.messages.extend([
                {"role": "user", "text": message[:2000], "product_ids": []},
                {"role": "bot", "text": answer[:16000], "product_ids": list(product_ids)[:20]},
            ])
            session.messages = session.messages[-40:]

    def history(self, session_id: str) -> list[dict]:
        with self.lock:
            return [{"role": item["role"], "text": item["text"],
                     "products": [p for pid in item["product_ids"] if (p := self.catalog.get(pid)) is not None]}
                    for item in self.get(session_id).messages]

    def cart(self, session_id: str) -> dict:
        with self.lock:
            session = self.get(session_id)
            items = [{"product": self.catalog.get(pid), "quantity": qty, "subtotal_kzt": self.catalog.get(pid)["price_kzt"] * qty} for pid, qty in session.cart.items()]
            return {"session_id": session_id, "items": items, "total_kzt": sum(i["subtotal_kzt"] for i in items)}

    def _check_cart_stock(self, session: Session, product_id: str, quantity: int) -> None:
        result = self.catalog.check_stock(product_id, session.cart.get(product_id, 0) + quantity)
        if result["requires_live_check"]:
            raise HTTPException(409, {"code": "live_stock_check_required", "message": "В файле только снимок каталога. Для добавления нужны актуальный продаваемый остаток, валюта и единица продажи.", "stock_check": result})
        if not result["cart_authorized"]:
            raise HTTPException(409, "Insufficient stock in demo catalog")

    def propose(self, session_id: str, product_id: str, quantity: int) -> dict:
        with self.lock:
            session = self.get(session_id)
            product = self.catalog.get(product_id)
            if product is None:
                raise HTTPException(404, "Unknown product")
            if quantity < 1 or quantity > 1000:
                raise HTTPException(422, "Quantity must be from 1 to 1000")
            self._check_cart_stock(session, product_id, quantity)
            proposal_id = str(uuid4())
            result = {"proposal_id": proposal_id, "product_id": product_id, "quantity": quantity,
                      "expires_at": datetime.now(timezone.utc) + TTL, "product": product}
            session.proposals[proposal_id] = {"status": "pending", "data": result}
            return result

    def confirm(self, session_id: str, proposal_id: str, confirmed: bool) -> dict:
        with self.lock:
            session = self.get(session_id)
            entry = session.proposals.get(proposal_id)
            if entry is None:
                raise HTTPException(404, "Unknown proposal for this session")
            if confirmed is not True:
                raise HTTPException(422, "Explicit confirm: true is required")
            if entry["status"] == "confirmed":
                return entry["cart"]  # frontend retries are idempotent
            if entry["status"] != "pending":
                raise HTTPException(409, "Proposal is no longer pending")
            proposal = entry["data"]
            if datetime.now(timezone.utc) >= proposal["expires_at"]:
                entry["status"] = "expired"
                raise HTTPException(409, "Proposal expired")
            product = self.catalog.get(proposal["product_id"])
            if product is None:
                raise HTTPException(409, "Product is unavailable or stock has changed")
            self._check_cart_stock(session, proposal["product_id"], proposal["quantity"])
            if any(product.get(key) != proposal["product"].get(key) for key in ("price", "price_kzt", "currency", "unit")):
                entry["status"] = "changed"
                raise HTTPException(409, {"code": "proposal_changed", "message": "Цена или единица продажи изменились. Создайте новое предложение и подтвердите его."})
            session.cart[proposal["product_id"]] = session.cart.get(proposal["product_id"], 0) + proposal["quantity"]
            entry["status"] = "confirmed"
            entry["cart"] = self.cart(session_id)
            return entry["cart"]

    def cancel(self, session_id: str, proposal_id: str) -> None:
        with self.lock:
            entry = self.get(session_id).proposals.get(proposal_id)
            if entry is None:
                raise HTTPException(404, "Unknown proposal for this session")
            if entry["status"] != "pending":
                raise HTTPException(409, "Proposal is no longer pending")
            entry["status"] = "cancelled"

