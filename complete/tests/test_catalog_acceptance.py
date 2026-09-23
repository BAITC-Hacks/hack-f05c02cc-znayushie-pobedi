"""Acceptance checks for trustworthy synthetic analog and document demonstrations."""
import json
from pathlib import Path

import pytest

from app.catalog import Catalog, DEMO_FILE, DEMO_CRITICAL_PROPERTIES


PVS = "demo-cable-pvs-3x2-5"
PVS_ALT = "demo-cable-pvs-3x2-5-alt"
BREAKER = "demo-breaker-16a"
BREAKER_ALT = "demo-breaker-16a-alt"


def test_stockout_cable_has_one_matching_available_candidate_and_reason():
    catalog = Catalog(DEMO_FILE)
    assert len(catalog.products) == 8
    assert catalog.get(PVS)["stock"] == 0
    result = catalog.alternative_result(PVS)
    assert result["status"] == "demo_candidates"
    assert [p["id"] for p in result["products"]] == [PVS_ALT]
    candidate = result["products"][0]
    assert candidate["stock"] > 0
    assert candidate["properties"] == catalog.get(PVS)["properties"]
    assert "ПВС" in candidate["reason"] and "2,5 мм²" in candidate["reason"]
    assert candidate["comparison"]["missing_checks"]
    assert candidate["replacement_confirmed"] is False
    assert candidate["needs_engineering_review"] is True
    assert result["replacement_confirmed"] is False


def test_breaker_candidate_matches_current_poles_curve_and_breaking_capacity():
    catalog = Catalog(DEMO_FILE)
    candidates = catalog.alternatives(BREAKER)
    assert [p["id"] for p in candidates] == [BREAKER_ALT]
    assert candidates[0]["properties"]["ток"] == "16 А"
    assert candidates[0]["properties"]["полюса"] == "1P"
    assert candidates[0]["properties"]["характеристика"] == "C"
    assert candidates[0]["properties"]["отключающая способность"] == "6 кА"


@pytest.mark.parametrize("original,candidate,category", [(PVS, PVS_ALT, "Кабель"), (BREAKER, BREAKER_ALT, "Автоматы")])
def test_each_missing_or_different_critical_property_blocks_a_candidate(original, candidate, category):
    for field in DEMO_CRITICAL_PROPERTIES[category]:
        catalog = Catalog(DEMO_FILE)
        del catalog.products[candidate]["properties"][field]
        assert catalog.alternatives(original) == [], field
        catalog = Catalog(DEMO_FILE)
        catalog.products[candidate]["properties"][field] = "другая характеристика"
        assert catalog.alternatives(original) == [], field
        catalog = Catalog(DEMO_FILE)
        del catalog.products[original]["properties"][field]
        assert catalog.alternative_result(original)["status"] == "insufficient_source_specs", field


def test_unknown_additional_property_and_zero_or_unknown_stock_never_match():
    catalog = Catalog(DEMO_FILE)
    catalog.products[PVS_ALT]["properties"]["дополнительная характеристика"] = "непроверено"
    assert catalog.alternatives(PVS) == []
    for stock in (0, None):
        catalog = Catalog(DEMO_FILE)
        catalog.products[PVS_ALT]["stock"] = stock
        assert catalog.alternatives(PVS) == []
    assert Catalog(DEMO_FILE).alternative_result("demo-contactor-25a")["status"] == "unsupported_category"


def test_certificate_fixture_survives_adaptation_and_is_explicitly_not_real():
    catalog = Catalog(DEMO_FILE)
    certificate = catalog.get(BREAKER)["certificates"][0]
    assert certificate["is_demo"] is True
    assert "НЕ сертификат" in certificate["title"]
    assert certificate["url"] == "/documents/demo-certificate.html"
    document = Path(__file__).resolve().parents[1] / "frontend/public/documents/demo-certificate.html"
    contents = document.read_text(encoding="utf-8")
    assert "НЕ сертификат соответствия" in contents
    assert "не имеет юридической силы" in contents
    # Callers cannot mutate the canonical fixture through a returned product.
    certificate["title"] = "modified"
    assert catalog.get(BREAKER)["certificates"][0]["title"] != "modified"


def test_demo_purchase_terms_have_an_explicit_minimum_and_demo_provenance():
    path = DEMO_FILE.with_name("purchase_terms.demo.json")
    terms = json.loads(path.read_text(encoding="utf-8"))
    assert terms["is_demo"] is True and terms["data_mode"] == "demo"
    assert "не условия продажи ekt.kz" in terms["notice"]
    assert terms["minimum_order"]["minimum_quantity_by_unit"] == {"шт": 1, "м": 1}
    assert terms["payment"]["answer"] and terms["delivery"]["answer"]


@pytest.mark.parametrize("query,ids", [
    ("автомат 16 А", {BREAKER, BREAKER_ALT}),
    ("Найди мне автомат на 16 ампер", {BREAKER, BREAKER_ALT}),
    ("C16 1P 6 кА", {BREAKER, BREAKER_ALT}),
    ("автомат С16 до 2000 тенге", {BREAKER}),
    ("C16 до 3 000 KZT", {BREAKER, BREAKER_ALT}),
    ("C16 не дороже 2000", {BREAKER}),
    ("ПВС 3x2.5", {PVS, PVS_ALT}),
    ("кабель ПВС 3×2,5 в наличии", {PVS_ALT}),
    ("ПВС сечением 2,5 мм² 3 жилы", {PVS, PVS_ALT}),
    ("DEMO-004", {BREAKER}),
    ("добавь DEMO-004 количество 2 шт", {BREAKER}),
    ("Покажи demo-breaker-16a", {BREAKER}),
    ("C16 до 1900", set()),
    ("C16 2P", set()),
    ("C16 4.5 кА", set()),
    ("B16", set()),
    ("ПВС 3x1.5", set()),
    ("DEMO-004 C10", set()),
    ("DEMO-999 автомат", set()),
    ("Legrand C16", set()),
])
def test_demo_search_enforces_explicit_specification_and_price_constraints(query, ids):
    assert {p["id"] for p in Catalog(DEMO_FILE).search(query)} == ids


@pytest.mark.parametrize("query", ["автомат не C10", "кабель кроме ПВС", "C16 до 3000 USD", "автомат ток до 16А", "C16 10А"])
def test_demo_search_requests_clarification_for_unsupported_or_conflicting_constraints(query):
    with pytest.raises(ValueError):
        Catalog(DEMO_FILE).search(query)


def test_budget_does_not_accept_unknown_currency_or_price():
    for field, value in [("currency", None), ("currency", "USD"), ("price_kzt", None)]:
        catalog = Catalog(DEMO_FILE)
        catalog.products[BREAKER][field] = value
        assert catalog.search("DEMO-004 до 3000") == []
