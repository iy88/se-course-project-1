<!--
Version: 0.1.30
Version-Datetime: 2026-10-29T15:50:59+08:00
-->

# 校园二手交易与物品流转平台

## llm-test-only 分支说明

本分支保留后端 `backend/`、桌面管理端 `frontend/admin/` 和移动PWA `frontend/mobile/` 的开发实现，运行期数据位于被忽略的 `var/`。开发决策与运行入口见[开发阶段技术决策](bits/开发阶段技术决策.md)。

2026-10-28同步需求主线 `c4ee232`，A／B报告均已确认。随后按合并后的需求开展三端实现对齐、隔离副本并行开发和多轮代码审查；需求对应实现、修复轮次及实际验证结果见[需求同步并行修改计划](bits/需求同步并行修改计划.md)。历史测试及人工核验仅代表各自记录的范围，本轮自动化回归不替代系统人工验收。下文需求阶段范围约束适用于需求材料维护。

本目录保存校园二手交易与物品流转平台的需求分析交付材料。全部14个主用例、14个用户故事及16个领域类均有独立详细文档。01—08按顺序构成需求规格说明书正文，详细材料以各目录索引为入口；正文详细展开关键US、UC、类及SC并展示关键图。需求正文及US／UC／SC／领域类分析已于2026-10-23获项目负责人确认，BR／TR已讨论接受；确认范围见[需求基线](docs/requirements/08-需求基线.md)。

## 项目运行与配置

### 环境与目录

本节适用于 `llm-test-only` 分支的开发实现。准备 Python 3.12及以上、uv、Node.js 22及以上及npm；Python依赖由 [uv.lock](backend/uv.lock) 固定，两个前端分别使用各自的 `package-lock.json`。以下步骤从仓库根目录开始，三个服务分别在独立终端运行。

| 服务／数据 | 位置 | 本地地址／用途 |
|---|---|---|
| FastAPI后端 | `backend/` | `http://127.0.0.1:8000`；业务API前缀 `/api/v1` |
| 移动用户端 | `frontend/mobile/` | `http://localhost:5173`；移动布局及PWA |
| 桌面管理端 | `frontend/admin/` | `http://localhost:5174`；审核、共享处理池及管理处置 |
| SQLite数据库 | `var/db/app.db` | 启动时自动建表，已有SQLite库增量补齐冻结计时字段 |
| 本地图片存储 | `var/storage/` | 上传图片，经后端签名URL访问 |

`var/`、`.env`、虚拟环境、`node_modules/`及构建目录均由Git忽略。保留已有数据库和图片目录即可保留业务数据，不需要为升级删除数据库。

### 后端配置

配置定义见 [config.py](backend/app/core/config.py)。环境变量优先于 `.env`，未设置的项采用代码默认值；修改后重启后端。配置文件按**启动时的工作目录**查找，因此下列命令统一在 `backend/` 内执行，配置文件放 `backend/.env`，不放仓库根目录。

先从[配置示例](backend/.env.example)创建本地配置，在 `backend/` 目录执行：

```bash
# -n 保留已经存在的 .env
cp -n .env.example .env
```

示例默认使用无Redis的本地开发模式，关键配置为：

```dotenv
ENVIRONMENT=dev
REDIS_URL=
STORAGE_BACKEND=local
DEV_EXPOSE_VERIFICATION_CODE=true
```

不要覆盖已有 `.env`；按需要合并这些配置。留空 `REDIS_URL` 使用进程内KV，验证码与频控状态会在进程重启时丢失。若使用Redis，改为 `REDIS_URL=redis://127.0.0.1:6379/0` 并先启动对应服务；默认值就是该地址。已配置Redis时连接失败会导致相关请求报错，不应把它当成自动切换到内存模式。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `APP_NAME` | `CampusMarket API` | 应用及健康检查名称 |
| `ENVIRONMENT` | `dev` | 开发验证码返回条件之一；改为 `prod` 不会自动接入生产服务 |
| `DATABASE_URL` | 仓库内 `var/db/app.db` 的绝对SQLite URL | 格式为 `sqlite+aiosqlite:///...`；本期仅实现SQLite |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | 非空使用Redis，空字符串使用内存KV |
| `STORAGE_BACKEND` | `local` | 使用本地存储；`oss`仅接口桩，不能作为可用配置 |
| `STORAGE_LOCAL_ROOT` | 仓库内 `var/storage` 的绝对路径 | 自定义相对路径按后端启动目录解析 |
| `JWT_SECRET` | 代码中的固定开发值 | 登录令牌签名密钥；共享环境中替换为独立随机值，HS256至少32字节 |
| `JWT_ALGORITHM`／`JWT_EXPIRE_DAYS` | `HS256`／`7` | 令牌签名算法及有效天数 |
| `FILE_URL_SECRET`／`FILE_URL_EXPIRE_SECONDS` | 固定开发值／`3600` | 图片URL签名密钥及有效秒数；密钥单独生成 |
| `DEV_EXPOSE_VERIFICATION_CODE` | `true` | 仅与 `ENVIRONMENT=dev` 同时满足时返回 `dev_code` |
| `TRADE_CONFIRM_TIMEOUT_DAYS` | `7` | 单方完成确认的有效等待天数，冻结期间暂停累计 |
| `TIMEOUT_SCAN_INTERVAL_SECONDS` | `60` | 后台超时扫描间隔秒数 |
| `COMMENT_MAX_LENGTH` | `500` | 评论长度上限 |
| `COMMENT_RATE_LIMIT_COUNT`／`COMMENT_RATE_LIMIT_SECONDS` | `3`／`60` | 每用户评论允许次数／窗口秒数 |

自定义数据库绝对路径示例为 `DATABASE_URL=sqlite+aiosqlite:////srv/campus/app.db`；自定义相对数据库路径按后端启动目录解析。未配置数据库与存储路径时，默认路径直接由仓库位置计算。

可在后端依赖安装后运行以下命令生成一个随机密钥，分别生成两次后将结果填入 `JWT_SECRET` 和 `FILE_URL_SECRET`：

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

前端沿用同源 `/api` 与 `/ws` 代理访问后端。

当前没有真实邮件发送通道。开发模式的注册、找回密码和换邮箱通过接口返回的 `dev_code` 联调，界面会显示开发验证码；新用户注册仍须先获取并提交正确验证码。关闭该开关仅停止返回验证码，不会启用真实发信。

### 安装、初始化与启动

终端一：安装后端依赖、初始化演示数据并启动API。

```bash
cd backend
uv sync --locked
uv run python -m app.seed
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

种子脚本创建管理员、初始分类、禁发条目、演示用户及4件示例商品；按脚本中的账号／名称／标题检查已存在数据并跳过，不重置已有账号密码。仅需首次初始化或补齐演示数据时运行；后续直接启动API。演示数据直接写入，不代表真实邮箱验证或人工审核。

| 用途 | 邮箱 | 初始密码 |
|---|---|---|
| 管理员（管理端登录） | `admin@campus.edu` | `admin123456` |
| 张同学（移动端登录） | `zhang@campus.edu` | `secret123` |
| 李同学（移动端登录） | `li@campus.edu` | `secret123` |
| 王同学（移动端登录） | `wang@campus.edu` | `secret123` |

终端二：从仓库根目录启动桌面管理端。

```bash
cd frontend/admin
npm ci
npm run dev -- --strictPort
```

终端三：从仓库根目录启动移动用户端。

```bash
cd frontend/mobile
npm ci
npm run dev -- --strictPort
```

依赖已安装且锁文件未变化时，可直接运行各端启动命令。`--strictPort` 在指定端口被占用时直接报错，避免Vite自动改端口后访问错服务。前端当前不读取 `VITE_API_URL` 等环境变量，API统一使用同源 `/api/v1`，WebSocket使用同源 `/ws`；两端 [Vite配置](frontend/mobile/vite.config.js)及[管理端配置](frontend/admin/vite.config.js)将 `/api` 和 `/ws` 代理到本机8000端口。更换后端地址／端口时，同时修改两端代理目标并重启Vite。

后端启动后可检查：

```bash
curl http://127.0.0.1:8000/api/health
```

交互式API文档为 `http://127.0.0.1:8000/docs`，OpenAPI描述为 `/openapi.json`。管理端从共享池认领事项后处理；私人交易读取与处置须使用本人认领且真正关联的事项，不能把管理员登录或先前商品审核当作任意交易权限。

### 前端开发缓存与排错

两端 Vite 的依赖预构建缓存分别位于各自项目根目录：`frontend/admin/.vite/`、`frontend/mobile/.vite/`。该目录已被 `.gitignore` 忽略，不写入共享或重装的 `node_modules`。安装或更新依赖前先停止对应端的 Vite 开发服务，完成后重新启动；不要依赖旧开发服务继续使用重新安装前的预构建结果。若出现 `504 Outdated Optimize Dep`，停止并重新启动对应端 Vite。浏览器仍持有旧页面资源时，刷新当前页面即可更新该页缓存。

### 回归、构建与预览

各命令分别从仓库根目录执行：

```bash
# 后端测试：临时SQLite、内存KV及临时图片目录
(cd backend && uv run pytest -q)

# 移动端生产构建
(cd frontend/mobile && npm run build)

# 管理端生产构建
(cd frontend/admin && npm run build)
```

真实 HTTP 生命周期测试补充 pytest 夹具测试：对运行中的开发服务与开发库按现有 10 个阶段执行真实流程，会新增账号、商品、图片、交易与通知等演示数据（不可清理，勿对生产运行）。覆盖核对只统计检查项编号与实际执行状态，不代表全部验收条件语义已验证；说明见 [e2e_lifecycle](backend/tests/e2e_lifecycle/README.md)：

```bash
cd backend/tests/e2e_lifecycle
../../.venv/bin/python e2e_runner.py --base-url http://127.0.0.1:8000
```

`--db-path` 与 `--results-dir` 未显式指定时默认使用仓库内 `var/db/app.db` 与 `var/e2e-results`；后端使用其他数据库时再传 `--db-path`。

构建产物分别位于 `frontend/mobile/dist/`、`frontend/admin/dist/`。本轮需求对齐后的自动化验证结果见[并行修改与审查计划](bits/需求同步并行修改计划.md)；最近一次真实开发环境 API 测试、补充数据与缺陷记录见[开发环境真实API测试与生命周期数据](bits/开发环境真实API测试与生命周期数据.md)。命令构建、真实 HTTP 测试通过与人工功能验收分别记录。

先启动后端，再在两个独立终端预览构建产物：

```bash
(cd frontend/mobile && npm run preview -- --port 4173 --strictPort)
```

```bash
(cd frontend/admin && npm run preview -- --port 4174 --strictPort)
```

Vite预览沿用现有开发代理，可在本机联调；正式托管静态产物时需自行配置 `/api` 的HTTP反向代理、`/ws` 的WebSocket升级，以及前端路由回退到 `index.html`。两端均使用根路径，宜用不同域名或端口提供各自根目录，不直接拼接到同一站点的任意子路径。移动端PWA的Service Worker由生产构建生成，安装与缓存需在HTTPS或localhost安全上下文验证；业务操作仍依赖在线API。

局域网手机访问时，可使用 `npm run dev -- --host 0.0.0.0 --strictPort`，手机访问开发机IP的5173端口；代理仍由开发机连接本机后端。普通局域网HTTP可用于页面联调，但不等于已满足PWA安装条件。

当前运行方案面向单进程开发：WebSocket连接管理在进程内，内存KV亦不跨进程共享，后台扫描随后端启动。MySQL、OSS、真实邮件与多实例广播尚未实现，不因静态构建成功就视为生产部署完成。

## 成员分工

需求成果确认已登记；当时34张图稿（含UC-03—UC-16独立用例图）已于2026-10-26由用户确认审阅通过；13张变化图稿及相关修订已于2026-10-26获用户确认；成员按实际完成的内容记录贡献，见 [A报告A.8](docs/需求分析质量验证报告.md#a8-成员贡献与人工责任)。

## 文件位置与命名

| 位置 | 存放内容与命名 |
|---|---|
| `docs/需求规格说明书.md` | 由01—08生成的整合需求规格说明书 |
| `docs/requirements/` | 01—08线性章节；关键材料从独立源文件展开 |
| `docs/appendices/user-stories/` | 14份详细用户故事、验收条件及类协作，入口 [用户故事索引](docs/appendices/user-stories/index.md)，与用例分开维护 |
| `docs/appendices/use-cases/` | 14份详细主用例、66项子用例及类协作，入口 [用例索引](docs/appendices/use-cases/index.md)；图仍放 models |
| `docs/appendices/scenarios/` | 12份独立详细场景，入口 [场景索引](docs/appendices/scenarios/index.md)；第05章保留总览及动态模型，第07章保留验收条件 |
| `docs/appendices/class-analysis/` | 详细类分析材料，入口 [类分析索引](docs/appendices/class-analysis/index.md)；图仍放 models |
| `docs/appendices/` | 附录及附件组织入口 [附录索引](docs/appendices/index.md)，引用现有材料，不复制另一套正文／证据 |
| `docs/需求分析质量验证报告.md` | A 报告，汇总确认、模型检查、最终验收 review 及问题复核记录 |
| `docs/AI智能体使用验证报告.md` | B 报告，汇总实质 AI 贡献、人工取舍、核验与证据索引 |
| `docs/appendices/models/` | 报告图（用例、活动、类、状态、上下文图等）的可编辑源文件目录，例如 `.puml`、`.mmd`；PNG 集中在 docs/appendices/rendered，不保存 SVG |
| `docs/appendices/rendered/` | `.puml`／`.mmd` 统一渲染的 PNG，入口 [渲染索引](docs/appendices/rendered/README.md) |
| `docs/appendices/evidence/` | 业务决定及讨论依据、实际形成的验证证据；入口 [证据索引](docs/appendices/evidence/index.md)，E 编号与 D 决定连续编号；编号重排时以 evidence 中映射表为准 |
| `docs/appendices/ai-usage/` | AI关键分析贡献、必要上下文及交互原文、人工取舍和核验、填写模板，索引见 [index.md](docs/appendices/ai-usage/index.md)，填写规则见 [AGENTS.md](AGENTS.md) |
| `docs/appendices/prototype/` | 按用户故事组织的多页 HTML 原型及 [说明](docs/appendices/prototype/README.md)，一个 HTML 文件一个页面，示例数据不代表后台功能实现 |
| `docs-pdf/` | 由Pandoc生成的PDF交付副本，保持docs的目录结构，文档链接使用PDF目标；该目录由Git忽略 |
| `scripts/` | [Python构建说明](scripts/README.md)：同步关键材料、生成说明书、渲染PNG，以及按SHA-256增量导出和检查PDF |
| `bits/` | 项目协作复盘及本分支开发阶段技术决策与运行指南；成员贡献、问题处理及需求边界分别见 A 报告与需求基线 |

文件按“编号-名称”组织；编号重排时同步更新文件名、索引及引用，需要的版本、日期按版本规范记录，需求确认事实集中登记在需求基线和证据中。正文通过相对链接及编号引用附件；尚未开展的工作不预填结果。

`docs/`中的交付材料只引用`docs/`内的本地文件，不引用仓库根AGENTS.md／README.md、bits、scripts或其他目录。必要决定、背景及依据保留在docs内，使交付材料能够独立阅读；历史引文中的文件名不作为现行依赖。脚本用法和仓库操作规范保留在docs外的指导文件中，工作笔记及仓库指导文件可以引用docs。

## 范围与验证约束

- 原型作为本项目需求分析交付材料，包含按用户故事组织的15个HTML页面。
- 场景分析与原型材料已成文；场景及原型走查由张新悦、孙含佳、金婉怡分别于 2026-10-23、2026-10-23、2026-10-25 完成（A.5.2—A.5.4、A.6.2—A.6.4、E-11—E-13）。图稿可读性记录按实际范围保留，系统运行验收在实现阶段开展。
- 多页 HTML 原型按用户故事组织界面示例，作为最终 review 的补充材料，不以静态页面证明后台功能已实现。
- 需求清单覆盖题目全部十项核心功能；14个主用例均有详细文档，主报告以交易闭环展开用户故事、场景和关键类，并展示三个代表性用例。
- 业务规则、术语及未决问题统一维护；性能目标按第 6 章登记的来源与状态表达，实测结论待系统实现后形成。教学模拟如实标注，AI 自检不能替代人工确认。
- 各成员仅记录 AI 对需求分析有实质影响的关键建议、人工取舍及证据，须有必要上下文并注明姓名；人工直接决定由 evidence 承载。实质分析开始时起草ai-usage，讨论中途保存关键prompt／output及实际反馈原文、来源定位与人工取舍；不要求完整聊天或环境、Git、一般文档维护流水，也不要求每次提交补档。构建与导出工具按用户明确要求专项记录于[AI-14](docs/appendices/ai-usage/AI-14-2026-10-23-文档构建与PDF增量导出.md)，不扩大日常维护的默认建档范围。开发阶段无需AI使用档案，开发决策与验证结果按代码、测试及必要技术笔记保留。详细边界见 AGENTS.md；B 报告由组长汇总。袁尚峰统筹最终review与汇总；三位成员已在各自设备和Git账号下完成走查及个人AI证据补充，实际贡献见A报告A.8。

## 图文件与索引规范

- 报告图可编辑源文件统一放在 `docs/appendices/models/`，PNG 集中在 `docs/appendices/rendered/`，不散落到章节目录；证据截图、原始资料仍放 `docs/appendices/evidence/`，原型材料放 `docs/appendices/prototype/`。
- 图文件采用“编号-名称”，例如 `ACT-02-交易请求与双方确认.puml`；图模型保留可编辑源文件，同名 PNG 集中到 `docs/appendices/rendered/`，不保存 SVG 导出图；多页 HTML 原型直接维护 HTML 页面。
- Markdown 正文以相对路径链接引用源文件，并可用图片语法展示 `docs/appendices/rendered/` 中已有的 PNG；图源与图片同步，不插入不存在的图片链接。
- [图索引](docs/appendices/models/index.md) 登记图编号、名称、源文件、正文位置、关联证据 evidence，以及可选关联项目／分析项；链接必须定位实际文件或条目。
- 不交付数据字典，不开展传统数据建模；保留领域类分析、职责、关联、状态和必要业务概念。不得据此省略业务规则、权限或隐私约束。

## 草稿与版本规范

- `bits/` 为 notes，不使用 `draft-` 前缀，去前缀不代表内容已验证；其余未确认的业务文档以 `draft-` 开头；确认后去除前缀并修订引用。README 及配置属于仓库运行规范，不作为业务确认稿。
- 仅 `docs/` 下的文件及各目录的 `README.md`、`AGENTS.md` 需要记录 `Version: x.y.z` 和带时区的 `Version-Datetime: ISO8601`。文本在原生注释或正文中记录；`docs/` 中的二进制文件使用同目录 `<文件名>.version` 伴随文件记录。其他文件（包括工具源码、测试、配置及未来业务代码）不需要版本信息，由 Git 历史追踪。
- 每次 commit 前对需要版本信息的修改文件按最终内容统一递增版本号、更新版本时间，并与上一提交比较；时间不得在未来。同一提交前的多轮修改不逐轮登记版本或保留未提交即放弃的中间方案。删除文件无需更新版本。
- 文档拆分、改名后同步修订引用。图源按最终提交内容管理版本。

## 提交前操作

完整的智能体工作与提交前检查规则统一见 [AGENTS.md](AGENTS.md)，适用于每次 commit 和 amend；提交前须检查需求／规则边界、跨文档一致性、历史遗留及实际目录与 README／索引同步；由用户明确指出 AI 使用模型及工作负责人，逐文件确认 diff、归属和更改。成员提交时同样按该检查清单核对；此处仅保留入口，不配置可执行 Git hook。

## 当前阶段工作入口

- [项目协作复盘与后续工作方法](bits/项目协作复盘与后续工作方法.md)：根据本人及组员Git历史，归纳基线漂移、共享材料合并、覆盖与模型语义、证据记录、图稿和导出等问题，说明后续任务的组织方法。具体执行规则统一见[AGENTS.md](AGENTS.md#工作中的基线变更传播与交接强制)。

- [需求基线](docs/requirements/08-需求基线.md)：指定需求范围、纳入版本与确认记录。
- [需求分析质量验证报告](docs/需求分析质量验证报告.md)：A.7 登记问题处理与复核，A.8 记录成员实际贡献；最终交付版本及日期见 A.1。

01—08及整合说明书已去除草稿前缀；附录文件名已去除 `draft-`，档案与证据的确认状态以正文记录为准。A报告已于2026-10-26经袁尚峰确认去除 `draft-`；B报告已于2026-10-27经袁尚峰确认去除 `draft-`，确认依据见 [AI-20](docs/appendices/ai-usage/AI-20-2026-10-27-报告结构优化与语义审阅.md)。变更纳入文件时同步更新基线版本表及影响记录。

## 报告入口

- [需求规格说明书](docs/需求规格说明书.md)
- [附录与附件索引](docs/appendices/index.md)
- [需求分析质量验证报告](docs/需求分析质量验证报告.md)
- [AI 智能体使用验证报告](docs/AI智能体使用验证报告.md)
- [多页 HTML 原型](docs/appendices/prototype/README.md)
- [渲染图索引](docs/appendices/rendered/README.md)
- [证据索引 E-01—E-09、E-11—E-15](docs/appendices/evidence/index.md)

## 文档生成

详细US、UC、SC和类分析分别在对应目录维护；01—08的关键节选由构建脚本从这些源文件同步，按章节顺序生成整合说明书。

```text
python3 scripts/cli.py build
python3 scripts/cli.py check
```

### 图片重新导出

在项目根目录执行：

```bash
# 增量渲染：只重新导出源文件或产物摘要变化、PNG 缺失或 DPI 不符的图
python3 scripts/cli.py render

# 强制重新导出全部图
python3 scripts/cli.py render --force

# 渲染图片，同时同步章节和整合说明书
python3 scripts/cli.py build
```

脚本调用本机 PlantUML，将 `docs/appendices/models/*.puml` 导出为默认200 DPI的PNG，保存到 `docs/appendices/rendered/`；同时更新对应 `.png.version` 中的版本、渲染时间、源文件及PNG的SHA-256摘要，以及渲染索引。源文件摘要包含版本注释，因此仅修改图源版本头也会触发重新渲染。`render` 不同步需求正文，也不导出PDF；需要同步正文时使用 `build`。

仅同步正文用 `python3 scripts/cli.py report`，仅检查用 `python3 scripts/cli.py check`；原型直接维护HTML页面。分步构建及自定义DPI见[scripts说明](scripts/README.md)。

## PDF 增量导出与检查

先同步Markdown正文，再导出PDF；以下命令在项目根目录执行：

```text
python3 scripts/cli.py report
python3 scripts/cli.py pdf
python3 scripts/cli.py pdf --check --pdf-link-check on
```

导出范围为 `docs/` 下全部Markdown，输出到 `docs-pdf/` 并保持目录层级；主说明书对应 `docs-pdf/需求规格说明书.pdf`。图片、图源及HTML原型等引用附件一并复制。导出前应已消除docs外的本地文件引用，不以导出时转成文字路径代替源文档修正，不生成 `_repository/`。

默认使用SHA-256增量导出。缓存 `docs-pdf/.export-cache.json` 分别保存源文件、渲染输入和产出PDF摘要；未变化且产出完整的PDF直接复用。源文档、内嵌图片、字体、模板、脚本、渲染器版本或排版参数变化时重导受影响文件；PDF缺失或内容损坏时自动重导。附件仅在内容变化时复制；首次无缓存时正常生成，缓存与PDF均由Git忽略。

```text
python3 scripts/cli.py pdf --only docs/requirements/02-用户需求.md
python3 scripts/cli.py pdf --force --only docs/requirements/02-用户需求.md
```

`--only` 可重复指定文件或目录，`--force` 强制重导所选范围。首次交付应运行完整的增量导出命令，以保证跨PDF目标齐全；选定导出不会递归生成其他PDF。默认并行4个任务，可用 `--jobs 1` 顺序运行。

PDF依赖Pandoc、XeLaTeX、`fc-match`及本机字体：中文苹方 `PingFang SC`、西文 `Times New Roman`、代码 `Fira Code`；PNG内中西文统一苹方。脚本按实际字体文件及集合索引加载，避免字体名查找失败。检查依赖qpdf核对实际链接注解、页内锚点及跨PDF目标，pdftotext扫描缺字；使用 `--pdf-link-check on` 可要求执行链接检查。

跨PDF文件名以Unicode文件描述保存，支持中文和空格。阅读时保留整个 `docs-pdf/` 目录结构，并使用支持本地跨PDF跳转的阅读器；红色为跨文件链接配色，不表示链接错误。字体、宽表、缓存失效条件及更多参数见[scripts说明](scripts/README.md#pdf-导出)。
