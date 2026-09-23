"""Offline catalog/search contract for a backend. No OpenAI key or API calls."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from .normalize import (BRANDS, CAPACITY_RE, CURRENT_RE, PHASE_RE, POLES_RE,
                        SERIES_RE, NUMBER, normalize_text, numeric)

DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "products.normalized.json"
FEATURE_KEYS = {"series", "current_a", "phase_count", "poles", "breaking_capacity_ka", "voltage_v"}
ALLOWED_FILTERS = FEATURE_KEYS | {"brand", "product_type", "article", "id", "max_price"}
ALIASES = {"current": "current_a", "phases": "phase_count", "type": "product_type", "product_id": "id", "breaking_capacity": "breaking_capacity_ka", "voltage": "voltage_v"}
NUMERIC_KEYS = {"current_a", "phase_count", "poles", "breaking_capacity_ka", "voltage_v", "max_price", "id"}
TYPE_ALIASES = {"автомат": "circuit_breaker", "автоматический выключатель": "circuit_breaker", "circuit breaker": "circuit_breaker", "дифавтомат": "rcbo", "диф.авт.": "rcbo", "реле": "relay", "коробка": "box"}
STOP_WORDS = {"мне", "нам", "нужен", "нужна", "нужно", "нужны", "ищу", "найди", "найдите", "покажи", "показать", "хочу", "купить", "пожалуйста", "на", "с", "для", "и", "в", "по", "товар", "товары", "есть", "ли", "у", "вас", "the", "a", "an", "i", "need"}
TOKEN_RE = re.compile(r"[\w]+(?:[.+-][\w]+)*", re.UNICODE)


def tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(normalize_text(text)))


def identity(value: Any) -> str:
    # The original article is preserved; an omitted terminal '_' is a search alias.
    return str(value or "").strip().casefold().rstrip("_")


def validated_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")
    result = {}
    for raw_key, value in filters.items():
        key = ALIASES.get(raw_key, raw_key)
        if key not in ALLOWED_FILTERS:
            raise ValueError(f"Unsupported filter: {raw_key}")
        if value is None:
            continue
        if key in NUMERIC_KEYS:
            parsed = numeric(value)
            if parsed is None or parsed < 0 or (key != "max_price" and parsed == 0):
                raise ValueError(f"{key} must be a positive finite number")
            if key in {"id", "phase_count", "poles"} and not isinstance(parsed, int):
                raise ValueError(f"{key} must be an integer")
            value = parsed
        else:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a nonempty string")
            value = value.strip()
            if key == "product_type":
                value = TYPE_ALIASES.get(value.casefold(), value.casefold())
        if key in result and result[key] != value:
            raise ValueError(f"Conflicting aliases for {key}")
        result[key] = value
    return result


def parse_simple_query(query: str) -> tuple[dict[str, Any], list[str]]:
    """Limited deterministic extraction. Complex intent belongs to the backend LLM."""
    if not isinstance(query, str) or len(query) > 2000:
        raise ValueError("query must be a string of at most 2000 characters")
    text = normalize_text(query)
    if re.search(r"\b(?:не|кроме|без|или)\b", text):
        raise ValueError("Запрос с отрицанием/альтернативой: передайте уточненные filters отдельно")
    if re.search(r"\d\s*(?:[-–…]|\.\.\.)\s*\d+\s*[aаvв](?!\w)", text):
        raise ValueError("Диапазон параметров пока не поддерживается; задайте точное значение")
    filters: dict[str, Any] = {}

    def consume(key: str, pattern: re.Pattern, converter) -> None:
        nonlocal text
        found = [converter(match) for match in pattern.finditer(text)]
        unique = list(dict.fromkeys(found))
        if len(unique) > 1:
            raise ValueError(f"Несколько значений {key}: {unique}; уточните запрос")
        if unique:
            filters[key] = unique[0]
            text = pattern.sub(" ", text)

    consume("brand", re.compile(r"\b(" + "|".join(BRANDS) + r")\b"), lambda m: BRANDS[m[1]])
    consume("series", SERIES_RE, lambda m: f"DRX{m[1]}")
    consume("breaking_capacity_ka", CAPACITY_RE, lambda m: numeric(m[1]))
    consume("current_a", CURRENT_RE, lambda m: numeric(m[1]))
    consume("phase_count", PHASE_RE, lambda m: int(m[1]))
    consume("poles", POLES_RE, lambda m: int(m[1]))
    consume("voltage_v", re.compile(r"(?<![\w.,])" + NUMBER + r"\s*[vв](?!\w)", re.I), lambda m: numeric(m[1]))
    for type_name, pattern in [
        ("rcbo", r"\b(?:дифавтомат|rcbo)\b|диф\.?\s*авт\.?"),
        ("circuit_breaker", r"\bавтомат(?:а|ы|ов)?\b"),
        ("relay", r"\bреле\b"), ("box", r"\bкоробк[аиу]\b"),
    ]:
        if re.search(pattern, text):
            if "product_type" in filters and filters["product_type"] != type_name:
                raise ValueError("Укажите один тип товара")
            filters["product_type"] = type_name
            text = re.sub(pattern, " ", text)
    reference = re.search(r"\b(?:артикул|арт\.?|sku)\s*[:#]?\s*([\w-]+)", text)
    if reference:
        filters["article"] = reference[1]
        text = text[:reference.start()] + " " + text[reference.end():]
    id_match = re.search(r"\bid\s*[:#]?\s*(\d+)\b", text)
    if id_match:
        filters["id"] = int(id_match[1])
        text = text[:id_match.start()] + " " + text[id_match.end():]
    remaining = sorted(word for word in tokens(text) if word not in STOP_WORDS)
    return filters, remaining


class CatalogService:
    """Instantiate once at backend startup; functions return copies, not shared state."""
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_PATH
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Normalized catalog not found: {self.path}") from exc
        if not isinstance(data, list):
            raise ValueError("Normalized catalog must be a JSON array")
        self._products: dict[int, dict[str, Any]] = {}
        self._tokens = {}
        for product in data:
            if not isinstance(product, dict) or product.get("schema_version") != "1.0":
                raise ValueError("Run normalize_product/build_catalog before loading raw data")
            pid = product.get("id")
            if isinstance(pid, bool) or not isinstance(pid, int) or pid in self._products:
                raise ValueError("Product ids must be unique integers")
            self._products[pid] = product
            self._tokens[pid] = tokens(" ".join(str(product.get(key) or "") for key in ["name", "article", "supplier_article", "name_reference"]))

    def __len__(self) -> int:
        return len(self._products)

    @staticmethod
    def _id(product_id: Any) -> int:
        value = numeric(product_id)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("product_id must be a positive integer")
        return value

    def _get(self, product_id: int) -> dict[str, Any]:
        pid = self._id(product_id)
        if pid not in self._products:
            raise KeyError(f"Product {pid} not found")
        return self._products[pid]

    def get_product_detail(self, product_id: int) -> dict[str, Any]:
        """Local normalized record, NOT a live call to EKT detail API."""
        return deepcopy(self._get(product_id))

    @staticmethod
    def _value(product: dict, field: str) -> Any:
        return product["features"].get(field) if field in FEATURE_KEYS else product.get(field)

    def search_products(self, query: str = "", *, filters: dict[str, Any] | None = None,
                        limit: int = 10, include_uncertain: bool = False) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("limit must be an integer from 1 to 50")
        if not isinstance(include_uncertain, bool):
            raise ValueError("include_uncertain must be boolean")
        supplied = validated_filters(filters)
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        # Try exact identifiers before parsing free text (retains leading zeros).
        exact_article = any(identity(query) in self._identifiers(p) for p in self._products.values()) if query.strip() else False
        if exact_article:
            inferred, terms = {"article": query.strip()}, []
        elif query.strip().isdigit() and int(query.strip()) in self._products:
            inferred, terms = {"id": int(query.strip())}, []
        else:
            inferred, terms = parse_simple_query(query)
        for field, value in supplied.items():
            if field in inferred and normalize_text(str(inferred[field])) != normalize_text(str(value)):
                raise ValueError(f"query and filters disagree for {field}")
            inferred[field] = value
        effective = validated_filters(inferred)
        results = []
        if effective or terms:
            for product in self._products.values():
                matched_filters = []
                review_fields = [item["field"] for item in product["data_conflicts"]]
                accepted = True
                for field, wanted in effective.items():
                    if field == "article":
                        ok = identity(wanted) in self._identifiers(product)
                    elif field == "max_price":
                        ok = product["price"] is not None and product["price"] <= wanted
                    else:
                        actual = self._value(product, field)
                        ok = actual is not None and (
                            normalize_text(actual) == normalize_text(wanted)
                            if isinstance(actual, str) and isinstance(wanted, str)
                            else actual == wanted
                        )
                        if not ok and field == "phase_count" and wanted in product["features"].get("phase_options", []):
                            ok = True
                        if not ok and include_uncertain and product["field_status"].get(field) == "conflict":
                            # An observed value may be shown only as an explicitly uncertain match.
                            ok = any(item["value"] == wanted for item in product["field_evidence"].get(field, []))
                    if not ok:
                        accepted = False
                        break
                    matched_filters.append(field)
                if accepted and all(term in self._tokens[product["id"]] for term in terms):
                    item = deepcopy(product)
                    item["match"] = {"status": "needs_review" if review_fields else "matched_source_fields",
                                     "matched_filters": matched_filters, "matched_terms": terms,
                                     "review_fields": review_fields}
                    results.append(item)
        # All filters must match. Price is only a tie-breaker in the supplied snapshot.
        results.sort(key=lambda p: (p["match"]["status"] == "needs_review", p["price"] is None,
                                    p["price"] if p["price"] is not None else 0, p["id"]))
        return {"query": query, "filters": effective, "terms": terms, "total": len(results),
                "count": len(results[:limit]), "products": results[:limit], "data_mode": "snapshot",
                "source_as_of": None, "warnings": ["not_live_price_or_stock"] + ([] if effective or terms else ["empty_query"])}

    @staticmethod
    def _identifiers(product: dict) -> set[str]:
        return {identity(product[k]) for k in ["article", "supplier_article", "name_reference"] if product.get(k)}

    def check_stock(self, product_id: int, quantity: int | float, *, store_id: int | None = None) -> dict[str, Any]:
        requested = numeric(quantity)
        if requested is None or requested <= 0:
            raise ValueError("quantity must be a positive finite number")
        product = self._get(product_id)
        stock = product["quantity"]
        if store_id is not None:
            sid = self._id(store_id)
            store = next((s for s in product["stores"] if s["id"] == sid), None)
            stock = store["quantity"] if store else None
        enough = None if stock is None else stock >= requested
        return {"product_id": product["id"], "store_id": store_id, "requested_quantity": requested,
                "snapshot_quantity": stock, "enough_in_snapshot": enough,
                "status": "unknown" if enough is None else ("snapshot_sufficient" if enough else "snapshot_insufficient"),
                "unit": product["unit"], "source_as_of": None, "data_mode": "snapshot",
                "currently_available": None, "requires_live_check": True, "cart_authorized": False,
                "warnings": ["snapshot_not_reservation", "sellable_stock_rules_not_provided"]}

    def find_analogs(self, product_id: int, *, limit: int = 5,
                     only_snapshot_available: bool = False) -> dict[str, Any]:
        """Preliminary candidates for circuit breakers, never compatibility approval."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("limit must be an integer from 1 to 50")
        if not isinstance(only_snapshot_available, bool):
            raise ValueError("only_snapshot_available must be boolean")
        original = self._get(product_id)
        envelope = {"product_id": original["id"], "candidates": [], "count": 0,
                    "replacement_confirmed": False, "data_mode": "snapshot"}
        if original["data_conflicts"]:
            return {**envelope, "status": "blocked_source_conflict", "issues": deepcopy(original["data_conflicts"])}
        if original["product_type"] != "circuit_breaker":
            return {**envelope, "status": "unsupported_category", "issues": ["Only circuit_breaker candidate rules are implemented"]}
        of = original["features"]
        if of["current_a"] is None or of["series"] is None:
            return {**envelope, "status": "insufficient_source_specs", "issues": ["current_a and series are required"]}
        candidates = []
        for candidate in self._products.values():
            cf = candidate["features"]
            if candidate["id"] == original["id"] or candidate["product_type"] != "circuit_breaker" or candidate["data_conflicts"]:
                continue
            if cf["current_a"] is None or cf["current_a"] != of["current_a"] or cf["series"] != of["series"]:
                continue
            if any(of[key] is not None and cf[key] is not None and of[key] != cf[key] for key in ["phase_count", "poles", "voltage_v"]):
                continue
            if of["breaking_capacity_ka"] is not None and cf["breaking_capacity_ka"] is not None and cf["breaking_capacity_ka"] < of["breaking_capacity_ka"]:
                continue
            if only_snapshot_available and (candidate["quantity"] is None or candidate["quantity"] <= 0):
                continue
            matches, differences, missing = [], [], []
            for key in ["current_a", "series", "phase_count", "poles", "voltage_v", "breaking_capacity_ka"]:
                before, after = of[key], cf[key]
                if before is None or after is None:
                    missing.append(key)
                elif before == after:
                    matches.append({"field": key, "value": before})
                else:
                    differences.append({"field": key, "original": before, "candidate": after})
            # These checks cannot be proved from the supplied name-only cards.
            missing.extend(["breaking_capacity_reference_conditions", "trip_characteristics", "dimensions_and_connections", "manufacturer_compatibility_confirmation"])
            item = deepcopy(candidate)
            item["comparison"] = {"matching_fields": matches, "differences": differences,
                                  "missing_checks": missing, "replacement_confirmed": False,
                                  "needs_engineering_review": True, "needs_live_stock_check": True}
            candidates.append(item)
        candidates.sort(key=lambda p: (p["price"] is None, p["price"] if p["price"] is not None else 0, p["id"]))
        return {**envelope, "candidates": candidates[:limit], "count": len(candidates[:limit]),
                "total": len(candidates), "status": "candidates_require_review" if candidates else "no_candidates",
                "issues": ["No percentage is a proof of interchangeability; no cart mutations"]}


@lru_cache(maxsize=1)
def _default() -> CatalogService:
    return CatalogService()


def search_products(query: str = "", **kwargs) -> dict[str, Any]:
    return _default().search_products(query, **kwargs)


def get_product_detail(product_id: int) -> dict[str, Any]:
    return _default().get_product_detail(product_id)


def check_stock(product_id: int, quantity: int | float, **kwargs) -> dict[str, Any]:
    return _default().check_stock(product_id, quantity, **kwargs)


def find_analogs(product_id: int, **kwargs) -> dict[str, Any]:
    return _default().find_analogs(product_id, **kwargs)
