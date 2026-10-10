"""省钱参谋 —— 优惠券最优组合与凑单决策引擎。

输入：购物车、配送费、可用优惠券列表、可凑单商品列表
输出：最优用券方案、实际应付金额、以及"是否值得凑单"的量化建议。

对应麦当劳 MCP Tools：
    - ``query-store-coupons``  查询当前门店可用券
    - ``available-coupons``    麦麦省券列表
    - ``auto-bind-coupons``    一键领券后再进入本引擎求解
    - ``query-my-coupons``     我的优惠券
    - ``calculate-price``      用官方口径复核最终价格
    - ``query-meals``          获取可凑单商品

算法说明：
    1. 枚举券子集（受 ``max_coupons`` 与 ``exclusive_group`` 约束）；
    2. 对每个可行子集计算总优惠，取最优；
    3. 对"差一点就够门槛"的券做凑单扫描：遍历可凑单商品（含两件组合），
       若 ``优惠增量 - 凑单成本 > 0`` 则给出建议，并按净收益排序。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any

from mcd_core import CartLine, Coupon

__all__ = ["optimize_deals", "render_deal"]

MAX_COUPON_SUBSET = 8  # 参与枚举的最大券数，避免 2^n 爆炸


def _subtotal(lines: Sequence[CartLine]) -> float:
    return round(sum(line.subtotal for line in lines), 2)


def _best_subset(coupons: Sequence[Coupon], subtotal: float, max_coupons: int) -> tuple[list[Coupon], float]:
    """枚举 coupon 子集，返回 (最优子集, 总优惠)。"""
    pool = list(coupons[:MAX_COUPON_SUBSET])
    best: list[Coupon] = []
    best_saving = 0.0
    upper = max(0, min(int(max_coupons), len(pool)))
    for size in range(1, upper + 1):
        for subset in combinations(pool, size):
            # 同一互斥组内至多选一张
            groups: set[str] = set()
            conflict = False
            for c in subset:
                if c.exclusive_group in groups:
                    conflict = True
                    break
                groups.add(c.exclusive_group)
            if conflict:
                continue
            if not all(c.eligible(subtotal) for c in subset):
                continue
            saving = round(sum(c.saving_for(subtotal) for c in subset), 2)
            saving = min(saving, subtotal)
            if saving > best_saving + 1e-9:
                best_saving = saving
                best = list(subset)
    return best, best_saving


def optimize_deals(payload: Mapping[str, Any]) -> dict[str, Any]:
    """求解最优用券与凑单方案。

    Args:
        payload: 见 ``examples/deals_input.json``。

    Returns:
        含最优方案、备选方案、凑单建议的字典。
    """
    cart = [CartLine.from_dict(x) for x in (payload.get("cart") or []) if isinstance(x, Mapping)]
    coupons = [Coupon.from_dict(x) for x in (payload.get("coupons") or []) if isinstance(x, Mapping)]
    cross_sell = [CartLine.from_dict(x) for x in (payload.get("cross_sell") or []) if isinstance(x, Mapping)]
    delivery_fee = float(payload.get("delivery_fee") or 0.0)
    max_coupons = int(payload.get("max_coupons") or 1)

    subtotal = _subtotal(cart)
    if subtotal <= 0:
        return {
            "subtotal": 0.0,
            "best": None,
            "ranked_options": [],
            "upsell_suggestions": [],
            "meta": {"reason": "购物车为空"},
        }

    # ---- 1) 不限券数时也能给出"理论最优"参考 ----
    best, best_saving = _best_subset(coupons, subtotal, max_coupons)

    # ---- 2) 逐券排行，便于解释与人工替换 ----
    ranked: list[dict[str, Any]] = []
    for c in sorted(coupons, key=lambda x: -x.saving_for(subtotal)):
        s = c.saving_for(subtotal)
        ranked.append(
            {
                "coupon": c.to_dict(),
                "saving": round(s, 2),
                "eligible": c.eligible(subtotal),
                "gap_to_threshold": round(max(0.0, c.threshold - subtotal), 2),
            }
        )

    # ---- 3) 凑单扫描 ----
    upsell: list[dict[str, Any]] = []
    untriggered = [c for c in coupons if not c.eligible(subtotal) and c.threshold > 0]
    for c in untriggered:
        gap = round(c.threshold - subtotal, 2)
        # 考虑 1 件或 2 件凑单组合
        combos: list[tuple[CartLine, ...]] = [(x,) for x in cross_sell]
        combos += list(combinations(cross_sell, 2))
        for combo in combos:
            cost = round(sum(x.subtotal for x in combo), 2)
            if cost <= 0 or cost > gap + 12:  # 只关心"能刚好够门槛"的邻近凑单
                continue
            new_subtotal = round(subtotal + cost, 2)
            if not c.eligible(new_subtotal):
                continue
            _, new_saving = _best_subset(coupons, new_subtotal, max_coupons)
            net = round(new_saving - best_saving - cost, 2)
            if net > 0:
                upsell.append(
                    {
                        "coupon": c.to_dict(),
                        "add_items": [x.to_dict() for x in combo],
                        "add_cost": cost,
                        "new_subtotal": new_subtotal,
                        "new_saving": round(new_saving, 2),
                        "net_gain": net,
                    }
                )
    upsell.sort(key=lambda x: -x["net_gain"])
    # 同券只保留净收益最高的一条
    seen: set[str] = set()
    dedup_upsell: list[dict[str, Any]] = []
    for u in upsell:
        cid = u["coupon"]["coupon_id"]
        if cid in seen:
            continue
        seen.add(cid)
        dedup_upsell.append(u)

    payable = round(subtotal - best_saving + delivery_fee, 2)
    return {
        "subtotal": subtotal,
        "delivery_fee": round(delivery_fee, 2),
        "best": {
            "coupons": [c.to_dict() for c in best],
            "saving": round(best_saving, 2),
            "payable": payable,
            "explain": _explain(best, best_saving, subtotal, delivery_fee),
        },
        "ranked_options": ranked,
        "upsell_suggestions": dedup_upsell[:5],
        "meta": {
            "coupon_count": len(coupons),
            "max_coupons": max_coupons,
            "note": "使用官方 calculate-price 复核后再下单" if best else "当前购物车无可用券",
        },
    }


def _explain(best: Sequence[Coupon], saving: float, subtotal: float, delivery_fee: float) -> str:
    if not best:
        return "当前小计金额下没有满足门槛的优惠券。"
    names = "、".join(c.name for c in best)
    parts = [f"使用「{names}」"]
    parts.append(f"小计 ¥{subtotal:.2f} 减 ¥{saving:.2f}")
    if delivery_fee > 0:
        parts.append(f"另加配送费 ¥{delivery_fee:.2f}")
    parts.append(f"实付 ¥{subtotal - saving + delivery_fee:.2f}")
    return "，".join(parts) + "。"


def render_deal(result: Mapping[str, Any]) -> str:
    best = result.get("best") or {}
    lines = [
        f"小计 ¥{result.get('subtotal', 0):.2f} → 实付 ¥{best.get('payable', 0):.2f}（省 ¥{best.get('saving', 0):.2f}）"
    ]
    if best.get("explain"):
        lines.append("  " + str(best["explain"]))
    for u in result.get("upsell_suggestions", []):
        add = " + ".join(i["name"] for i in u["add_items"])
        lines.append(f"  ↘ 凑单建议：加「{add}」¥{u['add_cost']:.2f}，净省 ¥{u['net_gain']:.2f}")
    return "\n".join(lines)
