# 麦当劳 MCP Tool 速查表

> 来源：[麦当劳中国 MCP Server 使用指南](https://github.com/M-China/mcd-mcp-server)
> 接入地址：`https://mcp.mcd.cn` ｜ 协议：Streamable HTTP ｜ 鉴权：`Authorization: Bearer <Token>`

McWise 当前覆盖 **26 个 Tool**，按模块归类如下（✅ = McWise 已接入）。

## 点餐与菜单

| Tool | 描述 | McWise |
| --- | --- | --- |
| `now-time-info` | 获取当前时间信息，便于判断菜单时段 | ✅ |
| `query-nearby-stores` | 查询地址附近的麦当劳餐厅 | ✅ |
| `query-meals` | 查询当前门店可售卖的餐品列表 | ✅ |
| `query-meal-detail` | 查询餐品详情与套餐组成、可替换项 | ✅ |
| `calculate-price` | 计算商品金额、配送费、优惠及应付总价 | ✅ |
| `create-order` | 创建订单，返回订单详情与支付链接 | ✅（需确认） |
| `query-order` | 查询订单状态、配送信息 | ✅ |
| `cancel-order` | 取消点餐订单 | — |
| `order-list` | 查询近期到店 / 外送历史订单 | — |
| `query-meal-assistance` | 团餐场景查询门店助餐服务 | — |
| `delivery-query-addresses` | 查询用户可配送地址列表 | ✅ |
| `delivery-create-address` | 新增配送地址 | — |
| `delivery-query-stores` | 查询可配送门店列表 | — |

## 营养

| Tool | 描述 | McWise |
| --- | --- | --- |
| `list-nutrition-foods` | 餐品营养信息列表（能量、蛋白质、脂肪、碳水、钠、钙） | ✅ |

## 优惠券

| Tool | 描述 | McWise |
| --- | --- | --- |
| `query-store-coupons` | 查询当前门店可用优惠券 | ✅ |
| `query-my-coupons` | 查询账户下全部可用优惠券 | ✅ |
| `available-coupons` | 麦麦省券列表查询 | ✅ |
| `auto-bind-coupons` | 麦麦省一键领券（自动领取所有可领券） | ✅ |

## 积分与商城

| Tool | 描述 | McWise |
| --- | --- | --- |
| `query-my-account` | 我的积分查询（可用/累计/冻结/即将过期） | ✅ |
| `mall-points-products` | 麦麦商城商品列表 | ✅ |
| `mall-product-detail` | 商城商品详情（图片、积分、有效期、说明） | ✅ |
| `mall-create-order` | 积分兑换商品下单 | ✅（需确认） |
| `mall-order-list` | 商城订单查询 | ✅ |
| `mall-order-detail` | 商城订单详情查询 | — |
| `query-lottery-info` | 积分抽奖活动信息 | — |
| `draw-lottery` | 执行一次积分抽奖 | — |
| `query-my-prizes` | 查看我的奖品 | — |

## 活动与主题派对

| Tool | 描述 | McWise |
| --- | --- | --- |
| `campaign-calendar` | 当月营销活动日历 | ✅ |
| `query-party-city` | 主题活动可参与城市列表 | ✅ |
| `query-party-store` | 指定城市下主题活动门店列表 | ✅ |
| `query-partystore-date` | 指定门店的可预约日期 | ✅ |
| `query-partystore-session` | 指定门店、日期的可预约场次 | ✅ |
| `party-order-create` | 主题活动订单创建 | ✅（需确认） |

## 错误码

| code | 原因 | 处理建议 |
| --- | --- | --- |
| `401` | Token 无效、已过期或未提供 | 检查 `Authorization` 请求头与 Token 配置 |
| `429` | 触发限流（超过 600 次/分钟） | 降低请求频率，合理控制调用间隔 |

## 安全约定

- 下单类 Tool：`create-order`、`mall-create-order`、`party-order-create`、`cancel-order`
  —— **仅在用户显式确认后调用**。
- 读取类 Tool 可自由调用，但**不做持久化存储**。
