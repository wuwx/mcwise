"""活动雷达 —— 营销活动 / 主题活动的兴趣匹配与推荐排序。

输入：活动日历、用户所在城市、兴趣标签
输出：与用户最相关的活动清单（进行中优先），并给出预约 / 下单线索。

对应麦当劳 MCP Tools：
    - ``campaign-calendar``      当月营销活动日历
    - ``query-party-city``       主题活动可参与城市
    - ``query-party-store``      主题活动门店
    - ``query-partystore-date``  可预约日期
    - ``query-partystore-session`` 可预约场次
    - ``party-order-create``     主题活动下单
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from mcd_core import Campaign

__all__ = ["rank_campaigns", "render_campaigns"]

STATUS_WEIGHT = {"ongoing": 2.0, "upcoming": 1.6, "past": 0.8, "ended": 0.4}
INTEREST_WEIGHT = 1.5  # 每个命中兴趣的加权
CITY_MATCH_BONUS = 1.5  # 城市命中加权
CITY_MISS_PENALTY = 0.8  # 城市不匹配扣分


def _parse_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value)[:19], fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def rank_campaigns(payload: Mapping[str, Any], today: date | None = None) -> dict[str, Any]:
    """按"状态 + 兴趣匹配 + 城市命中 + 剩余天数"综合排序活动。"""
    today = today or date.today()
    campaigns = [Campaign.from_dict(x) for x in (payload.get("campaigns") or []) if isinstance(x, Mapping)]
    city = str(payload.get("city") or "").strip()
    interests = [str(t).lower() for t in (payload.get("interests") or [])]

    scored: list[dict[str, Any]] = []
    for c in campaigns:
        score = STATUS_WEIGHT.get(c.status, 1.0)

        # 兴趣匹配
        haystack = (c.name + " " + c.description + " " + " ".join(c.tags)).lower()
        matched = [kw for kw in interests if kw and kw in haystack]
        score += INTEREST_WEIGHT * len(matched)

        # 城市命中（未指定城市时不扣分）
        if city and c.city:
            if city in c.city or c.city in city:
                score += CITY_MATCH_BONUS
            else:
                score -= CITY_MISS_PENALTY

        # 时间紧迫度：7 天内开始的未来活动加权
        start = _parse_date(c.start)
        days_left = (start - today).days if start else None
        if days_left is not None and 0 <= days_left <= 7:
            score += 0.5

        scored.append(
            {
                "campaign": c.to_dict(),
                "score": round(score, 2),
                "matched_interests": matched,
                "days_until_start": days_left,
            }
        )

    scored.sort(key=lambda x: (-x["score"], x["days_until_start"] if x["days_until_start"] is not None else 999))
    top = scored[0] if scored else None
    return {
        "recommendations": scored,
        "summary": _summary(scored, city, interests),
        "top": top["campaign"]["name"] if top else None,
        "meta": {"campaign_count": len(campaigns), "city": city, "interests": interests, "today": today.isoformat()},
    }


def _summary(scored: Sequence[Mapping[str, Any]], city: str, interests: Sequence[str]) -> str:
    ongoing = [s for s in scored if s["campaign"]["status"] == "ongoing"]
    if not scored:
        return "暂无可推荐的活动。"
    head = scored[0]
    parts = [f"最推荐「{head['campaign']['name']}」"]
    if head["matched_interests"]:
        parts.append("命中兴趣：" + "、".join(head["matched_interests"]))
    parts.append(f"当前有 {len(ongoing)} 个进行中活动")
    if city:
        parts.append(f"已按城市「{city}」筛选")
    return "；".join(parts) + "。"


def render_campaigns(result: Mapping[str, Any]) -> str:
    lines = [str(result.get("summary", ""))]
    for r in result.get("recommendations", [])[:5]:
        c = r["campaign"]
        flag = {"ongoing": "进行中", "upcoming": "即将开始", "past": "已结束"}.get(c["status"], c["status"])
        lines.append(f"  · [{flag}] {c['name']}（{c.get('start', '')} ~ {c.get('end', '')}） 匹配度 {r['score']}")
    return "\n".join(lines)
