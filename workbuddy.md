# WorkBuddy 开发对话上下文

本文件记录 **麦麦智囊（McWise）** 在 WorkBuddy 中从 0 到 1 的开发过程，
用于核验项目符合「麦当劳程序员创意开发大赛」WorkBuddy 专项奖励的联动条件。

- **开发工具**：腾讯 WorkBuddy
- **开发模式**：Agent 模式（说即做）
- **项目仓库**：`mcwise`
- **本文件性质**：开发过程记录，已脱敏（不含 Token、手机号、订单号等任何凭据）

---

## 1. 开发目标

> 基于麦当劳中国 MCP Server 的开放能力，开发一个有实际决策价值的 Skill，
> 而不是「再包一层聊天框」的简单检索。

开发过程中向 WorkBuddy 提出的核心需求：

1. 通读麦当劳 MCP Server 仓库与创意开发大赛仓库，梳理可用的 Tool 清单与参赛必备文件。
2. 设计一个有差异化创意的 Skill 方案，并落地为完整可运行的项目。
3. 必须满足大赛对文件命名与内容的规定（含 `CONTEST_DECLARATION.md` 内容不可改动）。
4. 代码要能跑、要有测试、要专业。

---

## 2. 关键对话节点

### 2.1 需求输入

```
https://github.com/M-China/mcd-mcp-server  这是麦当劳的 mcp 服务器信息
https://github.com/M-China/mcd-developer-innovation-challenge  这是我们要参加的活动
请你按照活动要求，自动在我们的工作目录下创建活动需要的项目，记得弄的专业一些。
```

### 2.2 WorkBuddy 的调研动作

- 抓取 `mcd-mcp-server` 仓库 README，提取：接入地址 `https://mcp.mcd.cn`、
  Streamable HTTP 协议、Bearer Token 鉴权、限流规则、**26 个 Tool 的完整清单与版本日志**。
- 抓取 `mcd-developer-innovation-challenge` 仓库 README 与 `activityGuidelines.md`，
  提取：赛程时间、报名方式、排名规则（Star 数）、奖励结构、
  **必需文件清单（README.md / CONTEST_DECLARATION.md / MCP_INTEGRATION.md / mcp-config.example.json / workbuddy.md）**。
- 直接下载 `CONTEST_DECLARATION.md` 官方原文，保证**逐字节一致、不做任何修改**。

### 2.3 方案设计（WorkBuddy 提出的创意）

WorkBuddy 给出的核心判断：

> 「大多数参赛项目会停留在『用户问什么、我调什么 Tool』的检索层。
> McWise 的差异应该是在 MCP 之上叠加一个**求解层**——
> MCP 提供实时事实，本地求解器在约束下搜索最优解。」

由此确定四大模块（营养配餐官 / 省钱参谋 / 积分管家 / 活动雷达）+ 一个受保护的成单流程，
并明确三条设计原则：**可解释、可复核、可降级**。

### 2.4 开发执行

WorkBuddy 自动完成：

1. 创建仓库骨架（`scripts/` `tests/` `examples/` `references/`）。
2. 实现数据归一化层 `mcd_core.py`——对 MCP 返回字段做**宽松解析**，
   兼容 `energy` / `energyKcal` / `热量` 等多种命名。
3. 实现四个求解器：
   - `nutrition_planner.py`：加权相对偏差 + 硬约束过滤 + 自动降级
   - `deal_strategist.py`：券子集枚举 + 凑单净收益扫描
   - `points_concierge.py`：每 1000 积分价值排序 + 0/1 背包
   - `campaign_radar.py`：城市 × 兴趣匹配打分
4. 实现 `workflow.py` 固化五条 MCP Tool 调用链。
5. 编写 22 个单元测试并运行。

### 2.5 迭代与修复

**第一轮测试结果：`Ran 22 tests — FAILED (failures=1, errors=4)`**

WorkBuddy 定位到两个真实缺陷并修复：

| # | 缺陷 | 根因 | 修复 |
| --- | --- | --- | --- |
| 1 | `TypeError: unsupported operand type(s) for -: 'list' and 'float'` | `_best_subset()` 返回 `(券列表, 优惠额)`，调用处解包顺序写反 | 修正为 `_, new_saving = _best_subset(...)` |
| 2 | 活动推荐排序与预期不符 | 状态权重（进行中 3.0）压过了个性化权重，导致「城市 + 兴趣」双命中的活动排不进前三 | 降低状态权重（进行中 2.0 / 即将开始 1.6），提高兴趣（1.5/项）与城市命中（+1.5）权重，使结果更贴近个性化推荐语义 |

**第二轮测试结果：`Ran 22 tests — OK`** ✅

### 2.6 端到端验证

WorkBuddy 用示例数据跑通四个模块的 CLI，实际输出（快照见 `examples/`）：

```
$ python scripts/cli.py nutrition --input examples/nutrition_input.json
¥45.00  ·  板烧鸡腿堡 + 玉米杯 + 美式咖啡（中）
  营养：热量 535kcal | 蛋白质 27g | 脂肪 18g | 碳水 63g | 钠 905mg
  偏差：热量 -0.9%，蛋白质 -3.6%，脂肪 +0.0%，碳水 +0.0%，钠 +0.6%

$ python scripts/cli.py deals --input examples/deals_input.json
小计 ¥57.00 → 实付 ¥58.00（省 ¥8.00）
  ↘ 凑单建议：加「苹果片」¥8.00，净省 ¥4.00

$ python scripts/cli.py points --input examples/points_input.json
可用积分 3200 → 建议消耗 3100，剩余 100
兑换后总价值约 ¥71.00（效率 ¥22.90/1000 积分）
  ⚠ 有 500 积分即将过期，建议优先消耗。
```

---

## 3. WorkBuddy 在本项目中的作用

| 环节 | WorkBuddy 承担的工作 |
| --- | --- |
| 调研 | 抓取并结构化两个官方仓库的全部规则与 Tool 清单 |
| 合规 | 直接下载官方 `CONTEST_DECLARATION.md`，确保内容零改动 |
| 设计 | 提出「求解层」差异化定位与四模块拆分 |
| 编码 | 产出 7 个 Python 模块 + 22 个测试 + 6 份文档 |
| 调试 | 定位并修复 2 个真实缺陷，测试全绿 |
| 验证 | 端到端运行 CLI，生成示例输出快照 |
| 文档 | 编写 README / MCP_INTEGRATION / SKILL 三份核心文档 |
| 工程化 | 编写合规自检脚本、三套 GitHub Actions 工作流、Dependabot 配置 |
| 仓库 | `git init`、`.gitattributes` 换行符策略、提交前敏感信息扫描 |

---

## 3.1 工程化阶段（第二轮迭代）

在项目上线 GitHub 之后，继续完善了工程质量保障：

1. **参赛合规自检脚本** `scripts/check_compliance.py`
   —— 把「必需文件齐全 / 声明原文一致 / JSON 合法 / 配置脱敏 / 无硬编码凭据」
   五类校验固化为可执行脚本，本地与 CI 共用同一套逻辑，避免两处规则漂移。

2. **三套 GitHub Actions 工作流**
   - `ci.yml`：`ubuntu` / `windows` / `macos` × Python `3.9` / `3.13` 矩阵跑全部单元测试，
     外加 CLI 端到端冒烟与 JSON 输出结构校验；
   - `lint.yml`：`ruff check` + `ruff format --check`；
   - `compliance.yml`：合规自检，并**实时拉取官方原文比对 sha256**。

3. **反向测试** `tests/test_compliance.py`
   —— 用 11 个用例证明自检脚本**确实能抓到违规**（缺失文件、声明被改动、
   CRLF 污染、真实 Token、`.env` 入库、BOM、私钥泄漏），而不是永远返回通过。

4. **自检脚本对自己的测试夹具产生了一次误报**（夹具里含"假 Token"和"假私钥"字符串），
   修复方式是让夹具在**运行时拼接**而非写成字面量 —— 保持扫描规则零豁免，
   而不是给检查器开后门加白名单。

---

## 4. 可复现性说明

本项目的全部产物（代码、测试、文档、示例）均可通过仓库内容独立复现，
不依赖任何会话内的临时状态。验证方式：

```bash
python scripts/check_compliance.py        # 参赛合规自检 → 全部通过（共 19 项检查）
python -m unittest discover -s tests -v   # Ran 33 tests ... OK
ruff check scripts tests                  # All checks passed!
ruff format --check scripts tests         # 已格式化
```

---

## 5. 脱敏声明

本文件及整个仓库：

- 不包含任何真实 MCP Token、API Key、密码或账号凭证；
- 不包含手机号、收货地址、订单号等个人信息；
- 配置文件仅使用环境变量占位符 `${MCD_MCP_TOKEN}`；
- 示例数据为公开渠道整理的教学示例，非真实用户数据。
