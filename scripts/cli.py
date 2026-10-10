#!/usr/bin/env python
"""McWise 命令行入口。

用法示例：
    python scripts/cli.py nutrition --input examples/nutrition_input.json
    python scripts/cli.py deals     --input examples/deals_input.json
    python scripts/cli.py points    --input examples/points_input.json
    python scripts/cli.py campaigns --input examples/campaigns_input.json
    python scripts/cli.py chain nutrition_plan
    python scripts/cli.py intents
    cat payload.json | python scripts/cli.py nutrition --stdin
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from campaign_radar import rank_campaigns, render_campaigns
from deal_strategist import optimize_deals, render_deal
from nutrition_planner import plan_meals, render_plan
from points_concierge import optimize_points, render_points
from workflow import list_intents, tool_chain


def _load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "stdin", False):
        return json.load(sys.stdin)
    if getattr(args, "input", None):
        with open(args.input, encoding="utf-8") as fh:
            return json.load(fh)
    raise SystemExit("请通过 --input <file> 或 --stdin 提供 JSON 输入")


def _emit(result: dict[str, Any], rendered: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(rendered)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcwise", description="麦麦智囊 McWise — 麦当劳 MCP 智能决策引擎")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("nutrition", "营养配餐优化"),
        ("deals", "优惠券与凑单优化"),
        ("points", "积分兑换优化"),
        ("campaigns", "活动推荐排序"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--input", help="输入 JSON 文件路径")
        p.add_argument("--stdin", action="store_true", help="从标准输入读取 JSON")
        p.add_argument("--json", action="store_true", help="输出完整 JSON（默认输出人类可读摘要）")
        if name == "nutrition":
            p.add_argument("--top", type=int, default=3, help="返回方案数量")
        if name == "points":
            p.add_argument("--unit", type=int, default=10, help="背包精度（积分）")

    p_chain = sub.add_parser("chain", help="打印某意图的麦当劳 MCP Tool 调用链")
    p_chain.add_argument("intent", help="意图标识，如 nutrition_plan")

    sub.add_parser("intents", help="列出全部业务意图")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "intents":
        print(json.dumps(list_intents(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "chain":
        print(json.dumps(tool_chain(args.intent), ensure_ascii=False, indent=2))
        return 0

    payload = _load_payload(args)

    if args.command == "nutrition":
        result = plan_meals(payload, top_n=getattr(args, "top", 3))
        rendered = "\n".join(render_plan(p) for p in result.get("plans", [])) or result["meta"].get("reason", "")
    elif args.command == "deals":
        result = optimize_deals(payload)
        rendered = render_deal(result)
    elif args.command == "points":
        result = optimize_points(payload, unit=getattr(args, "unit", 10))
        rendered = render_points(result)
    elif args.command == "campaigns":
        result = rank_campaigns(payload)
        rendered = render_campaigns(result)
    else:  # pragma: no cover - argparse 已保证不会到达
        raise SystemExit(f"未知命令：{args.command}")

    _emit(result, rendered, getattr(args, "json", False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
