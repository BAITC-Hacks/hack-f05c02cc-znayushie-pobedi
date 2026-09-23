"""Bridge between the teammate's CatalogService and the frontend /api contract."""
import json
import os
import re
from copy import deepcopy
from pathlib import Path

from ekt_catalog import CatalogService
from ekt_catalog.service import DEFAULT_PATH

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEMO_FILE = DATA_DIR / "products.json"
NORMALIZED_FILE = DEFAULT_PATH
LABELS = {"series": "Серия", "current_a": "Ток, А", "phase_count": "Фазы", "poles": "Полюса",
          "breaking_capacity_ka": "Отключающая способность, кА", "voltage_v": "Напряжение, В",
          "pole_configuration": "Конфигурация полюсов"}
DEMO_CRITICAL_PROPERTIES = {
    "Кабель": ("тип", "назначение", "жилы", "сечение", "материал", "класс гибкости", "номинальное напряжение"),
    "Автоматы": ("тип", "назначение", "полюса", "ток", "характеристика", "отключающая способность",
                 "номинальное напряжение", "тип тока", "монтаж", "ширина"),
}


class Catalog:
    def __init__(self, path: Path | None = None):
        if path is None:
            mode = os.getenv("CATALOG_MODE", "normalized")
            if mode not in {"normalized", "demo"}:
                raise ValueError("CATALOG_MODE must be normalized or demo")
            path = NORMALIZED_FILE if mode == "normalized" else DEMO_FILE
        rows = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        self.mode = "normalized" if rows and "schema_version" in rows[0] else "demo"
        self.source = "ekt-snapshot" if self.mode == "normalized" else "demo-json"
        self.service = CatalogService(path) if self.mode == "normalized" else None
        self.products = {str(row["id"]): self._adapt(row) for row in rows}
        if len(self.products) != len(rows):
            raise ValueError("Duplicate product ID")

    def _adapt(self, row):
        p = deepcopy(row)
        p["id"] = str(row["id"])
        if self.mode == "normalized":
            p.update(sku=row["article"], category=" / ".join(row["category_path"]), stock=row["quantity"],
                     price_kzt=row["price"] if row["currency"] == "KZT" else None,
                     requires_live_check=True, can_add_to_cart=False)
            p["properties"] = {label: row["features"][key] for key, label in LABELS.items()
                               if row["features"].get(key) is not None and row["field_status"].get(key) != "conflict"}
        else:
            p.update(article=row["sku"], price=row["price_kzt"], currency="KZT", quantity=row["stock"],
                     data_mode="demo", source_as_of=None, stock_status="demo", requires_live_check=False,
                     can_add_to_cart=True, stores=[], certificates=deepcopy(row.get("certificates", [])),
                     data_conflicts=[], warnings=[])
        return p

    def get(self, product_id):
        if self.service is not None:
            try:
                return self._adapt(self.service.get_product_detail(product_id))
            except (KeyError, ValueError):
                return None
        p = self.products.get(str(product_id))
        return deepcopy(p) if p is not None else None

    @staticmethod
    def _catalog_query(query):
        if not isinstance(query, str) or len(query) > 2000:
            raise ValueError("query must be a string of at most 2000 characters")
        # Strip a conversational wrapper ONLY when the entire tail is one identifier.
        # Extra constraints/negations remain intact for the service's strict parser.
        match = re.fullmatch(
            r"\s*(?:покажи|показать|покажите|добавь|добавить|положи|положить|аналоги?|найди\s+аналог|подбери\s+аналог|"
            r"похожие(?:\s+товары)?|похожий|замена|замену|цена|стоимость|наличие|характеристики|подробнее|сколько\s+стоит|"
            r"покажи\s+(?:цену|наличие|характеристики))"
            r"\s+(?:(?:для|на|товар|товара|артикул|id)\s+)?([\w-]+)\s*[?!.]?\s*", query, re.I)
        return match[1] if match else query

    def _demo_search(self, query, limit):
        # The demo uses a small deterministic parser. Every explicit constraint is
        # mandatory; unsupported text must never turn an electrical query into OR.
        working = query.casefold().replace("ё", "е")
        constraints = {}
        def number(value):
            match = re.search(r"\d+(?:[.,]\d+)?", str(value))
            return float(match[0].replace(",", ".")) if match else None
        def remember(key, value):
            if key in constraints and constraints[key] != value:
                raise ValueError("Укажите одно значение каждой характеристики для поиска.")
            constraints[key] = value
        def extract(pattern, callback):
            nonlocal working
            def replace(match):
                callback(match)
                return " "
            working = re.sub(pattern, replace, working)

        # Prices of these synthetic records are explicitly denominated in KZT.
        if re.search(r"(?:\b(?:usd|eur|rub|руб\w*|доллар\w*|евро)\b|[$€₽])", working):
            raise ValueError("В демо-каталоге цена задана в тенге. Укажите бюджет в KZT.")
        if re.search(r"\b(?:до|от|не\s+менее|не\s+более)\s*\d+(?:[.,]\d+)?\s*(?:а|a|ка|кa|в|мм)(?!\w)", working):
            raise ValueError("Укажите точный номинал; диапазоны электрических характеристик в демо не поддерживаются.")
        extract(r"(?:\b(?:цен[аеуы]|стоимост[ьи]|бюджет)\s*)?\b(?:до|не\s+дороже|дешевле)\s*(\d+(?:\s+\d{3})*(?:[.,]\d+)?)\s*(?:тенге|kzt|тг|₸)?",
                lambda m: remember("max_price", float(re.sub(r"\s+", "", m[1]).replace(",", "."))))
        if re.search(r"\b(?:не|без|кроме|исключая|not|except)\b", working):
            raise ValueError("Отрицательные условия пока не поддерживаются. Укажите требуемые характеристики прямо.")

        identifiers = set()
        for p in self.products.values():
            if re.search(r"(?<![\w-])" + re.escape(p["id"].casefold()) + r"(?![\w-])", working):
                identifiers.add(p["id"])
                working = working.replace(p["id"].casefold(), " ")
        skus = re.findall(r"(?<![\w-])demo-\d+(?![\w-])", working)
        if skus:
            known = {p["sku"].casefold(): p["id"] for p in self.products.values()}
            if any(sku not in known for sku in skus):
                return []
            identifiers.update(known[sku] for sku in skus)
            working = re.sub(r"(?<![\w-])demo-\d+(?![\w-])", " ", working)

        extract(r"(?<!\w)([bcdвсд])\s*(\d+)(?![\w.,])",
                lambda m: (remember("curve", {"в": "b", "с": "c", "д": "d"}.get(m[1], m[1])),
                           remember("current", float(m[2]))))
        extract(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(?:а|a|ампер(?:а|ов)?)(?!\w)",
                lambda m: remember("current", number(m[1])))
        extract(r"(?:характеристик\w*|крив\w*)\s*([bcdвсд])(?!\w)",
                lambda m: remember("curve", {"в": "b", "с": "c", "д": "d"}.get(m[1], m[1])))
        extract(r"(?<!\w)([1-4])\s*[pр](?!\w)", lambda m: remember("poles", int(m[1])))
        extract(r"(?<!\w)([1-4])\s*[- ]?полюс\w*", lambda m: remember("poles", int(m[1])))
        extract(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*к[aа](?!\w)",
                lambda m: remember("breaking_capacity", number(m[1])))
        extract(r"(?<!\d)(\d+)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)\s*(?:мм[²2]|мм\^2)?",
                lambda m: (remember("cores", int(m[1])), remember("section", number(m[2]))))
        extract(r"сечени\w*\s*(\d+(?:[.,]\d+)?)\s*(?:мм[²2]|мм\^2)?",
                lambda m: remember("section", number(m[1])))
        extract(r"(?<!\w)(\d+)\s*жил\w*", lambda m: remember("cores", int(m[1])))
        extract(r"\b(пвс|ввг(?:нг(?:\(а\))?)?(?:[- ]?ls)?)", lambda m: remember("cable_type", m[1].replace(" ", "")))
        extract(r"\b(?:в\s+наличии|на\s+складе)\b", lambda m: remember("available", True))
        # Requested cart quantities are not electrical constraints or product names.
        working = re.sub(r"\b(?:количество|кол-во)\s*[:=]?\s*\d+\b(?:\s*(?:шт\.?|штук[аи]?|метр\w*|м)(?!\w))?", " ", working)
        working = re.sub(r"(?<![\w.,])\d+\s*(?:шт\.?|штук[аи]?|метр\w*|м)(?!\w)", " ", working)
        stop = {"найди", "найдите", "покажи", "покажите", "показать", "подбери", "подберите", "нужен", "нужно", "нужна", "нужны",
                "мне", "товар", "товары", "товара", "артикул", "по", "на", "для", "с", "со", "и", "в", "а", "пожалуйста",
                "добавь", "добавить", "положи", "положить", "корзину", "характеристики", "наличие", "стоимость", "цена",
                "сколько", "стоит", "есть", "ли", "ток", "током", "ампер", "аналоги", "аналог", "похожие", "подробнее",
                "сертификат", "сертификаты", "сертификата"}
        terms = [t for t in re.findall(r"[\w-]+", working) if t not in stop]
        if not (terms or constraints or identifiers):
            return []

        found = []
        for p in self.products.values():
            if identifiers and p["id"] not in identifiers:
                continue
            props = p["properties"]
            actual = {"current": number(props.get("ток")), "poles": number(props.get("полюса")),
                      "curve": str(props.get("характеристика", "")).casefold(),
                      "breaking_capacity": number(props.get("отключающая способность")),
                      "cores": number(props.get("жилы")), "section": number(props.get("сечение"))}
            if any(actual[key] != value for key, value in constraints.items() if key in actual):
                continue
            if "cable_type" in constraints:
                kind = str(props.get("тип", "")).casefold()
                requested = constraints["cable_type"]
                if not kind.startswith("пвс" if requested.startswith("пвс") else "ввг"):
                    continue
                if any(part in requested and part not in kind for part in ("нг", "ls", "(а)")):
                    continue
            if "max_price" in constraints and (p.get("currency") != "KZT" or p.get("price_kzt") is None or p["price_kzt"] > constraints["max_price"]):
                continue
            if constraints.get("available") and (p.get("stock") is None or p["stock"] <= 0):
                continue
            haystack = json.dumps([p["id"], p["sku"], p["name"], p["category"], props], ensure_ascii=False).casefold().replace("ё", "е")
            if all(term in haystack for term in terms):
                found.append(p)
        found.sort(key=lambda p: p["id"])
        return deepcopy(found[:limit])

    def search_result(self, query="", limit=5, *, filters=None, include_uncertain=False):
        catalog_query = self._catalog_query(query)
        if self.service is not None:
            result = self.service.search_products(catalog_query, filters=filters, limit=limit,
                                                  include_uncertain=include_uncertain)
            return {**result, "query": query, "catalog_query": catalog_query,
                    "products": [self._adapt(p) for p in result["products"]], "source": self.source}
        if filters or include_uncertain:
            raise ValueError("Structured filters and uncertain matches require CATALOG_MODE=normalized")
        found = self._demo_search(query, len(self.products))
        return {"query": query, "products": found[:limit], "total": len(found),
                "count": len(found[:limit]), "source": self.source, "data_mode": "demo", "warnings": []}

    def search(self, query, limit=5):
        return self.search_result(query, limit)["products"]

    def check_stock(self, product_id, quantity=1, store_id=None):
        if type(quantity) is not int or quantity < 1:
            raise ValueError("Quantity must be a positive integer")
        if self.service is not None:
            result = self.service.check_stock(product_id, quantity, store_id=store_id)
            return {**result, "product_id": str(result["product_id"]), "quantity": quantity}
        p = self.get(product_id)
        if p is None:
            raise KeyError(product_id)
        stock = p["stock"] if store_id is None else None
        enough = None if stock is None else stock >= quantity
        return {"product_id": p["id"], "quantity": quantity, "store_id": store_id,
                "snapshot_quantity": stock, "enough_in_snapshot": enough, "currently_available": None,
                "requires_live_check": False, "cart_authorized": enough is True,
                "data_mode": "demo", "source_as_of": None}

    def alternative_result(self, product_id, limit=5):
        original = self.get(product_id)
        result = {"products": [], "status": "no_candidates",
                  "note": "Предварительное сравнение; взаимозаменяемость не подтверждена."}
        if original is None:
            return result
        if self.service is None:
            return self._demo_alternative_result(original, limit)
        raw = self.service.find_analogs(product_id, limit=limit)
        result.update(source_status=raw["status"], issues=raw.get("issues", []),
                      status="preliminary_candidates" if raw["status"] == "candidates_require_review" else raw["status"],
                      replacement_confirmed=raw["replacement_confirmed"], data_mode=raw["data_mode"])
        notes = {
            "blocked_source_conflict": "Подбор остановлен: в характеристиках исходного товара есть конфликт. Требуется уточнение.",
            "unsupported_category": "В модуле пока нет правил аналогов для этой категории.",
            "insufficient_source_specs": "Для подбора не хватает исходных характеристик тока или серии.",
        }
        result["note"] = notes.get(raw["status"], result["note"])
        for candidate in raw["candidates"]:
            p = self._adapt(candidate)
            comparison = candidate["comparison"]
            matches = {m["field"]: m["value"] for m in comparison["matching_fields"]}
            differences = {d["field"]: {"source": d["original"], "candidate": d["candidate"]} for d in comparison["differences"]}
            p["comparison"] = {**comparison, "matching_fields": matches, "differences": differences}
            p.update(replacement_confirmed=comparison["replacement_confirmed"],
                     needs_engineering_review=comparison["needs_engineering_review"],
                     needs_live_stock_check=comparison["needs_live_stock_check"])
            reason = "Совпадают: " + "; ".join(f"{LABELS.get(k, k)}: {v}" for k, v in matches.items()) + "."
            if differences:
                reason += " Отличаются: " + "; ".join(
                    f"{LABELS.get(k, k)}: {v['source']} → {v['candidate']}" for k, v in differences.items()) + "."
            p["reason"] = reason
            result["products"].append(p)
        result["count"] = len(result["products"])
        return result

    def _demo_alternative_result(self, original, limit):
        """Compare explicit synthetic specifications, never category alone."""
        result = {"products": [], "status": "no_candidates", "count": 0, "data_mode": "demo",
                  "replacement_confirmed": False,
                  "note": "Синтетические демо-данные. Совпадение указанных характеристик не подтверждает взаимозаменяемость."}
        critical = DEMO_CRITICAL_PROPERTIES.get(original["category"])
        if critical is None:
            result.update(status="unsupported_category", note="Для этой категории демо-товаров правила аналогов не заданы.")
            return result
        specs = original.get("properties", {})
        if any(specs.get(field) in (None, "") for field in critical):
            result.update(status="insufficient_source_specs", note="Для безопасного сравнения не хватает характеристик исходного товара.")
            return result
        for candidate in self.products.values():
            if (candidate["id"] == original["id"] or candidate["category"] != original["category"]
                    or not isinstance(candidate.get("stock"), (int, float)) or candidate["stock"] <= 0):
                continue
            other_specs = candidate.get("properties", {})
            # Additional provided specifications must also agree: silently dropping one
            # could accept a different cable function or protection-device variant.
            fields = tuple(dict.fromkeys((*critical, *specs, *other_specs)))
            if any(specs.get(field) in (None, "") or other_specs.get(field) in (None, "")
                   or str(specs[field]).strip().casefold() != str(other_specs[field]).strip().casefold()
                   for field in fields):
                continue
            p = self.get(candidate["id"])
            matches = {field: specs[field] for field in fields}
            p["comparison"] = {"matching_fields": matches, "differences": {},
                               "missing_checks": ["Требования конкретного проекта и условия монтажа",
                                                  "Документы и совместимость оборудования для реальной закупки"],
                               "replacement_confirmed": False, "needs_engineering_review": True,
                               "needs_live_stock_check": False}
            p.update(replacement_confirmed=False, needs_engineering_review=True, needs_live_stock_check=False)
            p["reason"] = ("Совпадают: " + "; ".join(f"{key}: {value}" for key, value in matches.items())
                           + f". Демо-остаток: {p['stock']} {p['unit']}. "
                           "Это предварительный кандидат по синтетическим данным; взаимозаменяемость не подтверждена.")
            result["products"].append(p)
            if len(result["products"]) >= limit:
                break
        result["count"] = len(result["products"])
        if result["products"]:
            result["status"] = "demo_candidates"
        return result

    def alternatives(self, product_id, limit=5):
        return self.alternative_result(product_id, limit)["products"]

