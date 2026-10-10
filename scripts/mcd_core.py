"""McWise 核心数据模型与归一化工具。

本模块把麦当劳 MCP Server 各 Tool 返回的原始 JSON 结果，归一化为内部统一的数据
对象，供上层各优化器（营养配餐 / 省钱参谋 / 积分管家 / 活动雷达）复用。

设计原则：
1. 只依赖 Python 标准库，离线可测；
2. 对 MCP 返回字段做"宽松解析"——不同版本 Tool 的字段命名可能存在差异，
   因此统一走 `_first()` 多候选键名兜底；
3. 缺失字段一律降级为安全默认值，绝不让上游数据瑕疵中断整个规划流程。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

__all__ = [
    "Campaign",
    "CartLine",
    "Coupon",
    "MallProduct",
    "MenuItem",
    "Nutrition",
    "to_dict",
]


# --------------------------------------------------------------------------- #
# 基础解析工具
# --------------------------------------------------------------------------- #
def _num(value: Any, default: float = 0.0) -> float:
    """把任意输入安全地转换为 float。"""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first(source: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    """按候选键名顺序取第一个非空值，用于兼容不同 Tool 的字段命名。"""
    if not isinstance(source, Mapping):
        return default
    for key in keys:
        if key in source and source[key] not in (None, ""):
            return source[key]
    return default


def _nutri_from_any(raw: Any) -> Nutrition:
    """兼容 dict / list 两种营养信息结构。"""
    if isinstance(raw, Mapping):
        return Nutrition.from_dict(raw)
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        merged: dict[str, Any] = {}
        for entry in raw:
            if isinstance(entry, Mapping):
                name = str(_first(entry, "name", "nutrient", "key", "item", default="")).strip()
                value = _first(entry, "value", "amount", "content")
                if name:
                    merged[name] = value
        return Nutrition.from_dict(merged)
    return Nutrition()


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class Nutrition:
    """单份餐品的营养成分（每份含量）。"""

    energy_kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carb_g: float = 0.0
    sodium_mg: float = 0.0
    calcium_mg: float = 0.0

    # 常见中文别名 -> 内部字段
    _ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {
        "energy_kcal": (
            "energy_kcal",
            "energy",
            "energyKcal",
            "calorie",
            "calories",
            "热量",
            "能量",
            "能量(kcal)",
            "能量(Kcal)",
        ),
        "protein_g": ("protein_g", "protein", "蛋白质", "蛋白质(g)"),
        "fat_g": ("fat_g", "fat", "脂肪", "脂肪(g)"),
        "carb_g": ("carb_g", "carbohydrate", "carb", "carbs", "碳水化合物", "碳水化合物(g)"),
        "sodium_mg": ("sodium_mg", "sodium", "钠", "钠(mg)"),
        "calcium_mg": ("calcium_mg", "calcium", "钙", "钙(mg)"),
    }

    @classmethod
    def from_dict(cls, raw: Any) -> Nutrition:
        if not isinstance(raw, Mapping):
            return cls()
        kw: dict[str, float] = {}
        for internal, aliases in cls._ALIASES.items():
            kw[internal] = _num(_first(raw, *aliases), 0.0)
        return cls(**kw)

    def get(self, key: str) -> float:
        return float(getattr(self, key, 0.0))

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class MenuItem:
    """可售卖餐品（来自 query-meals / query-meal-detail / list-nutrition-foods）。"""

    code: str
    name: str
    category: str = "other"
    price: float = 0.0
    nutrition: Nutrition = field(default_factory=Nutrition)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> MenuItem:
        nutri_raw = _first(raw, "nutrition", "nutritionFacts", "nutrition_info", "营养成分")
        if nutri_raw is None:
            nutri_raw = raw  # 营养 Tool 常常把营养字段平铺在根节点
        return cls(
            code=str(_first(raw, "code", "productCode", "mealCode", "sku", "id", default="")),
            name=str(_first(raw, "name", "productName", "mealName", "title", default="未命名餐品")),
            category=str(_first(raw, "category", "categoryName", "type", "group", default="other")).lower(),
            price=_num(_first(raw, "price", "salePrice", "currentPrice", "amount"), 0.0),
            nutrition=_nutri_from_any(nutri_raw),
            tags=[str(t) for t in (_first(raw, "tags", "labels", "flags", default=[]) or [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "price": round(self.price, 2),
            "nutrition": self.nutrition.to_dict(),
            "tags": list(self.tags),
        }


@dataclass
class Coupon:
    """优惠券。

    kind 取值：
      - ``threshold`` 满减券：满 threshold 元减 discount 元
      - ``discount``  折扣券：按 discount（如 0.85）打折
      - ``freebie``   赠品券：赠送价值约 value 元的小食
    """

    coupon_id: str
    name: str = ""
    kind: str = "threshold"
    threshold: float = 0.0
    discount: float = 0.0
    applies_to: list[str] = field(default_factory=list)
    exclusive_group: str = "default"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Coupon:
        kind = str(_first(raw, "kind", "type", "couponType", default="threshold")).lower()
        if kind in ("满减", "manjian", "full_reduction"):
            kind = "threshold"
        elif kind in ("折扣", "zhekou", "rebate"):
            kind = "discount"
        elif kind in ("赠品", "gift", "free"):
            kind = "freebie"
        elif kind not in ("threshold", "discount", "freebie"):
            kind = "threshold"
        applies = _first(raw, "applies_to", "appliesTo", "scope", "productCodes", default=[]) or []
        if isinstance(applies, (str, bytes)):
            applies = [applies]
        return cls(
            coupon_id=str(_first(raw, "coupon_id", "couponId", "id", "code", default="")),
            name=str(_first(raw, "name", "title", "couponName", default="优惠券")),
            kind=kind,
            threshold=_num(_first(raw, "threshold", "minAmount", "minSpend", "condition"), 0.0),
            discount=_num(_first(raw, "discount", "amount", "value", "reduce", "rate"), 0.0),
            applies_to=[str(x) for x in applies],
            exclusive_group=str(_first(raw, "exclusive_group", "group", default="default")),
        )

    def eligible(self, subtotal: float) -> bool:
        return subtotal + 1e-9 >= self.threshold

    def saving_for(self, subtotal: float) -> float:
        """在当前小计金额下，这张券能省多少钱。"""
        if not self.eligible(subtotal):
            return 0.0
        if self.kind == "threshold":
            return min(self.discount, subtotal)
        if self.kind == "discount":
            rate = self.discount if self.discount < 1 else self.discount / 100.0
            rate = max(0.0, min(1.0, rate))
            return round(subtotal * (1.0 - rate), 2)
        if self.kind == "freebie":
            return max(0.0, self.discount)
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MallProduct:
    """麦麦商城商品（积分兑换 / 现金购买）。"""

    product_id: str
    name: str
    points_cost: float = 0.0
    cash_price: float = 0.0
    market_value: float = 0.0

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> MallProduct:
        points = _num(_first(raw, "points_cost", "pointsCost", "points", "needPoints", "integral"), 0.0)
        cash = _num(_first(raw, "cash_price", "cashPrice", "price", "amount"), 0.0)
        market = _num(_first(raw, "market_value", "marketValue", "value", "worth", "faceValue"), 0.0)
        if market <= 0:
            market = max(cash, 0.0)
        return cls(
            product_id=str(_first(raw, "product_id", "productId", "id", "code", default="")),
            name=str(_first(raw, "name", "title", "productName", default="商城商品")),
            points_cost=points,
            cash_price=cash,
            market_value=market,
        )

    @property
    def value_per_1000_points(self) -> float:
        """每 1000 积分的等值人民币（元）——积分使用效率的核心指标。"""
        if self.points_cost <= 0:
            return 0.0
        return round(self.market_value / self.points_cost * 1000.0, 2)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["value_per_1000_points"] = self.value_per_1000_points
        return data


@dataclass
class Campaign:
    """营销 / 主题活动。"""

    name: str
    status: str = "upcoming"  # ongoing | upcoming | past
    start: str = ""
    end: str = ""
    city: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Campaign:
        tags = _first(raw, "tags", "keywords", "labels", default=[]) or []
        if isinstance(tags, (str, bytes)):
            tags = [tags]
        return cls(
            name=str(_first(raw, "name", "title", "activityName", default="未命名活动")),
            status=str(_first(raw, "status", "state", default="upcoming")).lower(),
            start=str(_first(raw, "start", "startDate", "beginDate", default="")),
            end=str(_first(raw, "end", "endDate", default="")),
            city=str(_first(raw, "city", "cityName", default="")),
            tags=[str(t) for t in tags],
            description=str(_first(raw, "description", "desc", "summary", default="")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CartLine:
    """购物车行。"""

    code: str
    name: str
    price: float
    qty: int = 1

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CartLine:
        return cls(
            code=str(_first(raw, "code", "productCode", "id", default="")),
            name=str(_first(raw, "name", "productName", default="商品")),
            price=_num(_first(raw, "price", "salePrice", "amount"), 0.0),
            qty=int(_num(_first(raw, "qty", "quantity", "count", "num"), 1)),
        )

    @property
    def subtotal(self) -> float:
        return round(self.price * max(1, self.qty), 2)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["subtotal"] = self.subtotal
        return data


def to_dict(obj: Any) -> Any:
    """递归地把 dataclass 转换为原生 dict / list，便于 JSON 序列化。"""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, Mapping):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, Iterable) and not isinstance(obj, (str, bytes)):
        return [to_dict(v) for v in obj]
    return obj
