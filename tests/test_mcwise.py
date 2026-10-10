"""McWise 单元测试。

运行方式（仓库根目录）：
    python -m unittest discover -s tests -v
或：
    python tests/test_mcwise.py
"""

from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
EXAMPLES = os.path.join(ROOT, "examples")
sys.path.insert(0, SCRIPTS)

from campaign_radar import rank_campaigns
from deal_strategist import optimize_deals
from mcd_core import Coupon, MallProduct, Nutrition
from nutrition_planner import plan_meals
from points_concierge import optimize_points
from workflow import TOOL_CHAINS, list_intents, tool_chain


def load(name: str) -> dict:
    with open(os.path.join(EXAMPLES, name), encoding="utf-8") as fh:
        return json.load(fh)


class TestCore(unittest.TestCase):
    def test_nutrition_alias_parsing(self):
        n = Nutrition.from_dict({"热量": "550", "蛋白质(g)": 26, "脂肪": 30, "钠(mg)": 1000})
        self.assertEqual(n.energy_kcal, 550.0)
        self.assertEqual(n.protein_g, 26.0)
        self.assertEqual(n.sodium_mg, 1000.0)
        self.assertEqual(n.carb_g, 0.0)

    def test_coupon_saving(self):
        c = Coupon.from_dict({"coupon_id": "x", "kind": "threshold", "threshold": 40, "discount": 8})
        self.assertFalse(c.eligible(39.99))
        self.assertTrue(c.eligible(40))
        self.assertEqual(c.saving_for(57), 8.0)
        d = Coupon.from_dict({"coupon_id": "y", "kind": "discount", "discount": 0.8})
        self.assertEqual(d.saving_for(50), 10.0)

    def test_mall_product_efficiency(self):
        p = MallProduct.from_dict({"product_id": "1", "name": "券", "points_cost": 500, "market_value": 15})
        self.assertEqual(p.value_per_1000_points, 30.0)


class TestNutritionPlanner(unittest.TestCase):
    def setUp(self):
        self.result = plan_meals(load("nutrition_input.json"), top_n=3)

    def test_returns_plans(self):
        self.assertTrue(self.result["plans"])
        self.assertGreater(self.result["meta"]["evaluated_combinations"], 0)

    def test_top_plan_respects_hard_constraints(self):
        top = self.result["plans"][0]
        self.assertTrue(top["hard_constraints_ok"])
        kcal = top["total_nutrition"]["energy_kcal"]
        self.assertGreaterEqual(kcal, 440)
        self.assertLessEqual(kcal, 680)
        self.assertLessEqual(top["total_nutrition"]["sodium_mg"], 1300)

    def test_top_plan_is_grilled_chicken(self):
        names = [i["name"] for i in self.result["plans"][0]["items"]]
        self.assertIn("板烧鸡腿堡", names)

    def test_empty_candidates_degrades_gracefully(self):
        res = plan_meals({"target": {"energy_kcal": 500}, "candidates": []})
        self.assertEqual(res["plans"], [])
        self.assertIn("reason", res["meta"])

    def test_missing_category_reports_reason(self):
        res = plan_meals(
            {
                "structure": {"main": 1, "drink": 1},
                "candidates": [{"code": "a", "name": "堡", "category": "main", "price": 10}],
            }
        )
        self.assertEqual(res["plans"], [])
        self.assertIn("drink", res["meta"]["reason"])


class TestDealStrategist(unittest.TestCase):
    def setUp(self):
        self.result = optimize_deals(load("deals_input.json"))

    def test_subtotal(self):
        self.assertAlmostEqual(self.result["subtotal"], 57.0, places=2)

    def test_best_coupon_choice(self):
        best = self.result["best"]
        self.assertEqual(best["saving"], 8.0)
        self.assertEqual(best["coupons"][0]["coupon_id"], "C39")
        self.assertAlmostEqual(best["payable"], 58.0, places=2)

    def test_upsell_suggestion(self):
        upsell = self.result["upsell_suggestions"]
        self.assertTrue(upsell)
        self.assertEqual(upsell[0]["coupon"]["coupon_id"], "C59")
        self.assertEqual(upsell[0]["add_items"][0]["name"], "苹果片")
        self.assertAlmostEqual(upsell[0]["net_gain"], 4.0, places=2)

    def test_empty_cart(self):
        res = optimize_deals({"cart": []})
        self.assertIsNone(res["best"])


class TestPointsConcierge(unittest.TestCase):
    def setUp(self):
        self.result = optimize_points(load("points_input.json"))

    def test_ranking_is_sorted(self):
        eff = [p["value_per_1000_points"] for p in self.result["ranking"]]
        self.assertEqual(eff, sorted(eff, reverse=True))
        self.assertEqual(eff[0], 30.0)

    def test_knapsack_plan(self):
        plan = self.result["plan"]
        self.assertLessEqual(plan["used_points"], self.result["balance"])
        self.assertGreaterEqual(plan["total_market_value"], 70.0)
        self.assertGreater(plan["effective_value_per_1000"], 22.0)

    def test_expiring_warning(self):
        self.assertTrue(any("过期" in w for w in self.result["warnings"]))

    def test_zero_balance(self):
        res = optimize_points({"balance": {"available_points": 0}, "products": load("points_input.json")["products"]})
        self.assertEqual(res["plan"]["items"], [])


class TestCampaignRadar(unittest.TestCase):
    def setUp(self):
        self.result = rank_campaigns(load("campaigns_input.json"), today=__import__("datetime").date(2026, 10, 10))

    def test_recommendations_present(self):
        self.assertTrue(self.result["recommendations"])
        scores = [r["score"] for r in self.result["recommendations"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_city_boost(self):
        top_names = [r["campaign"]["name"] for r in self.result["recommendations"][:3]]
        self.assertIn("麦当劳生日派对季", top_names)


class TestWorkflow(unittest.TestCase):
    def test_intents(self):
        intents = {i["intent"] for i in list_intents()}
        self.assertEqual(
            intents,
            {"nutrition_plan", "deal_optimize", "points_redeem", "campaign_digest", "one_tap_order"},
        )

    def test_chain_has_mcp_tools(self):
        chain = tool_chain("nutrition_plan")
        tools = [s["tool"] for s in chain["steps"]]
        self.assertIn("query-meals", tools)
        self.assertIn("list-nutrition-foods", tools)

    def test_unknown_intent(self):
        with self.assertRaises(KeyError):
            tool_chain("nope")

    def test_order_chain_is_guarded(self):
        self.assertIn("guard", TOOL_CHAINS["one_tap_order"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
