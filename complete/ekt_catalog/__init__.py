"""Public backend interface. Python 3.10+, standard library only for the core."""
from .normalize import normalize_product, normalize_text
from .service import CatalogService, search_products, get_product_detail, check_stock, find_analogs

__all__ = ["CatalogService", "normalize_product", "normalize_text", "search_products",
           "get_product_detail", "check_stock", "find_analogs"]
