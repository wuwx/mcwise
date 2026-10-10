"""工作流编排 —— 定义每个业务意图对应的麦当劳 MCP Tool 调用链。

本模块是 McWise 的"骨架"：它把自然语言意图翻译成一条确定的 Tool 调用序列，
上层 Agent（WorkBuddy Skill）按此序列调用 MCP，再把结果交给对应优化器求解。

这样做的价值：
1. **可审计**：每一次推荐都能回溯到具体的 Tool 调用；
2. **可裁剪**：用户只要"看看"，就不触发下单类 Tool；
3. **可降级**：某个 Tool 报错时有明确的替代路径。
"""

from __future__ import annotations

from typing import Any

__all__ = ["TOOL_CHAINS", "list_intents", "tool_chain"]

TOOL_CHAINS: dict[str, dict[str, Any]] = {
    "nutrition_plan": {
        "name": "营养配餐",
        "description": "按热量/蛋白质/脂肪/钠目标，从门店可售餐品中求解最优组合。",
        "steps": [
            {"tool": "now-time-info", "purpose": "锚定当前时间，判断早餐/正餐菜单"},
            {"tool": "query-nearby-stores", "purpose": "定位用户附近可下单门店"},
            {"tool": "query-store-coupons", "purpose": "获取该门店券，供省钱参谋联动"},
            {"tool": "query-meals", "purpose": "拉取门店可售餐品与分类"},
            {"tool": "query-meal-detail", "purpose": "获取套餐组成与可替换项"},
            {"tool": "list-nutrition-foods", "purpose": "获取餐品营养成分"},
            {"tool": "local:nutrition_planner.plan_meals", "purpose": "多目标优化求解最优组合"},
            {"tool": "calculate-price", "purpose": "用官方口径复核方案价格"},
        ],
    },
    "deal_optimize": {
        "name": "省钱购餐",
        "description": "在已选餐品/购物车基础上，求解最优用券与凑单方案。",
        "steps": [
            {"tool": "query-meals", "purpose": "拉取门店菜单用于挑选与凑单"},
            {"tool": "available-coupons", "purpose": "拉取麦麦省可领券"},
            {"tool": "auto-bind-coupons", "purpose": "一键领取全部可领券"},
            {"tool": "query-my-coupons", "purpose": "汇总账户券，避免重复计算"},
            {"tool": "query-store-coupons", "purpose": "补充门店专属券"},
            {"tool": "local:deal_strategist.optimize_deals", "purpose": "券组合与凑单最优解"},
            {"tool": "calculate-price", "purpose": "官方价格复核"},
        ],
    },
    "points_redeem": {
        "name": "积分管家",
        "description": "评估积分兑换效率，给出预算内最优兑换组合。",
        "steps": [
            {"tool": "query-my-account", "purpose": "查询可用/即将过期积分"},
            {"tool": "mall-points-products", "purpose": "拉取商城商品与积分价"},
            {"tool": "mall-product-detail", "purpose": "补充商品市场价值与有效期"},
            {"tool": "local:points_concierge.optimize_points", "purpose": "积分效率排序 + 0/1 背包"},
        ],
    },
    "campaign_digest": {
        "name": "活动雷达",
        "description": "按城市与兴趣推荐当月活动与可预约主题活动。",
        "steps": [
            {"tool": "campaign-calendar", "purpose": "当月营销活动日历"},
            {"tool": "query-party-city", "purpose": "主题活动可参与城市"},
            {"tool": "query-party-store", "purpose": "主题活动门店"},
            {"tool": "local:campaign_radar.rank_campaigns", "purpose": "兴趣匹配与排序"},
        ],
    },
    "one_tap_order": {
        "name": "一键成单",
        "description": "把已确认的方案落单，输出支付链接并跟踪订单。",
        "steps": [
            {"tool": "query-nearby-stores", "purpose": "确认门店"},
            {"tool": "delivery-query-addresses", "purpose": "外送场景选择收货地址"},
            {"tool": "calculate-price", "purpose": "最终价格与优惠确认"},
            {"tool": "create-order", "purpose": "创建订单并获取支付链接"},
            {"tool": "query-order", "purpose": "跟踪订单状态"},
        ],
        "guard": "下单类 Tool 必须在用户显式确认方案后调用，默认不自动执行。",
    },
}


def list_intents() -> list[dict[str, Any]]:
    """列出全部意图及其摘要。"""
    return [
        {"intent": key, "name": val["name"], "description": val["description"], "steps": len(val["steps"])}
        for key, val in TOOL_CHAINS.items()
    ]


def tool_chain(intent: str) -> dict[str, Any]:
    """返回某个意图的完整 Tool 调用链。"""
    if intent not in TOOL_CHAINS:
        raise KeyError(f"未知意图：{intent}，可选：{', '.join(TOOL_CHAINS)}")
    return TOOL_CHAINS[intent]
