import json
import unittest
from ekt_catalog import CatalogService, normalize_product, normalize_text
from ekt_catalog.service import parse_simple_query

class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = CatalogService()

    def ids(self, query="", **kwargs):
        return [p["id"] for p in self.catalog.search_products(query, **kwargs)["products"]]

    def test_count(self):
        self.assertEqual(len(self.catalog), 40)

    def test_current_aliases(self):
        for query in ["Legrand 160A", "160а Legrand", "легранд 160 ампер", "Мне нужен трехфазный автомат Legrand на 160 ампер"]:
            with self.subTest(query=query):
                self.assertEqual(self.ids(query), [515288])

    def test_conflicted_record_is_optional(self):
        found=self.catalog.search_products("Legrand 160A", include_uncertain=True)["products"]
        self.assertEqual([p["id"] for p in found], [515288, 515291])
        self.assertEqual(found[1]["match"]["status"], "needs_review")

    def test_unknown_not_zero(self):
        self.assertIsNone(self.catalog.get_product_detail(515288)["quantity"])
        result=self.catalog.check_stock(515288, 1)
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["enough_in_snapshot"])

    def test_stock_snapshot_total(self):
        result=self.catalog.check_stock(515291, 23)
        self.assertTrue(result["enough_in_snapshot"])
        self.assertTrue(result["requires_live_check"])
        self.assertFalse(result["cart_authorized"])
        self.assertIsNone(result["currently_available"])

    def test_stock_store(self):
        self.assertTrue(self.catalog.check_stock(515291, 5, store_id=13)["enough_in_snapshot"])
        self.assertFalse(self.catalog.check_stock(515291, 6, store_id=13)["enough_in_snapshot"])
        self.assertEqual(self.catalog.check_stock(515291, 1, store_id=999)["status"], "unknown")

    def test_stock_invalid_quantities(self):
        for value in [0, -1, True, "text", float("nan"), float("inf")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.catalog.check_stock(515291, value)

    def test_identifiers(self):
        for query in ["200300285_", "200300285", "027228", "515291", "артикул 200300285_", "id 515291"]:
            self.assertEqual(self.ids(query), [515291], query)
        self.assertEqual(self.ids("RM35BA10"), [35604])
        self.assertEqual(self.ids("ярп4520"), [45357])

    def test_nonexistent_identifiers(self):
        self.assertEqual(self.ids("артикул 99999999"), [])
        self.assertEqual(self.ids("99999999"), [])

    def test_exact_25_not_125_or_250(self):
        self.assertEqual(self.ids("Legrand 25A"), [515282])
        self.assertEqual(self.ids("Legrand 125А"), [515290, 515287])
        self.assertEqual(self.ids("Legrand 250A"), [515286, 515293])

    def test_phase_is_not_poles(self):
        self.assertEqual(self.catalog.get_product_detail(515288)["features"]["phase_count"], 3)
        self.assertIsNone(self.catalog.get_product_detail(515288)["features"]["poles"])
        self.assertEqual(self.ids("Legrand 160A 3P"), [])
        self.assertEqual(self.ids("Legrand 160A 3ф"), [515288])

    def test_rcbo_not_plain_breaker(self):
        self.assertEqual(self.ids("дифавтомат 16A"), [25397])
        self.assertEqual(self.ids("автомат 16A"), [])
        self.assertEqual(self.catalog.get_product_detail(25397)["features"]["pole_configuration"], "1P+N")

    def test_milliamps_not_nominal_current(self):
        p=normalize_product({"id":1,"name":"Диф.авт. 1p+N 16А (30мА)"})
        self.assertEqual(p["features"]["current_a"], 16)

    def test_kiloamps_not_current(self):
        p=normalize_product({"id":1,"name":"АВ 3ф 160A 18кА Legrand"})
        self.assertEqual(p["features"]["current_a"], 160)
        self.assertEqual(p["features"]["breaking_capacity_ka"], 18)

    def test_decimal_kiloamps(self):
        p=normalize_product({"id":1,"name":"АВ 16А 4,5 kA"})
        self.assertEqual(p["features"]["breaking_capacity_ka"], 4.5)

    def test_conflict_is_preserved(self):
        p=self.catalog.get_product_detail(515291)
        self.assertIsNone(p["features"]["current_a"])
        self.assertEqual(p["data_conflicts"][0]["values"], [160,250])
        self.assertEqual(p["properties_raw"]["NOMINALNYY_TOK"], "250 А")

    def test_type_word_not_corrupted(self):
        self.assertEqual(normalize_text("автомат"), "автомат")
        self.assertEqual(normalize_text("АВ"), "автомат")
        self.assertEqual(normalize_text("килоампер"), "килоампер")

    def test_no_missing_brand_inference(self):
        p=self.catalog.get_product_detail(35604)
        self.assertIsNone(p["brand"])
        self.assertIsNone(p["features"]["current_a"])
        self.assertEqual(p["features"]["phase_options"], [1,3])

    def test_currency_unknown(self):
        self.assertIsNone(self.catalog.get_product_detail(515291)["currency"])

    def test_raw_category_preserved(self):
        p=self.catalog.get_product_detail(58379)
        self.assertIn("ustroystva_plavnogo_puska_iek_", p["category_path"])
        self.assertIsNone(p["product_type"])

    def test_url_not_authoritative_spec(self):
        p=self.catalog.get_product_detail(515281)
        self.assertEqual(p["features"]["current_a"],100)
        self.assertIn("url_slug_disagrees_with_name_current_not_used_as_spec",p["warnings"])

    def test_filters_from_existing_ai(self):
        self.assertEqual(self.ids(filters={"brand":"Legrand", "current":160, "phases":3, "series":None, "product_type":"автомат"}), [515288])

    def test_no_unknown_filter_ignored(self):
        with self.assertRaises(ValueError): self.catalog.search_products(filters={"made_up_filter":1})

    def test_conflicting_filters_fail(self):
        with self.assertRaises(ValueError): self.catalog.search_products("Legrand 160A", filters={"current":200})

    def test_empty_query(self):
        self.assertEqual(self.ids("   "), [])

    def test_irrelevant_search(self):
        self.assertEqual(self.ids("несуществующий_товар"), [])
        self.assertEqual(self.ids("ABB 999A"), [])

    def test_ambiguous_query_rejected(self):
        for query in ["Legrand 160A или 200A", "не Legrand", "Legrand 125-160A", "160A 200A"]:
            with self.subTest(query=query), self.assertRaises(ValueError): self.catalog.search_products(query)

    def test_deep_copy(self):
        p=self.catalog.get_product_detail(515291)
        p["features"]["current_a"]=999
        self.assertIsNone(self.catalog.get_product_detail(515291)["features"]["current_a"])

    def test_analog_conflict_blocks(self):
        r=self.catalog.find_analogs(515291)
        self.assertEqual(r["status"], "blocked_source_conflict")
        self.assertEqual(r["candidates"], [])

    def test_analog_hard_current(self):
        r=self.catalog.find_analogs(515290)
        self.assertEqual([p["id"] for p in r["candidates"]], [515287])
        self.assertFalse(r["replacement_confirmed"])
        self.assertTrue(r["candidates"][0]["comparison"]["needs_engineering_review"])

    def test_analog_lower_ka_rejected(self):
        self.assertEqual(self.catalog.find_analogs(515287)["candidates"], [])

    def test_analog_stock_missing_not_available(self):
        self.assertEqual(self.catalog.find_analogs(515290,only_snapshot_available=True)["candidates"], [])

    def test_unsupported_analog_category(self):
        self.assertEqual(self.catalog.find_analogs(35604)["status"], "unsupported_category")

    def test_unknown_id(self):
        with self.assertRaises(KeyError): self.catalog.get_product_detail(99999999)

    def test_no_credentials_needed(self):
        json.dumps(self.catalog.search_products("Legrand 160A"), ensure_ascii=False, allow_nan=False)

if __name__ == "__main__":
    unittest.main()
