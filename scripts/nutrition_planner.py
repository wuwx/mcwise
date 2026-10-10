"""营养配餐官 —— 多目标营养配餐优化器。

输入：用户营养目标（热量 / 蛋白质 / 脂肪 / 碳水 / 钠）+ 门店可售餐品清单（含营养数据）
输出：满足目标的最优 N 套组合方案，并给出偏差解释。

对应麦当劳 MCP Tools：
    - ``list-nutrition-foods``  获取餐品营养成分
    - ``query-meals``           获取当前门店可售餐品（分类 / 编码）
    - ``query-meal-detail``     获取套餐组成，支持替换项
    - ``calculate-price``       计算方案实际价格

算法说明：
    1. 按餐品分类（main / side / drink / dessert）分组；
    2. 依据 ``structure`` 指定的每类件数做组合枚举（笛卡尔积）；
    3. 对每个组合计算"加权相对偏差"作为适应度，越小越优；
    4. 支持硬约束区间（min / max）做前置过滤，过滤后无解时自动降级为软约束；
    5. 同分时优先价格更低者。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations, product
from typing import Any

from mcd_core import MenuItem, Nutrition

__all__ = ["plan_meals", "render_plan"]

NUTRIENT_LABELS = {
    "energy_kcal": ("热量", "kcal"),
    "protein_g": ("蛋白质", "g"),
    "fat_g": ("脂肪", "g"),
    "carb_g": ("碳水", "g"),
    "sodium_mg": ("钠", "mg"),
    "calcium_mg": ("钙", "mg"),
}

MAX_GROUP_SIZE = 40  # 每个分类参与枚举的候选上限，防止组合爆炸
MAX_COMBOS = 500_000  # 总枚举上限保护


def _weighted_deviation(
    total: Nutrition, target: Mapping[str, float], weights: Mapping[str, float]
) -> tuple[float, dict[str, float]]:
    """计算加权相对偏差（越小越接近目标），并返回各营养素偏差明细。"""
    score = 0.0
    detail: dict[str, float] = {}
    for key, tgt in target.items():
        tgt = float(tgt)
        if tgt <= 0:
            continue
        actual = total.get(key)
        rel = (actual - tgt) / tgt
        detail[key] = round(rel * 100.0, 1)  # 百分比偏差
        w = float(weights.get(key, 1.0))
        score += w * rel * rel
    return score, detail


def _satisfies(total: Nutrition, constraints: Mapping[str, Mapping[str, float]]) -> bool:
    for key, bounds in (constraints or {}).items():
        if not isinstance(bounds, Mapping):
            continue
        value = total.get(key)
        if "min" in bounds and value + 1e-9 < float(bounds["min"]):
            return False
        if "max" in bounds and value - 1e-9 > float(bounds["max"]):
            return False
    return True


def _sum_nutrition(items: Sequence[MenuItem]) -> Nutrition:
    total = Nutrition()
    for it in items:
        total.energy_kcal += it.nutrition.energy_kcal
        total.protein_g += it.nutrition.protein_g
        total.fat_g += it.nutrition.fat_g
        total.carb_g += it.nutrition.carb_g
        total.sodium_mg += it.nutrition.sodium_mg
        total.calcium_mg += it.nutrition.calcium_mg
    return total


def _candidates_for(category: str, pool: Sequence[MenuItem], count: int, rank_key) -> list[tuple[MenuItem, ...]]:
    """在单个分类内选出 ``count`` 件餐品的所有组合（带规模保护）。"""
    items = sorted(pool, key=rank_key)[:MAX_GROUP_SIZE]
    if count > len(items):
        return []
    if count == len(items):
        return [tuple(items)]
    return list(combinations(items, count))


def plan_meals(payload: Mapping[str, Any], top_n: int = 3) -> dict[str, Any]:
    """执行营养配餐优化。

    Args:
        payload: 结构化输入，字段说明见 ``examples/nutrition_input.json``。
        top_n: 返回前 N 套方案。

    Returns:
        含 ``plans``（有序方案列表）与 ``meta``（求解信息）的字典。
    """
    target: dict[str, float] = dict(payload.get("target") or {})
    weights: dict[str, float] = dict(payload.get("weights") or {})
    constraints: dict[str, Any] = dict(payload.get("constraints") or {})
    structure: dict[str, int] = dict(payload.get("structure") or {"main": 1, "side": 1, "drink": 1})

    raw_items = payload.get("candidates") or []
    items = [MenuItem.from_dict(x) for x in raw_items if isinstance(x, Mapping)]
    if not items:
        return {"plans": [], "meta": {"reason": "候选餐品为空，请先调用 query-meals / list-nutrition-foods"}}

    pool: dict[str, list[MenuItem]] = {}
    for it in items:
        pool.setdefault(it.category or "other", []).append(it)

    # 分类内先按"单位价格带来的营养密度"粗略排序，兼顾价格与数据完整性
    def rank_key(it: MenuItem):
        return (it.price, -it.nutrition.protein_g)

    categories = [c for c, n in structure.items() if int(n) > 0]
    missing = [c for c in categories if not pool.get(c)]
    if missing:
        return {"plans": [], "meta": {"reason": f"缺少分类候选：{', '.join(missing)}，无法构成完整组合"}}

    per_category: list[list[tuple[MenuItem, ...]]] = []
    total_combos = 1
    for cat in categories:
        combos = _candidates_for(cat, pool[cat], int(structure[cat]), rank_key)
        if not combos:
            return {"plans": [], "meta": {"reason": f"分类 {cat} 可选餐品不足 {structure[cat]} 件"}}
        per_category.append(combos)
        total_combos *= len(combos)
        if total_combos > MAX_COMBOS:
            return {"plans": [], "meta": {"reason": f"组合空间过大（{total_combos}），请收敛候选餐品范围"}}

    scored: list[dict[str, Any]] = []
    feasible_count = 0
    for combo in product(*per_category):
        chosen = [it for group in combo for it in group]
        total = _sum_nutrition(chosen)
        hard_ok = _satisfies(total, constraints)
        score, detail = _weighted_deviation(total, target, weights)
        if hard_ok:
            feasible_count += 1
        # 硬约束不满足者排到后面，但仍保留作为降级备选
        penalty = score if hard_ok else score + 100.0
        scored.append(
            {
                "items": [it.to_dict() for it in chosen],
                "total_price": round(sum(it.price for it in chosen), 2),
                "total_nutrition": total.to_dict(),
                "deviation_pct": detail,
                "score": round(score, 4),
                "hard_constraints_ok": hard_ok,
                "_penalty": penalty,
            }
        )

    scored.sort(key=lambda x: (not x["hard_constraints_ok"], x["_penalty"], x["total_price"]))
    plans = scored[: max(1, int(top_n))]
    for p in plans:
        p.pop("_penalty", None)

    return {
        "plans": plans,
        "meta": {
            "evaluated_combinations": len(scored),
            "feasible_combinations": feasible_count,
            "structure": structure,
            "degraded": feasible_count == 0,
            "note": "无组合满足全部硬约束，已降级为软约束最优解" if feasible_count == 0 else "已按硬约束过滤",
        },
    }


def render_plan(plan: Mapping[str, Any]) -> str:
    """把单套方案渲染为人类可读文本。"""
    lines = [f"¥{plan.get('total_price', 0):.2f}  ·  " + " + ".join(i.get("name", "") for i in plan.get("items", []))]
    total = plan.get("total_nutrition", {})
    facts = " | ".join(
        f"{NUTRIENT_LABELS[k][0]} {total.get(k, 0):.0f}{NUTRIENT_LABELS[k][1]}" for k in NUTRIENT_LABELS if total.get(k)
    )
    lines.append(f"  营养：{facts}")
    dev = plan.get("deviation_pct") or {}
    if dev:
        lines.append("  偏差：" + "，".join(f"{NUTRIENT_LABELS.get(k, (k, ''))[0]} {v:+.1f}%" for k, v in dev.items()))
    return "\n".join(lines)
