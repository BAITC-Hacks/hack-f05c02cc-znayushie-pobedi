"""Run: uvicorn app.main:app --reload"""
import html
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .assistant import answer, grounded_answer
from .attachments import analyze_attachment, MAX_FILE_BYTES, MEDIA_TYPES, ocr_available
from .catalog import Catalog
from .conversation import purchase_intent, search_in_conversation, products_from_attachment
from .models import ChatRequest, ChatResponse, ConfirmRequest, Proposal, ProposalRequest, SearchRequest
from .sessions import SessionStore
from .terms import answer_purchase_terms
from .upload_limit import UploadLimitMiddleware

load_dotenv(".env.local")
load_dotenv(".env")

catalog = Catalog()
store = SessionStore(catalog)
app = FastAPI(title="EKT catalog assistant demo", version="0.6.0")
origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(UploadLimitMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])


@app.get("/health")
def health():
    return {"status": "ok", "catalog": catalog.mode, "source": catalog.source, "products": len(catalog.products),
            "search_engine": "ekt_catalog" if catalog.service is not None else "demo",
            "attachments": {"extensions": list(MEDIA_TYPES), "max_bytes": MAX_FILE_BYTES,
                            "ocr_configured": ocr_available()}}


@app.post("/api/sessions", status_code=201)
def create_session():
    return {"session_id": store.create().id}


@app.get("/api/sessions/{session_id}/messages")
def get_messages(session_id: str):
    return {"messages": store.history(session_id)}


@app.get("/api/products")
def browse_products(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    product_ids = list(catalog.products)
    return {"products": [catalog.get(product_id) for product_id in product_ids[offset:offset + limit]],
            "total": len(product_ids), "source": catalog.source, "catalog": catalog.mode,
            "offset": offset, "limit": limit}


@app.get("/api/products/search")
def search_products(q: str = Query(min_length=1, max_length=2000), limit: int = Query(5, ge=1, le=20)):
    try:
        return catalog.search_result(q, limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/products/search")
def search_products_with_filters(request: SearchRequest):
    try:
        return catalog.search_result(request.query, request.limit, filters=request.filters,
                                     include_uncertain=request.include_uncertain)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    product = catalog.get(product_id)
    if product is None:
        raise HTTPException(404, "Unknown product")
    return product


@app.get("/api/products/{product_id}/alternatives")
def get_alternatives(product_id: str):
    if catalog.get(product_id) is None:
        raise HTTPException(404, "Unknown product")
    return catalog.alternative_result(product_id)


@app.get("/api/products/{product_id}/stock")
def check_stock(product_id: str, quantity: int = Query(1, ge=1, le=1000), store_id: int | None = Query(None, ge=1)):
    if catalog.get(product_id) is None:
        raise HTTPException(404, "Unknown product")
    return catalog.check_stock(product_id, quantity, store_id)


@app.get("/api/purchase-terms")
def purchase_terms(q: str = Query("Условия покупки", min_length=1), demo: bool | None = None):
    result = answer_purchase_terms(q, mode=("demo" if demo else "normalized") if demo is not None else catalog.mode)
    if result is None:
        raise HTTPException(404, "No verified purchase terms for that question")
    return result


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    session = store.get(request.session_id) if request.session_id else store.create()
    def result(text, products=None, proposal=None):
        products = products or []
        store.record(session.id, request.message, text, [p["id"] for p in products])
        return {"session_id": session.id, "answer": text, "products": products, "pending_action": proposal}
    terms = answer_purchase_terms(request.message, mode=catalog.mode)
    if terms is not None:
        return result(terms["answer"] + "\n[Источник условий](" + terms["source_url"] + ")")
    try:
        adding, quantity, query = purchase_intent(request.message)
        products = search_in_conversation(query, session, catalog)
    except ValueError as exc:
        return result("Уточните параметры поиска: " + str(exc))
    requested_products = list(products)
    analog_note = None
    analog_ids = []
    is_analog_query = bool(re.search(r"аналог|замен|похож", request.message.casefold()))
    if is_analog_query:
        previous = products[0] if len(products) == 1 else None
        if not products and session.last_product_ids and is_context_followup(request.message, analog=True):
            previous = catalog.get(session.last_product_ids[0])
        if previous:
            alternatives = catalog.alternative_result(previous["id"])
            products, analog_note = alternatives["products"], alternatives["note"]
            analog_ids = [p["id"] for p in products]
        else:
            products, analog_note = [], "Уточните артикул или ID одного товара, для которого нужны аналоги."
    elif not products and session.last_product_ids and is_context_followup(request.message):
        previous = catalog.get(session.last_product_ids[0])
        products = [previous] if previous else []
    elif products:
        # Unknown stock is never treated as zero. An unavailable selected item gets
        # visible alternatives, but its replacement is never selected for a cart.
        notes = []
        seen = {p["id"] for p in products}
        for original in requested_products[:5]:
            if original["stock"] != 0:
                continue
            alternatives = catalog.alternative_result(original["id"])
            notes.append(f"У товара {original['sku']} остаток в {'снимке' if original['requires_live_check'] else 'демо'} — 0. " +
                         ("Ниже предложены кандидаты с объяснением." if alternatives["products"] else "Совместимые кандидаты в этой выборке не найдены."))
            for candidate in alternatives["products"]:
                if candidate["id"] not in seen and len(products) < 20:
                    products.append(candidate)
                    analog_ids.append(candidate["id"])
                    seen.add(candidate["id"])
        analog_note = "\n".join(notes) or None
    if products:
        session.last_product_ids = [p["id"] for p in products]
        session.last_analog_ids = analog_ids
    # Fast deterministic routes for stock, certificates and analog explanations.
    factual = is_analog_query or analog_note or bool(re.search(r"цен|стоит|налич|остат|сертифик|характерист", request.message, re.I))
    if not products and analog_note:
        text = analog_note
    elif products and factual:
        text = grounded_answer(products, request.language)
    else:
        try:
            text = answer(request.message, products, request.language)
        except HTTPException as exc:
            if not products or exc.status_code not in (502, 503):
                raise
            text = grounded_answer(products, request.language) + "\nСервис ИИ временно недоступен; ответ сформирован непосредственно по каталогу."
    if analog_note and products:
        text += "\n" + analog_note
    proposal = None
    # Add intent may create a proposal. Chat, including 'yes', can never confirm one.
    if adding and not is_analog_query:
        selected = requested_products if len(requested_products) == 1 else []
        if selected and selected[0]["can_add_to_cart"] and selected[0]["stock"] is not None and selected[0]["stock"] > 0:
            try:
                proposal = store.propose(session.id, selected[0]["id"], quantity)
                text += f"\nПодготовлено {quantity} {selected[0]['unit']}. Подтвердите отдельной кнопкой. Пока корзина не изменена."
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                text += "\nНедостаточно доступного количества с учётом корзины. Выберите меньшее количество."
        elif len(selected) == 1 and selected[0]["requires_live_check"]:
            text += "\nДля добавления нужно подтвердить актуальный продаваемый остаток, валюту и единицу продажи. В этом файле только снимок; корзина не изменена."
        else:
            text += "\nДля добавления выберите товар и количество. Корзина не изменена."
    return result(text, products, proposal)


@app.post("/api/sessions/{session_id}/attachments")
async def upload_attachment(session_id: str, request: Request):
    session = store.get(session_id)
    async with request.form(max_files=1, max_fields=1, max_part_size=MAX_FILE_BYTES) as form:
        if any(key not in {"file", "message"} for key in form) or len(form.getlist("file")) != 1:
            raise HTTPException(422, "Передайте один файл и необязательный текст сообщения.")
        file = form.get("file")
        message = form.get("message", "")
        if not isinstance(file, UploadFile) or not isinstance(message, str) or len(message) > 2000:
            raise HTTPException(422, "Некорректный файл или слишком длинное сообщение.")
        content = await file.read(MAX_FILE_BYTES + 1)
        analysis = await run_in_threadpool(analyze_attachment, file.filename or "", content, file.content_type or "")
    products = products_from_attachment(analysis["text"], catalog)
    text = f"Файл «{analysis['filename']}» обработан. "
    if products:
        text += f"Найдено позиций каталога: {len(products)}. Проверьте соответствие распознанным строкам и выберите количество вручную.\n"
        source_products = list(products)
        analog_ids = []
        seen = {p["id"] for p in products}
        for product in source_products:
            if product["stock"] == 0:
                for candidate in catalog.alternative_result(product["id"])["products"]:
                    if candidate["id"] not in seen and len(products) < 20:
                        products.append(candidate)
                        analog_ids.append(candidate["id"])
                        seen.add(candidate["id"])
        text += grounded_answer(products)
        session.last_product_ids = [p["id"] for p in products]
        session.last_analog_ids = analog_ids
    else:
        text += "Подтверждённые совпадения в текущей выборке не найдены. Уточните артикул или параметры из файла."
    text += "\nЗагрузка файла не добавляет товары и не создаёт предложение корзины."
    # Store only a filename and matched public catalog data, never the raw file or extracted text.
    store.record(session_id, f"[Файл: {analysis['filename']}] {message}", text, [p["id"] for p in products])
    return {"session_id": session_id, "answer": text, "products": products,
            "pending_action": None, "attachment": analysis}


def is_context_followup(message: str, analog: bool = False) -> bool:
    text = " ".join(message.casefold().strip(" \t\r\n?!.").split())
    topic = (r"(?:аналоги?|похожие(?: товары)?|замена|замену)" if analog else
             r"(?:цена|стоимость|наличие|характеристики|подробнее|сколько стоит|есть в наличии)")
    return bool(re.fullmatch(r"(?:а )?(?:покажи |покажите )?" + topic +
                             r"(?: (?:для него|для этого товара|у него|его))?", text))


def cart_with_url(request: Request, session_id: str, cart: dict) -> dict:
    return {**cart, "cart_url": str(request.url_for("demo_cart", session_id=session_id))}


@app.get("/api/sessions/{session_id}/cart")
def get_cart(session_id: str, request: Request):
    return cart_with_url(request, session_id, store.cart(session_id))


@app.get("/demo/cart/{session_id}", response_class=HTMLResponse, name="demo_cart")
def demo_cart(session_id: str):
    cart = store.cart(session_id)
    rows = "".join(
        f"<li><span>{html.escape(item['product']['name'])}</span> <strong>{item['quantity']} {html.escape(item['product']['unit'])}</strong> — {item['subtotal_kzt']:,} ₸</li>"
        for item in cart["items"]
    ) or "<li>Корзина пока пуста.</li>"
    return HTMLResponse(
        '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Демо-корзина EKT</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#1e293b}'
        'li{padding:1rem 0;border-bottom:1px solid #ddd;display:flex;gap:1rem;flex-wrap:wrap;justify-content:space-between}ul{list-style:none;padding:0}'
        'strong{white-space:nowrap}small{color:#64748b}</style><h1>Демо-корзина</h1><small>Тестовые товары; это не корзина ekt.kz.</small>'
        f'<ul>{rows}</ul><h2>Итого: {cart["total_kzt"]:,} ₸</h2></html>'
    )


@app.post("/api/sessions/{session_id}/cart/proposals", response_model=Proposal, status_code=201)
def create_proposal(session_id: str, request: ProposalRequest):
    return store.propose(session_id, request.product_id, request.quantity)


@app.post("/api/sessions/{session_id}/cart/proposals/{proposal_id}/confirm")
def confirm_proposal(session_id: str, proposal_id: str, body: ConfirmRequest, request: Request):
    return cart_with_url(request, session_id, store.confirm(session_id, proposal_id, body.confirm))


@app.delete("/api/sessions/{session_id}/cart/proposals/{proposal_id}", status_code=204)
def cancel_proposal(session_id: str, proposal_id: str):
    store.cancel(session_id, proposal_id)


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def mount_frontend(application: FastAPI, frontend_dir: Path = FRONTEND_DIR) -> None:
    """Expose only the entry page and public frontend assets, when supplied."""
    frontend_dir = frontend_dir.resolve()
    index = frontend_dir / "index.html"
    if not index.is_file() or not index.resolve().is_relative_to(frontend_dir):
        return

    @application.get("/", response_class=FileResponse, include_in_schema=False)
    def frontend_index():
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-store"})

    for url, directory in (("/src", frontend_dir / "src"),
                           ("/assets", frontend_dir / "public" / "assets"),
                           ("/documents", frontend_dir / "public" / "documents")):
        if directory.is_dir() and directory.resolve().is_relative_to(frontend_dir):
            application.mount(url, StaticFiles(directory=directory, follow_symlink=False), name=url[1:])

    def public_file(path):
        def response():
            return FileResponse(path, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        return response

    for url, filename in (("/embed.js", "embed.js"), ("/embed-demo", "embed-demo.html")):
        path = frontend_dir / "public" / filename
        if path.is_file() and path.resolve().is_relative_to(frontend_dir):
            application.add_api_route(url, public_file(path), methods=["GET"], include_in_schema=False)


mount_frontend(app)
