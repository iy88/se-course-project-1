# 验收任务分配与 Issue 清单（2026-11-02）

> 用途：把浏览器人工验收与「需求是否完整实现」的核对分给金婉怡、孙含佳、张新悦三人，并记录任务拆分、环境方案、AC 主责、缺陷/需求缺口模板与流转规则。
> 本文件是 `bits/` 工作笔记，不是需求交付材料；三个任务 Issue 已发布到 GitHub，本文件只保留任务清单与执行规则。
> 本文件不自动授权提交或推送。

## 一、结论

1. **自动化已经把业务规则验完**：真实 API 验收 51/51 检查 PASS、105 AC、109 SC（run `20261101T175558Z-8469dd`）。这些**不做人工逐条复测**，人工只验界面、交互、浏览器集成与需求入口。
2. **人工验收覆盖 6 个浏览器通道 + 4 类集成点**：布局、状态表达、空态/错误、受限只读、键盘可达、PWA；图片直传与展示、WebSocket 实时、管理端事项会话、最近前端改动。
3. **同时核对需求完整性**：按 US/AC 逐条确认「有页面入口、能按条件完成、结果/原因可见」。接口 PASS 不等于需求落地；缺功能/缺入口一律建 **feature issue**，不混进 bug。
4. 三个测试任务并行，**生产演示环境是本轮人工验收的主环境**：允许执行完整写流程，也允许成员自建测试账号、商品、请求等数据；demo-seed 场景被改过时用自建对象复现前置，不记 BLOCKED。本地 SQLite+local 用于修改代码后的回归与需要重置重跑的场景。同一生产场景对象同一时间只能由一人操作。

## 二、分工

| 任务 | 执行人 | 主责 | 人工通道主责 | 需求核对范围 |
|---|---|---|---|---|
| A | 金婉怡 | 移动端账户、商品发布/审核状态、检索收藏、评论展示、受限结果、PWA | UI-LAYOUT（移动端用户核心页）、UI-STATE（商品/账户）、UI-ERROR（搜索/守卫）、UI-A11Y、PWA-01 | US-01（除 AC-07）、US-02、US-03、US-09、US-13-AC-01/07，共 30 AC |
| B | 孙含佳 | 移动端交易、两类 IM、通知待办、我的业务、举报提交、受限访问 | UI-LAYOUT（交易/消息/我的）、UI-STATE（交易/通知）、UI-ERROR（IM/限频）、UI-ACCESS-01 | US-01-AC-07、US-04、US-05、US-06、US-07、US-11、US-12，共 47 AC |
| C | 张新悦 | 管理端事项处理、审核/举报、交易异常、分类/统计/审计 | UI-LAYOUT（管理端）、UI-STATE（管理端）、UI-ERROR（管理端）、UI-A11Y（管理端抽查） | US-08、US-10、US-14、US-13-AC-02..06，共 28 AC |

边界说明：
- 同一场景可由两人核对自己角色的一侧（例如 `product.edit_notify` 的卖方编辑与买方通知），但**不得在同一环境并行操作同一对象**。
- US-07 的提交与本人记录由 B 核对；US-07 的管理侧结论/匿名/申辩经 US-08-AC-03/04/05 由 C 核对，不重复计 AC。
- US-02-AC-04 的卖方拒绝由 A 核对，管理员分类纠正部分归 US-13-AC-06（C）。

## 三、基线（可复核）

| 项目 | 事实 |
|---|---|
| 代码 | HEAD `c6f1632`（2026-11-02 02:08）；生成本清单前工作区干净，`bits/` 与 `.github/ISSUE_TEMPLATE/` 为新增工作文件 |
| 自动化 | run `20261101T175558Z-8469dd`：`PASS=51 FAIL=0 SKIP=0`，AC 105 PASS，SC 109 PASS，路由语义 108/108；报告在负责人本机 `var/acceptance-real/acceptance-20261101T175558Z-8469dd.md`（不提交） |
| 源码一致性 | 当前 `backend/app`、`backend/alembic`、`backend/tests/acceptance_real` 的源码摘要 `0025d0ff6eb7bf4e…` 与该 run 记录一致；frontend 不在摘要范围 |
| 目录统计 | `backend/tests/acceptance_real/coverage.json`：51 检查 / 105 AC / 109 SC / 14 主用例 / 66 子用例 / 6 浏览器人工通道 |
| 演示数据 | catalog v2，48 场景、19 身份；seed、verify、自动化回归读取同一目录 `backend/app/devtools/demo_scenarios/` |
| 生产演示环境 | mobile `https://mobile.cm.iy88.site`、admin `https://admin.cm.iy88.site`；`/api/health` = ok；生产 manifest tag `3fc703b230dc9304`（19 账号 / 48 场景 / catalog v2，2026-11-02 02:20） |
| 生产版本抽查 | 生产首页资产哈希与本地 `frontend/*/dist` 一致（`index-mObH_peU.js`、`index-lIhBf__g.js`、`AdminProducts-1yfRRrGS.js`、`MyReports-Bhyz-cfD.js` 等）；`/api/v1/admin/products`、`/api/v1/admin/cases/{id}/conversations/{id}` 均存在（未登录 401）。**仅为抽查**，生产发布版本以负责人确认为准 |
| 人工验收状态 | 任务分配时浏览器人工整体登记为 NOT-RUN；本轮三个任务即是这部分 |

## 四、自动化已覆盖：不人工复测

以下检查已由 `backend/tests/acceptance_real/` 在真实 HTTP/WS 与真实资源上通过。人工任务**不重复判定其规则、错误码、幂等或权限**；只在页面上核对「入口、展示、提示、操作可达」。

| 领域 | 自动检查（PASS） |
|---|---|
| 环境/服务/清理 | `ENV-01`、`SVC-01`、`OBJ-01`、`CLEAN-01` |
| 账户 | `ACC-01`—`ACC-05`（注册验证码、找回/改密/换邮箱、改名、失败登录） |
| 分类/禁发 | `CAT-01`—`CAT-03`、`PROH-01` |
| 文件 | `FILE-01`（租约、直传、签名、校验、拒绝路径；**浏览器 CORS/直传 UI 不在内**） |
| 商品/检索/收藏/评论 | `PROD-01`—`PROD-06`、`SEARCH-01`、`FAV-01`、`COMM-01`、`USERS-01` |
| 交易 | `TRADE-01`—`TRADE-10`、`CONC-01`、`REVIEW-ADMIN-STATES`（含并发、旧状态、九种管理调整） |
| 治理/IM | `GOV-01`—`GOV-05`、`IM-01`—`IM-03` |
| 通知/我的 | `NOTIF-01`—`NOTIF-02`、`MY-01` |
| 管理 | `STATS-01`、`AUDIT-01`、`AUDIT-02`、`ADMIN-CORRECTION-01` |
| demo 生命周期（服务层） | `tests/test_demo_seed.py`（含生命周期转换）、`tests/test_demo_scenarios_catalog.py`、`demo-verify` 只读核验 |

**人工仍必须覆盖**（自动化明确不覆盖）：
- 页面布局、路由守卫、表单可用性、移动端/桌面端视口；
- 状态、资格、禁用态、原因/结果的视觉表达；
- 空态、加载、错误、限频提示；浏览器网络失败与重试；
- 受限账户/冻结交易只读与事项沟通入口；
- 键盘焦点/对比度；
- PWA 安装、离线壳、更新；
- 浏览器图片直传（CORS、预览、失败提示）与签名 URL 展示；
- WebSocket 实时消息与已读交互；
- 管理端事项处理枢纽、关联会话只读、列表分页筛选；
- 需求 AC 是否有页面入口、能否按条件完成。

## 五、需求完整性核对（新增要求）

### 5.1 方法

对本人范围内的每个 AC：

1. 在 `docs/appendices/user-stories/` 找到 AC 原文，确认条件、动作、结果；
2. 找到**页面入口**（移动端/管理端）并实际点开；
3. 按条件操作或核对展示，记录结论：
   - `已实现`：入口存在、可完成、结果/状态/原因可见且符合 AC；
   - `部分实现`：只覆盖部分角色/状态/条件；
   - `缺界面入口`：接口或数据已有，页面无入口（典型：历史记录类接口存在但无页面）；
   - `未实现`：需求要求但完整缺失；
   - `与需求不一致`：页面行为与 AC 冲突（先确认是缺陷还是需求歧义）；
   - `BLOCKED`：缺账号/设备/环境，且无法通过自建测试账号/对象复现前置，写明具体原因；
   - `N/A`：该 AC 不适用于当前界面，写理由并由负责人确认。
4. **只有 `已实现` 才能计入通过**；自动化 API PASS 不能填 `已实现`。
5. `部分实现`、`缺界面入口`、`未实现`、`与需求不一致` 一律新建 **feature issue**（行为错误用 bug）；`BLOCKED` 在任务 issue 说明。
6. 输出：AC 状态表（AC｜页面入口｜结论｜关联 issue｜证据）贴在任务评论；统计六类数量。
7. 不擅自改需求文档、不扩大实现范围；是否本轮补由负责人在 feature issue 书面决定。

### 5.2 AC 主责表（合计 105 AC，逐条唯一）

| 执行人 | AC 范围 | 计数 |
|---|---|---|
| 金婉怡 | US-01-AC-01—06、08；US-02-AC-01—09；US-03-AC-01—06；US-09-AC-01—06；US-13-AC-01、07 | 30 |
| 孙含佳 | US-01-AC-07；US-04-AC-01—09；US-05-AC-01—11；US-06-AC-01—06；US-07-AC-01—07；US-11-AC-01—06；US-12-AC-01—07 | 47 |
| 张新悦 | US-08-AC-01—09；US-10-AC-01—06；US-14-AC-01—08；US-13-AC-02—06 | 28 |

SC 分支通过各 issue 中的 demo 场景清单核对（每条场景已映射 US/UC/SC）；不另建 109 行手工矩阵，但场景未覆盖的分支要在 AC 状态表备注。

注：张新悦的 AC 表另含 US-02-AC-04/08 管理侧与 US-07 管理侧的**交叉复核行**，这些行已由 A/B 主责计数，不重复计入 28，只用于确认管理端入口与处置结果。

## 六、环境与数据隔离

### 6.1 生产演示环境（本轮人工验收主环境，可自建测试数据）

- mobile `https://mobile.cm.iy88.site`，admin `https://admin.cm.iy88.site`；账号与对象 ID 由负责人通过私密渠道分发生产 manifest（tag `3fc703b230dc9304`）。
- 用于：登录、布局、导航、列表/分页/筛选、详情、状态与原因展示、通知/事项、错误提示、PWA 安装（HTTPS），以及审核/举报/交易/封禁/分类等完整写流程；demo 场景对象与自建对象都可使用。
- 自建测试数据：普通用户流程可用本人真实邮箱注册新账号（生产 SMTP 已配置；显示名如 `测试-金婉怡-01`），并新建商品/请求/交易/举报等对象（标题/说明加 `【测试】<姓名>-01`）。管理员账号仍需使用 manifest 的 `admin`/`admin2`（自注册不能获得管理员）。若成员无法接收验证码，改用在 manifest 中的 demo 买家/卖家账号，普通账号的登录/注册流程由 A 的 P2 项单独核对。
- 规则：一次只操作本人负责的 demo 场景对象或自建对象；执行前在结果表登记目标对象与账号；同一对象同一时间只由一人操作；需要另一角色配合时按约定顺序执行。
- **状态不一致时**：若 demo 场景的初始状态已被演示或他人改变，不要直接记 `BLOCKED`，用新账号 + 新商品/请求/举报复现所需前置；确实无法复现（如需真实 7 天超时、真实时间累计）才记 `BLOCKED` 并说明。
- **不允许**：reset/seed/删除、批量创建、压测、修改他人账号、把密码/token/manifest 内容写进 issue/截图/终端记录。成员不得为了重测自行重置生产；需要恢复演示起点时由负责人统一执行 reset + demo-seed（见 `docs/development/部署说明.md` 生产数据重新初始化节）。
- 新对象要少量、可识别（标题加「测试」）；不提交无效内容。生产验收会消耗演示状态，批次结束后由负责人决定是否重置并重新 seed。

### 6.2 本地环境（修改代码后的回归、需要重置重跑时）

允许只配置 SQLite + local 存储 + 内存 KV，**不要求 OSS/PostgreSQL**；SMTP 仍需可启动配置（向负责人获取测试配置，禁止使用生产 `.env.prod`）。按 `backend/.env.dev.example` 填写，关键项：

```text
ENVIRONMENT=dev
API_HOST=127.0.0.1
API_PORT=8000
DATABASE_URL=sqlite+aiosqlite:////<abs>/var/db/dev.db
DATABASE_SCHEMA=app
DB_AUTO_CREATE=true
STORAGE_LOCAL_ROOT=<abs>/var/storage
AUDIT_TRUSTED_PROXIES=none
JWT_SECRET=<random>
FILE_URL_SECRET=<random>
SMTP_HOST=... / SMTP_PORT=... / SMTP_SECURITY=... / SMTP_USERNAME=... / SMTP_PASSWORD=... / SMTP_FROM_EMAIL=... / SMTP_FROM_NAME=...
# 省略全部 OSS_* 与 REDIS_* 字段（= local 存储 + 内存 KV）
```

```bash
(cd backend && APP_ENV_FILE=.env.dev .venv/bin/python -m app.manage migrate)
(cd backend && .venv/bin/python -m app.manage demo-seed --env-file .env.dev)
(cd backend && .venv/bin/python -m app.manage demo-verify --env-file .env.dev)
./scripts/dev.sh start
```

本地可随时停止、删除 SQLite 文件与本地存储目录后重新 seed；每位成员优先使用自己的本地环境，避免互相消费场景。

### 6.3 数据与场景使用规则

- 只使用 demo 账号与场景对象；场景的 `objects` 是互斥分支，不能把某条终态记录当另一条场景的起点。
- 生产与本地分别记录 manifest tag；证据中写实际 tag/run_id。
- 同一场景被两名成员核对时（如 `product.edit_notify`），各自只做本人角色动作，或使用自建对象，不互相覆盖状态。
- 生产上某场景已被他人改变时，优先用自建测试账号/商品/请求复现前置并记录；无法复现时才记 `BLOCKED`，不擅自重置生产。
- 自建对象命名：显示名 `测试-<姓名>-<序号>`，商品/举报说明加 `【测试】<姓名>-<序号>`；在结果表登记账号邮箱与对象 ID，便于收尾清理和区分演示数据。

## 七、负责人执行前待办

- [ ] 确认自动化基线与当前 HEAD 一致；若派发前后端代码有变，重跑 `(cd backend && RUN_REAL_ACCEPTANCE=1 .venv/bin/python -m pytest -q)` 并记下新 run_id。
- [ ] 确认生产部署版本（抽查结果见第三节）；如生产不等于当前 HEAD，在任务 issue 明确测试目标版本。
- [ ] 确认生产 demo 初始核验（`demo-verify`）并保存结果；服务启动后的超时扫描会推进 `trade.timeout_scan`，以实际状态为准。
- [ ] 确认生产是否作为本轮验收主环境（含写流程），并排定场景分配与串行时间；代码修改后的回归统一在本地 SQLite+local 或生产重新部署后验证。
- [ ] 分发账号/对象访问方式：生产 manifest 私密分发（至少含 admin/admin2）；普通账号由成员自建或使用 demo 账号；确认生产 SMTP 可发验证码、成员有可收件邮箱；本地由成员自行 seed。
- [ ] 如需避免共享主管理员密码，可为 C 在生产执行 `app.manage seed --admin-email <测试管理员邮箱>` 创建独立测试管理员（负责人操作），或明确允许使用 admin/admin2。
- [ ] 创建标签、Project、3 个任务 Issue；把编号回填到本文件与成员。
- [ ] 明确截止时间与复核窗口；每位成员开始前在任务 issue 回填前置条件。
- [ ] 安排 feature issue 的范围决定（本轮补/延后/不补），避免成员自行扩需求。
- [ ] 收尾：复核证据、汇总 AC 状态、汇总人工结果、关闭任务 issue。

## 八、Issue 创建清单

| 任务 | 标题 | 指派 | 标签 | Project |
|---|---|---|---|---|
| A | `[测试任务] 移动端账户／商品／检索／收藏／评论展示与 PWA 人工验收` | 金婉怡 | `testing` `area:mobile` `area:account` `area:product` | Todo |
| B | `[测试任务] 移动端交易／IM／通知／我的业务与受限访问人工验收` | 孙含佳 | `testing` `area:mobile` `area:trade` `area:im` | Todo |
| C | `[测试任务] 管理端审核／举报／异常交易／分类统计人工验收` | 张新悦 | `testing` `area:admin` `area:governance` | Todo |

指派列是成员姓名，创建 Issue 时请选对应 GitHub 账号；如仓库使用不同用户名，按实际替换。

Project 自定义字段（如已建）：A/B `类型=Task`、`领域=移动端`；C `类型=Task`、`领域=管理端`；三者 `状态=Todo`；不建 `priority` 标签，任务本身都是全量验收；缺陷/缺口用表单里的严重级别或影响级别表达，需要时再加 Project 字段。如需按批次统计，可建 milestone（如 `人工验收-2026-11`）并挂三个任务及缺陷/缺口。

已新增 GitHub Issue 表单（新文件，可不提交）：

- `.github/ISSUE_TEMPLATE/task.yml`：人工验收任务；
- `.github/ISSUE_TEMPLATE/bug.yml`：缺陷（需求已实现但行为错误）；
- `.github/ISSUE_TEMPLATE/feature.yml`：需求缺口（未实现/部分实现/缺界面入口/结果不可见）。

如果暂时不想在仓库启用表单，删除 `.github/` 即可；三个任务 Issue 已发布到 GitHub，后续按 Issue 正文执行。成员新建 Bug/Feature 时也可复制表单内容手填。

标签只保留 `testing` 与 `area:*`（缺陷/缺口另加 `bug`/`feature`）；`priority:P0` 不建——三个任务都是全量验收，优先级没有区分作用。A 拆成 `area:account` + `area:product`，B 拆成 `area:trade` + `area:im`，C 保持 `area:governance`。

需要创建的标签（可选命令）：

```bash
gh label create testing --color 1D76DB --description "人工验收/测试任务"
gh label create feature --color A2EEEF --description "需求缺口：未实现/部分实现/缺界面入口"
gh label create "area:mobile" --color 5319E7 --description "移动端用户侧"
gh label create "area:admin" --color 5319E7 --description "管理端"
gh label create "area:account" --color 0E8A16 --description "账户生命周期与权限"
gh label create "area:product" --color 0E8A16 --description "商品发布、审核、检索、收藏与分类展示"
gh label create "area:trade" --color 0E8A16 --description "请求、约定、确认、取消与评价"
gh label create "area:im" --color 0E8A16 --description "IM、通知、待办与我的业务"
gh label create "area:governance" --color 0E8A16 --description "审核、举报、异常、统计"
gh label create "blocked-ui" --color FBCA04 --description "缺界面入口，无法按需求验证"
```

`bug` 为 GitHub 默认标签；若不存在，先 `gh label create bug --color D73A4A`。

Project 建议：
1. 新建 Board 项目，Status 改为 `Todo / In Progress / In Review / Done`；
2. 自定义字段 `类型`（Task / Bug / Feature）、`领域`（移动端 / 管理端 / 跨端）；
3. Workflows：Auto-add to project、Item closed → Done；
4. 三个任务 Issue 加入 Project 并设 Todo，Bug/Feature 由成员创建后自动加入。

## 九、缺陷与需求缺口的区别

| 情形 | 用哪个模板 | 处理 |
|---|---|---|
| 需求已实现，但页面行为/提示/状态错误 | `缺陷`（`bug.yml`） | 直接修复：`fix/<issue>-<slug>` → PR `Closes #<bug>` |
| 需求未实现、部分实现、缺页面入口、结果不可见 | `需求缺口`（`feature.yml`） | 先登记；负责人决定「本轮补/延后/不补」；本轮补才实现：`feat/<issue>-<slug>` → PR `Closes #<feature>` |
| 需求本身有歧义或与实现冲突 | `需求缺口`，类型选「与需求规则不一致/待决定」 | 负责人决定，必要时改需求文档；成员不擅自改口径 |
| 缺账号/设备/环境且无法自建测试数据复现 | 任务 issue 记 `BLOCKED` | 不新建 bug/feature，写明原因与所需支持 |
| 自动化已覆盖且 PASS 的规则 | 不建 issue | 页面只核对入口与展示；不把人工重看当新增证据 |

模板字段（与 `.github/ISSUE_TEMPLATE/bug.yml`、`feature.yml` 一致，无法使用表单时按此手填）：

- **缺陷**：严重级别（P0—P3）、发现任务、环境（HEAD/manifest tag/页面/浏览器视口/角色）、复现步骤、预期结果、实际结果、复现概率、证据（脱敏）、需求依据、是否属自动化可判定范围、修复与验证、提交检查。
- **需求缺口**：缺口类型（缺界面入口/未实现/部分实现/展示缺失/不一致/BLOCKED-UI）、影响级别（阻塞验收/主流程/局部/待决定）、发现任务、需求依据（精确到 AC）、现状、期望（引用原文）、影响与边界、证据、负责人决定（本轮补/延后/不补）、实现与验证、提交检查。

要求：
- Bug/Feature 的 `Parent` 写发现它的任务 Issue；修复 PR 必须 `Closes #<对应 issue>`。
- 一个 PR 只关闭一个 Bug/Feature，不同时关闭任务 Issue；任务 Issue 由负责人复核后手动关闭。
- P0/P1 缺陷修复前，相关范围不得宣告通过；修复后必须按原步骤回归，回归证据补在 Bug issue。
- Feature 延后/不补时，对应 AC 不能记为「已实现」，任务 issue 保留残留缺口并由负责人决定是否接受。

## 十、分支、提交与 Review

```text
发现 → 建 Bug/Feature issue（assign 自己，Project: Todo）
     → 本地修复/补齐（分支 fix/ 或 feat/）
     → 本地验证（相关测试 + 构建；后端改动跑自动验收或与负责人商定的等价范围）
     → PR（正文 Closes #issue；Reviewer: 袁尚峰；评论“申请 review”）
     → 负责人 review、合并（成员不自行合并，除非负责人明确授权）
     → Bug/Feature 自动关闭（未自动则手动关闭），Project: Done
     → 回到任务 Issue 按原步骤回归、勾选结果、附证据
     → 负责人复核 → 任务 Issue: In Review → Done
```

PR 正文至少包含：关联 issue、复现/需求依据、修复或补齐内容、验证命令与结果、影响范围、脱敏截图（可选）。不要提交 `var/`、截图、manifest、密码或生产配置。

PR 正文模板：

```markdown
## 关联
Closes #<缺陷或需求缺口编号>
Parent: #<人工验收任务编号>

## 问题/缺口
<复现步骤与预期/实际，或需求 AC 与现状>

## 修改
<改动点；只列必要内容>

## 验证
- [ ] 本地 SQLite+local 启动并回归原步骤
- [ ] 相关自动化测试/构建（写命令与结果）
- [ ] 影响范围内的页面回归（贴脱敏截图或步骤）

## 影响与风险
<可能影响的角色/场景/AC；是否需要重新部署或重置演示数据>
```

分支示例：

```bash
git switch -c fix/<issue>-<slug>     # 缺陷
git switch -c feat/<issue>-<slug>    # 需求缺口
# 修改、验证、提交后
git push -u origin <branch>
```

负责人合并后，成员在 post-merge HEAD 上回归；不要直接把未合并分支部署到生产。

## 十一、已知候选（仅核对起点，未验证，不能当结论）

代码只读检查发现以下「接口有、前端疑似无入口」的情况，供对应成员在需求核对时确认；**实测确认前不得写成缺陷或需求缺口**：

1. `GET /api/v1/products/{id}/edit-history` 存在，移动端与前端均未检索到调用 → 可能影响 US-02-AC-03、US-12-AC-07（编辑历史/D-43），请 B 在「我的交易」核对，A 在商品编辑侧核对。
2. `GET /api/v1/products/{id}/review-records` 存在，前端未检索到调用 → 可能影响 US-02-AC-02 的「独立审核记录」是否要求可查看，请 A 核对；若属需求歧义，交负责人决定，不直接判缺口。
3. 受限商品匿名结果、事项会话只读等最近改动路径，重点回归入口与不泄露身份（A/B/C 交叉核对）。

## 十二、证据与脱敏

- 目录：`var/manual-acceptance/<run_id>/<member>/`，`run_id` 建议 `20261102-<manifest tag 前 8 位>`；本地与生产分开子目录。
- 文件命名：`A-P0-03-01.png`、`B-AC-US-07-04.md` 等；每张截图对应检查号。
- 记录字段：检查号、HEAD、环境（生产/本地）、manifest tag、浏览器/OS/视口、角色、步骤、预期、实际、结论、证据文件、缺陷/缺口号、时间。
- 自建数据登记：自建账号邮箱（不记密码）、自建商品/举报/交易 ID、创建时间；用于区分演示数据、复核与收尾清理。
- 不记录/不截图：密码、token、Cookie、连接串、签名 URL 参数、完整对象 key、manifest 内容、他人私人信息。
- 截图可留在本地证据目录；Issue 评论只贴脱敏摘要或少量打码截图。

## 十三、未覆盖与边界

- 真实邮件投递（注册/找回密码/换邮箱）：依赖真实收件箱，列 P2；不可用记 BLOCKED，不算通过。
- 100 用户/1 万商品性能压测、Safari/实体手机、多实例 WebSocket 广播、备份恢复演练、OSS 生命周期/WORM、生产发布验收：本轮不安排，另行计划。
- 7 天超时通过测试受控时钟验证（自动化），不要求人工等待；现场只核对超时后的状态表达与处置入口。
- 生产环境测试不等于生产发布验收；人工记录按实际执行结果更新。

## 十四、收尾

1. 每个任务 issue 必须有：结果表、AC 状态表、证据目录、缺陷/缺口清单、未执行项说明。
2. 负责人逐项复核；P0 全 PASS 且范围内 AC 均为「已实现」或负责人书面接受缺口后，任务才可关闭。
3. 汇总三个任务的 AC 状态与缺陷：汇总浏览器人工执行结果与验证范围；不把自动化结论继承为人工 PASS。
4. 关闭 Bug/Feature 后确认 Project 状态一致；未关闭项保留并说明影响。
5. 生产验收会产生自建账号/商品等测试数据：证据收集完成后，由负责人决定是否按 `docs/development/部署说明.md` 的生产数据重新初始化节重置并重新 demo-seed；重置前确认没有待复核证据依赖当前数据，成员不自行重置。
