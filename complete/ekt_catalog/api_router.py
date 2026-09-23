"""Optional FastAPI integration. Import this router into the backend's existing app."""
from functools import lru_cache
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from .service import CatalogService

router = APIRouter(tags=["EKT catalog"])

@lru_cache(maxsize=1)
def get_catalog() -> CatalogService:
    return CatalogService()

class SearchRequest(BaseModel):
    query: str = Field(default="", max_length=2000)
    filters: dict[str, Any] | None = None
    limit: int = Field(default=10, ge=1, le=50)
    include_uncertain: bool = False

class StockRequest(BaseModel):
    quantity: float = Field(gt=0, allow_inf_nan=False, strict=True)
    store_id: int | None = Field(default=None, gt=0)

@router.get("/health")
def health():
    return {"status": "ok", "products": len(get_catalog()), "data_mode": "snapshot"}

@router.post("/search")
def search(request: SearchRequest):
    try:
        return get_catalog().search_products(request.query, filters=request.filters,
                                             limit=request.limit, include_uncertain=request.include_uncertain)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get("/products/{product_id}")
def detail(product_id: int):
    try:
        return get_catalog().get_product_detail(product_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Product not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get("/products/{product_id}/analogs")
def analogs(product_id: int, limit: int = Query(default=5, ge=1, le=50), only_snapshot_available: bool = False):
    try:
        return get_catalog().find_analogs(product_id, limit=limit, only_snapshot_available=only_snapshot_available)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Product not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post("/products/{product_id}/stock-check")
def stock(product_id: int, request: StockRequest):
    try:
        return get_catalog().check_stock(product_id, request.quantity, store_id=request.store_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Product not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
