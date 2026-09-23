"""Conservative normalization of the supplied EKT snapshots; no network calls."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit

NUMBER = r"(\d+(?:[.,]\d+)?)"
CURRENT_RE = re.compile(r"(?<![\w.,])" + NUMBER + r"\s*(?:ампер(?:а|ов)?|amperes?|amps?|[аa])(?!\w)", re.I)
CAPACITY_RE = re.compile(r"(?<![\w.,])" + NUMBER + r"\s*(?:килоампер(?:а|ов)?|[кk]\s*[аa])(?!\w)", re.I)
PHASE_RE = re.compile(r"(?<!\w)([13])\s*(?:ф(?!\w)|-?фаз\w*|фазы?\b)", re.I)
POLES_RE = re.compile(r"(?<!\w)([1-4])\s*[pр](?!\w|\s*\+)", re.I)
SERIES_RE = re.compile(r"\bdrx\s*(\d+)\b", re.I)
BRANDS = {"legrand": "Legrand", "schneider": "Schneider Electric", "iek": "IEK", "ekf": "EKF", "abb": "ABB", "chint": "CHINT", "megalight": "MEGALIGHT", "opple": "OPPLE"}


def plain(text: Any) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).casefold().replace("ё", "е")


def normalize_text(text: str) -> str:
    """Search aliases only. Does not rewrite the stored product name/article."""
    value = plain(text)
    aliases = [
        (r"\bлегранд\b", "legrand"),
        (r"\bшнайдер(?:\s+электрик)?\b", "schneider"),
        (r"\bschneider\s+electric\b", "schneider"),
        (r"\bиэк\b", "iek"), (r"\bекф\b", "ekf"),
        (r"\bтрехфаз\w*\b", "3ф"), (r"\bоднофаз\w*\b", "1ф"),
        (r"\bавтоматический\s+выключатель\b", "автомат"),
        (r"\bcircuit\s+breaker\b", "автомат"),
        (r"\bав\b", "автомат"),  # whole word: never corrupts 'автомат'
    ]
    for pattern, replacement in aliases:
        value = re.sub(pattern, replacement, value)
    value = CAPACITY_RE.sub(lambda m: f"{m[1].replace(',', '.')}ka", value)
    value = CURRENT_RE.sub(lambda m: f"{m[1].replace(',', '.')}a", value)
    value = PHASE_RE.sub(lambda m: f"{m[1]}ф", value)
    value = POLES_RE.sub(lambda m: f"{m[1]}p", value)
    value = SERIES_RE.sub(lambda m: f"drx{m[1]}", value)
    return " ".join(value.split())


def numeric(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return int(parsed) if parsed == parsed.to_integral_value() else float(parsed)


def property_number(value: Any, unit_pattern: str = "") -> int | float | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*" + NUMBER + r"\s*(?:" + unit_pattern + r")?\s*", str(value), re.I)
    return numeric(match[1]) if match else None


def infer_type(name: str) -> str | None:
    text = plain(name)
    if re.search(r"диф\.?\s*авт|дифференциальный\s+автомат|\brcbo\b", text):
        return "rcbo"
    if re.search(r"\bав\b|автоматический выключатель|\bавтомат\b", text):
        return "circuit_breaker"
    if "реле" in text:
        return "relay"
    if "коробка" in text:
        return "box"
    if re.search(r"\bled\b|\bopple\b|светильник|лампа", text):
        return "lighting"
    return None


def normalize_product(raw: dict[str, Any], source_ids: list[str] | None = None) -> dict[str, Any]:
    """Keep unknowns null and expose contradictory observations instead of choosing."""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), int) or isinstance(raw["id"], bool):
        raise ValueError("Product must have an integer id")
    if not isinstance(raw.get("name"), str) or not raw["name"].strip():
        raise ValueError(f"Product {raw['id']} has no name")
    name = raw["name"]
    description = raw.get("description") or ""
    props = raw.get("properties") or {}
    if not isinstance(props, dict):
        raise ValueError("properties must be an object")
    product_type = infer_type(name)
    evidence: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []

    def observe(field: str, value: Any, source: str) -> None:
        if value is not None:
            evidence.setdefault(field, []).append({"value": value, "source": source})

    # Brands are taken only from name/properties, never guessed from URL/category.
    for key, label in BRANDS.items():
        if re.search(r"\b" + re.escape(key) + r"\b", normalize_text(name)):
            observe("brand", label, "name")
    if props.get("TORGOVAYA_MARKA"):
        brand = normalize_text(str(props["TORGOVAYA_MARKA"]))
        observe("brand", BRANDS.get(brand, str(props["TORGOVAYA_MARKA"]).strip()), "properties.TORGOVAYA_MARKA")

    for match in SERIES_RE.finditer(name):
        observe("series", f"DRX{match[1]}", "name")
    phase_options: list[int] = []
    if re.search(r"\b1\s*и\s*3\s*-?\s*фаз", plain(name)):
        phase_options = [1, 3]
    else:
        for match in PHASE_RE.finditer(normalize_text(name)):
            observe("phase_count", int(match[1]), "name")
    pole_configuration = None
    pole_config_match = re.search(r"(?<!\w)([1-4])\s*p\s*\+\s*n(?!\w)", plain(name))
    if pole_config_match:
        pole_configuration = f"{pole_config_match[1]}P+N"
    for match in POLES_RE.finditer(name):
        observe("poles", int(match[1]), "name")
    observe("poles", property_number(props.get("KOLICHESTVO_POLYUSOV")), "properties.KOLICHESTVO_POLYUSOV")

    # A relay contact current is NOT silently treated as a circuit-breaker rating.
    if product_type in {"circuit_breaker", "rcbo"}:
        for match in CURRENT_RE.finditer(name):
            observe("current_a", numeric(match[1]), "name")
        for match in re.finditer(r"номинальный\s+ток\s*:\s*" + NUMBER + r"\s*[аa](?!\w)", description, re.I):
            observe("current_a", numeric(match[1]), "description.Номинальный ток")
        observe("current_a", property_number(props.get("NOMINALNYY_TOK"), r"[аa]"), "properties.NOMINALNYY_TOK")
        for match in CAPACITY_RE.finditer(name):
            observe("breaking_capacity_ka", numeric(match[1]), "name")
        observe("breaking_capacity_ka", property_number(props.get("NOMINALNAYA_OTKLYUCHAYUSHCHAYA_SPOSOBNOST"), r"[кk][аa]"), "properties.NOMINALNAYA_OTKLYUCHAYUSHCHAYA_SPOSOBNOST")
    observe("voltage_v", property_number(props.get("NOMINALNOE_NAPRYAZHENIE"), r"[вv]"), "properties.NOMINALNOE_NAPRYAZHENIE")

    features: dict[str, Any] = {}
    field_status: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    fields = ["brand", "series", "current_a", "phase_count", "poles", "breaking_capacity_ka", "voltage_v"]
    for field in fields:
        observations = evidence.get(field, [])
        values = list(dict.fromkeys(item["value"] for item in observations))
        if len(values) == 1:
            features[field] = values[0]
            field_status[field] = "source_observed_not_verified"
        else:
            features[field] = None
            field_status[field] = "conflict" if values else "missing"
            if values:
                conflicts.append({"field": field, "values": values, "observations": observations})
                warnings.append(f"conflicting_{field}")
    features["phase_options"] = phase_options
    features["pole_configuration"] = pole_configuration

    # Supplier/category URLs are retained, not used as trusted numeric specifications.
    url = raw.get("url")
    path = [part for part in urlsplit(url or "").path.split("/") if part]
    category_path = path[1:-1] if path[:1] == ["catalog"] else []
    if url:
        slug = path[-1] if path else ""
        slug_currents = [numeric(m[1]) for m in re.finditer(r"(?:^|_)(\d+(?:\.\d+)?)a(?:_|$)", slug, re.I)]
        if features["current_a"] is not None and slug_currents and features["current_a"] not in slug_currents:
            warnings.append("url_slug_disagrees_with_name_current_not_used_as_spec")
    name_reference = re.match(r"^(\d[\d-]{3,})(?=\s)", name.strip())
    quantity = numeric(raw.get("quantity"))
    if quantity is not None and quantity < 0:
        warnings.append("negative_quantity_unusable")
        quantity = None
    stores = []
    for store in raw.get("stores") or []:
        q = numeric(store.get("quantity"))
        stores.append({"id": store.get("id"), "name": store.get("name"), "quantity": q if q is not None and q >= 0 else None, "sellable": None})
    if quantity is None:
        warnings.append("stock_not_provided")
    else:
        warnings.append("stock_is_snapshot_not_live")
    price = numeric(raw.get("price"))
    if price is not None and price < 0:
        warnings.append("negative_price_unusable")
        price = None
    if not raw.get("currency"):
        warnings.append("currency_not_provided")
    warnings.append("specifications_not_manufacturer_verified")
    return {
        "schema_version": "1.0", "id": raw["id"], "name": name,
        "article": raw.get("article"), "supplier_article": props.get("ARTIKULPOSTAVSHCHIKA"),
        "name_reference": name_reference[1] if name_reference else None,
        "product_type": product_type, "product_type_source": "name_rule" if product_type else None,
        "category_path": category_path, "category_source": "url_path" if category_path else None,
        "brand": features.pop("brand"), "features": features,
        "price": price, "currency": raw.get("currency"),
        "quantity": quantity, "unit": raw.get("unit"),
        "stock_status": "unknown" if quantity is None else ("snapshot_positive" if quantity > 0 else "snapshot_zero"),
        "stores": stores, "source_as_of": None, "data_mode": "snapshot",
        "description": raw.get("description"), "image": raw.get("image"),
        "url": url, "url_api_detail": raw.get("url_api_detail"),
        "certificates": [], "certificate_status": "not_provided_in_supplied_schema",
        "related_ids_raw": deepcopy(props.get("RECOMMEND", [])),
        "order_multiple_raw": props.get("KRATNOST_MIN"),
        "properties_raw": deepcopy(props), "offers_raw": deepcopy(raw.get("offers", [])),
        "field_status": field_status, "field_evidence": evidence,
        "data_conflicts": conflicts, "warnings": warnings,
        "source_ids": source_ids or ["caller_supplied_record"],
    }
