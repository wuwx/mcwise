"""积分管家 —— 积分价值评估与最优兑换组合（0/1 背包）。

输入：用户积分余额、麦麦商城商品列表（积分价 / 现金价 / 市场价值）
输出：商品按"每 1000 积分等值人民币"排序、在积分预算内的最优兑换组合。

对应麦当劳 MCP Tools：
    - ``query-my-account``       查询积分账户（可用 / 累计 / 冻结 / 即将过期）
    - ``mall-points-products``   麦麦商城商品列表
    - ``mall-product-detail``    商品详情（有效期 / 说明）
    - ``mall-create-order``      兑换下单

算法说明：
    积分是"会过期的资产"，本模块以"每 1000 积分等值人民币"为效率指标排序，
    再用 0/1 背包在积分余额内求总价值最大的兑换组合。
    背包采用整数化（把积分按 ``unit`` 缩放）后的动态规划，兼顾精度与速度。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from mcd_core import MallProduct

__all__ = ["optimize_points", "render_points"]

DEFAULT_UNIT = 10  # 背包精度：每 10 积分作为一个格子
MAX_CAPACITY_CELLS = 200_000


def _account_balance(payload: Mapping[str, Any]) -> tuple[float, Mapping[str, Any]]:
    raw = payload.get("balance")
    if isinstance(raw, Mapping):
        return float(
            raw.get("available_points") or raw.get("available") or raw.get("points") or raw.get("balance") or 0.0
        ), raw
    return float(payload.get("available_points") or 0.0), {}


def _knapsack(products: Sequence[MallProduct], capacity: float, unit: int) -> tuple[list[MallProduct], float, float]:
    """0/1 背包：在 capacity 积分内最大化总市场价值。"""
    cap = int(capacity // unit)
    if cap <= 0:
        return [], 0.0, 0.0
    cap = min(cap, MAX_CAPACITY_CELLS)
    dp = [0.0] * (cap + 1)
    keep: list[list[int]] = [[] for _ in range(cap + 1)]
    for idx, p in enumerate(products):
        cost = int(p.points_cost // unit)
        if cost <= 0:
            continue
        value = p.market_value
        for c in range(cap, cost - 1, -1):
            cand = dp[c - cost] + value
            if cand > dp[c] + 1e-9:
                dp[c] = cand
                keep[c] = keep[c - cost] + [idx]
    best_value = dp[cap]
    indices = keep[cap]
    chosen = [products[i] for i in indices]
    used_points = sum(p.points_cost for p in chosen)
    return chosen, round(used_points, 2), round(best_value, 2)


def optimize_points(payload: Mapping[str, Any], unit: int = DEFAULT_UNIT) -> dict[str, Any]:
    """评估积分使用效率并给出最优兑换组合。

    Args:
        payload: 见 ``examples/points_input.json``。
        unit: 背包精度单位（积分），默认 10。

    Returns:
        含排行、最优组合与结论建议的字典。
    """
    balance, balance_raw = _account_balance(payload)
    products = [MallProduct.from_dict(x) for x in (payload.get("products") or []) if isinstance(x, Mapping)]
    convertible = [p for p in products if p.points_cost > 0]

    ranking = sorted(convertible, key=lambda p: -p.value_per_1000_points)
    chosen, used_points, total_value = _knapsack(convertible, balance, max(1, int(unit)))

    best_eff = ranking[0].value_per_1000_points if ranking else 0.0
    avg_eff = round(total_value / used_points * 1000.0, 2) if used_points > 0 else 0.0
    leftover = round(balance - used_points, 2)

    warnings: list[str] = []
    expiring = float(balance_raw.get("expiring_points") or balance_raw.get("expiringSoon") or 0.0)
    if expiring > 0:
        warnings.append(f"有 {expiring:.0f} 积分即将过期，建议优先消耗。")
    if ranking and best_eff >= 25:
        warnings.append("存在高效兑换项（每 1000 积分价值 ≥ ¥25），不建议用积分抽奖。")

    return {
        "balance": balance,
        "ranking": [p.to_dict() for p in ranking],
        "plan": {
            "items": [p.to_dict() for p in chosen],
            "used_points": used_points,
            "leftover_points": leftover,
            "total_market_value": total_value,
            "effective_value_per_1000": avg_eff,
            "best_single_efficiency": best_eff,
        },
        "warnings": warnings,
        "meta": {
            "product_count": len(products),
            "convertible_count": len(convertible),
            "knapsack_unit": unit,
        },
    }


def render_points(result: Mapping[str, Any]) -> str:
    plan = result.get("plan") or {}
    lines = [
        f"可用积分 {result.get('balance', 0):.0f} → 建议消耗 {plan.get('used_points', 0):.0f}，剩余 {plan.get('leftover_points', 0):.0f}",
        f"兑换后总价值约 ¥{plan.get('total_market_value', 0):.2f}（效率 ¥{plan.get('effective_value_per_1000', 0):.2f}/1000 积分）",
    ]
    for p in plan.get("items", []):
        lines.append(f"  · {p['name']}：{p['points_cost']:.0f} 积分 ≈ ¥{p['market_value']:.2f}")
    for w in result.get("warnings", []):
        lines.append(f"  ⚠ {w}")
    return "\n".join(lines)
