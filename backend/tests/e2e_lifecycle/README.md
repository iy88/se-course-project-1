<!--
Version: 0.1.0
Version-Datetime: 2026-10-29T15:50:59+08:00
-->

# 开发环境真实 HTTP 生命周期测试（e2e_lifecycle）

本目录用**真实运行中的开发后端（uvicorn + 开发库 + Redis/本地存储）**和真实 HTTP 接口，
按现有阶段执行完整使用生命周期，并把覆盖各 US／SC 的账号、商品、图片、交易、事项与通知数据
留在开发库中。它补充 `backend/tests/` 的 pytest 夹具测试：后者走 `ASGITransport` 内存应用与临时库，
本目录走真实网络、真实会话、真实后台扫描与真实存储，二者不能互相代替。

## 目录

| 路径 | 内容 |
|---|---|
| `e2e_client.py` | httpx 真实 HTTP 客户端：鉴权、预期状态码、调用日志、5xx 自动记为缺陷 |
| `e2e_recorder.py` | 检查项记录器：`rec.step(check_id, us=, sc=)` → PASS/FAIL/SKIP 与缺陷候选 |
| `e2e_support.py` | 上下文与数据清单、注册/登录/上传、签名 URL、时间加速、共享池辅助、结束状态复核 |
| `e2e_runner.py` | 阶段编排、`--only/--skip`、结果落盘 `results.json / inventory.json / report.md` |
| `e2e_report.py` | 报告生成：US／SC 覆盖、失败清单、缺陷、数据清单、证据边界 |
| `phases/p01—p10` | 按领域划分的阶段模块，每个模块可单独运行 |
| `assets/` | 真实上传用的本地图片素材（商品图 11 张、举报证据图 2 张） |
| `make_assets.py` | 用 Pillow 重新生成 `assets/`（仅维护素材时需要） |
| `tools/coverage_check.py` | 把运行结果与需求覆盖矩阵比对（`coverage_expected.json`） |
| `tools/db_snapshot.py` | 只读 SQLite 快照：表行数、商品/交易/事项状态分布、通知类型、图片统计 |
| `tools/supplementary_checks.py` | 少量未单独编号分支的补充真实 API 核验（含前端代理、签名图片） |
| `coverage_expected.json` | 105 条 US-AC、109 条 SC 分支的覆盖矩阵（来自需求文档分析；矩阵条目不等于全部已执行或已验证） |

## 前置条件

- 后端按 `README.md` 启动，`ENVIRONMENT=dev`、`DEV_EXPOSE_VERIFICATION_CODE=true`，Redis 可用（验证码与评论频控依赖 KV）；
- 已执行 `uv run python -m app.seed`（管理员、分类、禁发范围、演示账号）；
- **只对开发环境运行**：会真实创建账号、商品、交易、通知与图片，且没有删除/重置接口，数据不可清理；
  禁止指向生产库或他人共享库；
- 完整流程含 p08 真实后台扫描等待（默认扫描间隔 60 秒），全量约 90—120 秒。

## 运行

从仓库根目录：

```bash
# 终端一：后端（开发配置）
cd backend
uv run python -m app.seed                 # 首次或需补种子时
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# 终端二：全量生命周期（真实 HTTP）
cd backend/tests/e2e_lifecycle
../../.venv/bin/python e2e_runner.py \
  --base-url http://127.0.0.1:8000
```

`--db-path` 默认指向仓库 `var/db/app.db`，`--results-dir` 默认指向仓库 `var/e2e-results`；
后端使用其他 SQLite 时再显式传 `--db-path`。相对路径按当前工作目录解析，解释器 `../../.venv`
指 `backend/.venv`，不要改成 `../../../.venv`。

常用参数：

```bash
../../.venv/bin/python e2e_runner.py --list                    # 阶段列表
../../.venv/bin/python e2e_runner.py --only p01 p03            # 只跑部分阶段
../../.venv/bin/python e2e_runner.py --skip p08                # 跳过超时场景
../../.venv/bin/python e2e_runner.py --no-refresh              # 跳过结束状态复核
```

结果目录包含 `report.md`（人读）、`results.json`（检查项明细）、`inventory.json`（数据清单）。
`--db-path` 只供 p08 时间加速使用；实际库应指向本次运行后端所用 SQLite。

## 阶段与需求对应

| 阶段 | 内容 | 覆盖 |
|---|---|---|
| p01 | 账户生命周期与访问控制 | US-01、SC-01（注册验证码、登录、改密、换邮箱、忘记密码、封禁读写） |
| p02 | 分类标签与禁发范围维护 | US-08 部分、US-13、SC-10、SC-02（改名/别名/停用/逻辑删除、禁发范围 CRUD 与权限） |
| p03 | 商品发布、审核与维护 | US-02、US-09、SC-02、SC-10（审核通过/不通过、撤回/重提、标签申请三种决策、编辑历史、上下架、图片上传与签名 URL） |
| p04 | 检索、详情、收藏与评论 | US-03、US-04、SC-03（组合检索、可见性、收藏失效/恢复、评论/回复/限流） |
| p05 | 请求、约定、确认与终止 | US-05、US-06、SC-05、SC-06（全交易状态、约定变更、确认、取消、争议、D-48/D-49） |
| p06 | 两类 IM 与站内通知 | US-04、US-11、SC-04、SC-11（普通私聊/交易分支、分分支已读、归档、冻结隔离、通知与 WS） |
| p07 | 评价、举报、认领与封禁 | US-07、US-08、SC-07（双向评价、举报各目标、问询/说明/决策/申诉、封禁联动、匿名结果） |
| p08 | 单方确认超时与异常交易 | US-14、SC-09（冻结暂停计时与续算、真实扫描转异常、异常处置、D-48/D-50） |
| p09 | 统计、本人业务与待办 | US-10、US-12、SC-08、SC-12、SC-11（统计口径、双向评价、举报入口、待办） |
| p10 | 可靠性与权限边界 | 7.3 可靠性、越权/重复提交/并发锁单/参数边界 |

## 数据与账号

- 固定人设账号：种子 `admin@campus.edu`、`zhang@campus.edu`、`li@campus.edu`、`wang@campus.edu`；
  阶段新建 `chen@campus.edu`、`liu@campus.edu`、`zhao@campus.edu`、`qian@campus.edu`、`wu@campus.edu`、
  `sun@campus.edu`、`email.after@campus.edu`、`reset@campus.edu` 等。开发账号口令以 `e2e_support.py`
  中实际配置为准，不在本文重复记录；重置账号以本次运行 inventory 的最终账号状态为准。
- 各阶段还会按运行需要创建测试账号（如 `devb.*`、`c2.*` 前缀），全部为开发演示数据，不是真实用户；
- 商品图片、举报证据均为本地生成的示意素材，经真实 multipart 上传并从开发存储按签名 URL 读取；
- 重复运行会累积新数据（账号可复用登录；商品/交易/通知会追加），这是开发库演示数据的一部分。

## 时间加速与证据边界

- `p08` 的"单方确认满 7 天"无法在测试内真实等待：只把 SQLite 中 `trades.confirm_wait_started_at`
  前移 8 天（冻结暂停场景只动计时起点），**超时识别、状态转异常、冻结、事项、通知、解冻续算、管理调整
  全部由真实后台扫描与 HTTP 接口完成**；报告与阶段注释中已注明，不得表述为"真实等待 7 天"。
- 结论边界：不代表人工验收、真实邮件、生产数据库/对象存储、真机/PWA、弱网与性能验收；
- 响应丢失注入、多 worker 并发扫描、第二管理员认领竞争等场景无法在本 harness 内完整验证，报告中按"未覆盖/缺口"说明。

## 结果解读

- `PASS` 只代表该检查项本次实际断言通过；检查项编号与需求矩阵编号对应，不等于对应 AC/SC 的全部语义已验证；
- `FAIL` 是真实接口行为与需求／契约的差异，需保留原文与复现条件，不得删除检查项或放宽断言；
- `SKIP` 必须写明理由（由其他阶段覆盖、缺少接口/环境、无法注入等），仅 SKIP 不计执行；
- 覆盖核对把“编号直接登记”和“有非 SKIP 记录”分开统计；同一 SC 其他检查项只标“关联待补证”，
  不自动补齐 AC，也不把仅 SKIP 的 SC 视为已执行；
- 运行结束会用只读接口复核 `inventory` 中对象状态；复核失败只记备注，不改变检查结论。

辅助命令示例：

```bash
# 覆盖核对（需要本次运行的结果与覆盖矩阵）
../../.venv/bin/python tools/coverage_check.py \
  --results ../../../var/e2e-results/<runid>/results.json \
  --coverage coverage_expected.json \
  --out ../../../var/e2e-results/<runid>/coverage_check.md

# 开发库只读快照
../../.venv/bin/python tools/db_snapshot.py --db ../../../var/db/app.db --out ../../../var/e2e-results/<runid>/snapshot.json

# 补充核验（非所有者修改、争议访问/保持、待接受保持、统计空范围、签名图片、前端代理）
../../.venv/bin/python tools/supplementary_checks.py --base-url http://127.0.0.1:8000
```
