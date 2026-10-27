# 方案：出站闸门（egress policy）——禁止测试载荷进入线上业务群

- 日期：2026-09-30
- 触发事件：11:45:59 / 11:46:42 / 11:47:08，三个**单元测试夹具**渲染出的图片
  （`aaaa…(64)`=3,570B、`aaaa…(64)_1`=3,570B、`bbbb…(64)`=4,140B，内容 `正文甲`/`正文乙`）
  经驱动进入 `李老哈（品牌）💰臻肆外卖运营对接群`（线上业务群），随后被撤回。
- 状态：**方案待确认，尚未改任何代码**（铁律：先方案再编码）

---

## 1. 根因（两层，缺一不可）

| # | 层 | 事实 | 证据 |
|---|---|---|---|
| R-1 | **载荷** | 夹具造数用了**真实品牌名**（`品牌="李老哈"`） | `brand-negative-review-appeal-followup/tests/test_delivery_executor.py:30-36` |
| R-2 | **路由** | 目标群由 `品牌` 解析得出（CSV 列 `群检索结果` 为「待统一微信执行器核验」，实际由执行器解析） | 09-29 CSV 全 4 行均为该值；本次落点正是李老哈群 |
| R-3 | **通道** | Mac 侧发送实现 `windows_adapter.send_one` 只校验「能够打开会话」，**不校验载荷出身、不校验目标群是否被授权** | `scripts/windows_adapter.py` |

⇒ 夹具数据 + 真实品牌 ⇒ 解析出真实业务群 ⇒ 无闸门拦下 ⇒ 测试数据进线上群。

**⚠️ 上述"绕过技能执行器 / 疑似第三方直连驱动"的推断已于 12:15 被推翻，真实根因见下（保留原文以留痕）**：

> **真实根因（代码级铁证）**：肇事者是 **⑨ 技能自己的测试套件**，不是外部进程。
> 1. 夹具用**真品牌名 `李老哈`**，而目标群 `prepare.GROUP` 是**模块常量**——测试只 patch 了
>    `ROOT/WECHAT` 路径，**隔离不了群身份** ⇒ 目标解析成线上群；
> 2. 测试把桩打在 `heartbeat_recovery.run`，而 `delivery_executor.run()` 真正的传输点是
>    **`_windows_run(...)`**（`:367/441/451/462`）⇒ 旧 macOS 通道的遗留桩**完全失效、走真驱动真发**；
> 3. 无任何出站守卫。
>
> 所谓"绕过执行器"的表象，是因为测试把 `delivery.WECHAT` 打桩到**临时目录**，
> 故事件写进临时根、真实 `.runtime` 才"无新事件"。物证：群内 `aaaa…(64a).png`/`bbbb…(64b).png`
> 大小 3570/4140 与本机 `render_png("正文甲"/"正文乙")` **完全一致**，文件名即夹具 `记录键`。
>
> ⇒ **但"闸门必须设在出站通道"这个结论依然成立且更被强化**：本次正是被测试打穿了技能层，
> 说明技能层隔离（已修 3 道锁）**不足以**覆盖全部路径（其它技能、其它副本、直连驱动）。
> 故本方案继续实施：出站通道层加闸门 + 载荷出身校验（新增 **R5 退化载荷** 规则，直接封本次事故的形态）。

---

## 2. 目标（可验收）

1. **测试载荷（夹具/自检数据）在测试群集合为空时，一律无法送达任何群**；有测试群时只能进测试群。
2. **生产载荷行为不变**：当日授权群 + 当日真实业务 CSV 的载荷，判定强度、回执、台账全部不变。
3. **拒绝必须 fail-closed 且留痕**：拒发要写一条 `egress-denied` 事件（含 reason、目标群、载荷摘要），
   不得静默丢弃、不得降级成"发到上一个会话"。

---

## 3. 最小改动设计

### 3.1 新增 `scripts/egress_policy.py`（纯函数，无 IO，可单测）

```python
TEST_GROUP_ENV = "WECHAT_TEST_GROUPS"        # 逗号分隔；默认空

SENTINEL = ("正文甲", "正文乙", "__TEST__", "TEST-IMG", "lorem ipsum", "hello world")

def check(*, group, resolved_group, items, authorized_groups, business_keys=None,
          test_groups=frozenset()) -> dict:
    """返回 {"allow": bool, "reason": str}。任一规则命中即拒发。"""
```

规则（按顺序，命中即 deny）：

| 规则 | 条件 | reason |
|---|---|---|
| R1 目标群必须是「当日授权群 ∪ 测试群」 | `resolved_group ∉ authorized_groups ∪ test_groups` | `egress-group-not-authorized` |
| R2 无测试群时禁止一切非授权群 | `test_groups == ∅` 且 `resolved_group ∉ authorized_groups` | `egress-test-group-undefined` |
| R3 哨兵载荷只能进测试群 | 任一条目（text/name）命中 `SENTINEL` 且 `resolved_group ∉ test_groups` | `egress-sentinel-payload` |
| R4 载荷必须在当日业务快照在册 | `business_keys` 非空 且 条目键 ∉ `business_keys` | `egress-payload-not-in-business-snapshot` |
| **R5 退化载荷（本次事故形态）** | 条目 `name`/`text` **或其词干**是**单字符重复 ≥20 次**（`aaaa…`/`bbbb…`） | `egress-degenerate-payload` |

- R1/R2 封死"测试载荷落到业务群"的**路由层**；
- R3 封死"夹具文案"这类**明显测试内容**（零成本、直击本次事故）；
- R4 是可选的**在册校验**（由调用方提供当日 CSV 的记录键集合；⑨ 可提供，⑥/⑦ 可不提供）。
- 三条规则都**不引入任何模糊匹配**，全部为集合/精确串比对 ⇒ 不降低判定强度。

### 3.2 接入点（唯一强制点）

`windows_adapter.send_one()` 在**解析出 `resolved` 之后、调用驱动之前**调用 `egress_policy.check`：
- `allow=False` ⇒ **不调用驱动**，写 `egress-denied`（reason 进回执），条目标 `blocked`；
- `allow=True` ⇒ 原逻辑完全不变。
- `authorized_groups` 来源：`request["authorization"]["groupName"]`（已是现成字段，零新增状态）；
- `test_groups` 来源：环境变量 `WECHAT_TEST_GROUPS`（默认空 ⇒ 最严）。

### 3.3 夹具与生产物理隔离（防再犯）

- `tests/test_delivery_executor.py` 的造数改**保留品牌名** `__TEST__`、门店 `测试门店甲/乙`（保留字）。
- `prepare_delivery` 入口：CSV 中出现保留品牌 `__TEST__` ⇒ 直接拒（`test-fixture-brand-not-deliverable`）。
- 效果：即使夹具被真实执行器跑到，也会在**冻结前**被拒，不会走到发送。

---

## 4. 边界（明确不做什么）

- **不做**：不改 Windows 驱动；不改回读判定强度；不引入群名模糊匹配；不动 ⑦/⑥ 的既有投递逻辑；
- **不做**：不自动把未授权群"改投"到测试群（那是静默降级，必须硬失败）；
- **不做**：不回溯追责已发生的一次发送（大同已明确不追责）。

---

## 5. 测试计划（全离线，无真机发送）

`tests/test_egress_policy.py`（≥14 条）：
- 授权群放行 / 非授权群拒 / 测试群空时拒非授权群 / 测试群集合含目标群则放行；
- 哨兵（正文甲、正文乙、TEST-IMG）在业务群拒、在测试群放行；真实正文（含"差评/申诉中"）不误伤；
- `business_keys` 提供时，快照外键拒、快照内键放行；未提供时 R4 不生效；
- 大小写/空格边界（保留名 `__TEST__` 精确匹配，不误伤真实品牌）。

回归：`wechat-messaging` 全量离线 211 项 + ⑨ 技能离线测试 + Top10 29 项。全绿后才走受控再封印。

---

## 6. 放行条件（需大同确认）

1. **同意本方案**（尤其是 R3 哨兵词表 —— 若你认为"测试/正文甲"这类词可能出现在真实差评里，我把 R3 收窄为只匹配 `__TEST__`/`TEST-IMG`，或直接删掉 R3 只留 R1/R2/R4）；
2. **测试群落地**（D17）：`WECHAT_TEST_GROUPS` 填什么？填不出安全测试群时保持**空**（=最严，一切非授权群全拒）；
3. 确认后我执行：加保护文件 → 单测 → 受控再封印（新授权 `user-20260930-egress-policy-guard`）→ 重绑受影响的下游摘要（Top10 / daily-negative-reviews）。

---

## 7. 残余风险（诚实披露）

- **绕道风险**：任何人直接 `from client import WeChat` 调驱动，仍可绕过本闸门（本闸门在项目的适配层，不在驱动内）。
  补偿：**出站审计**——在 `egress_policy` 里记录每次出站（时间/目标群/载荷摘要/调用方 PID），
  事后可比对驱动 `inbox` 与审计流水，**发现绕过**。是否要做这一层，请一并裁决。
- **R3 误伤风险**：真实评价内容含"测试"字样时会误伤 ⇒ 默认实现里 R3 只匹配保留名（`__TEST__`/`TEST-IMG`）与前缀，
  "正文甲/正文乙"作为**可选**项（默认关闭），避免影响线上。
